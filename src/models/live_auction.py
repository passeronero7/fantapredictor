"""Live auction re-optimization: state, residual plan and maximum bids.

A static roster plan breaks at the second player sold. This module keeps the
auction state (who bought whom, for how much), re-solves the roster MILP of
``src.models.auction_optimizer`` for the slots still open, and turns the
optimizer's own trade-offs into a **maximum bid** per player:

    bid_max(p) = the price at which buying p leaves the plan exactly as good
                 as the best plan without p,

given the reference prices of everyone else. The objective gap
``V(with p) - V(without p)`` is converted to credits with the marginal value
of a credit (objective lost per credit when the budget tightens), refined by
one secant step on the real MILP, and capped by what the manager can legally
bid (remaining credits minus one per other open slot).

Speed comes from exact dominance pruning (see :func:`dominance_prune`): it
removes players who can never enter an optimal plan, so the optimum is
unchanged while the MILP shrinks.
"""

from __future__ import annotations

import difflib
import time
import unicodedata
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
import pandas as pd

from src.models.auction_optimizer import (
    DEPTH_WEIGHTS,
    MODIFIER_SLOT_WEIGHTS,
    AuctionOptimizationConfig,
    ROSTER_SLOTS,
    _Model,
    prepare_pool,
)

STATE_COLUMNS = ["giocatore", "acquirente", "prezzo"]
ROLE_ORDER = list(ROSTER_SLOTS)


# ---------------------------------------------------------------------------
# Auction log
# ---------------------------------------------------------------------------

def _key(text: object) -> str:
    """Accent-, case- and punctuation-insensitive lookup key."""
    value = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
    value = value.lower().replace(".", " ").replace("'", " ").replace("-", " ")
    return " ".join(value.split())


def resolve_player(query: object, pool: pd.DataFrame) -> int:
    """Row label in ``pool`` for a typed name or official id.

    Accepts the official Fantacalcio id (``source_ref``), the display name or
    the warehouse key, ignoring case, accents and punctuation, then a unique
    token-prefix match ("thuram k" finds "Thuram K.", "de ket" finds
    "De Ketelaere"). Raises ``KeyError`` with suggestions otherwise.
    """
    text = str(query).strip()
    if text.isdigit() and "source_ref" in pool:
        hit = pool.index[pd.to_numeric(pool["source_ref"], errors="coerce").eq(int(text))]
        if len(hit) == 1:
            return int(hit[0])
    key = _key(text)
    names = pool["player"].map(_key)
    keys = pool["player_normalized"].map(_key) if "player_normalized" in pool else names
    exact = pool.index[names.eq(key) | keys.eq(key)]
    if len(exact) == 1:
        return int(exact[0])

    def label(i: int) -> str:
        return f"{pool.at[i, 'player']} ({pool.at[i, 'team']}, {pool.at[i, 'role']})"

    if len(exact) > 1:
        raise KeyError(f"'{text}' is ambiguous: {', '.join(label(i) for i in exact)}")
    tokens = key.split()
    prefix = pool.index[names.map(lambda n: len(n.split()) >= len(tokens) and all(
        part.startswith(tok) for part, tok in zip(n.split(), tokens)))]
    if len(prefix) == 1:
        return int(prefix[0])
    candidates = list(prefix) or [
        pool.index[names.eq(name)][0]
        for name in difflib.get_close_matches(key, names.tolist(), n=5, cutoff=0.6)
    ]
    hint = ", ".join(label(i) for i in candidates[:6])
    raise KeyError(f"Unknown or ambiguous player '{text}'" + (f"; did you mean: {hint}" if hint else ""))


def read_state(path: Path) -> pd.DataFrame:
    """Load the auction log (``giocatore,acquirente,prezzo``); empty if absent."""
    if not Path(path).exists():
        return pd.DataFrame(columns=STATE_COLUMNS)
    state = pd.read_csv(path, dtype={"giocatore": str, "acquirente": str})
    missing = set(STATE_COLUMNS) - set(state.columns)
    if missing:
        raise ValueError(f"State file missing columns: {', '.join(sorted(missing))}")
    state = state.dropna(subset=["giocatore"]).copy()
    state["prezzo"] = pd.to_numeric(state["prezzo"], errors="raise").astype(int)
    if (state["prezzo"] < 1).any():
        raise ValueError("Every price must be at least 1 credit")
    state["acquirente"] = state["acquirente"].fillna("").astype(str).str.strip()
    if state["acquirente"].eq("").any():
        raise ValueError("Every sale needs an acquirente")
    return state[STATE_COLUMNS].reset_index(drop=True)


def resolve_state(state: pd.DataFrame, pool: pd.DataFrame) -> pd.DataFrame:
    """Attach pool row, role and team to each sale; reject double sales."""
    rows = []
    for record in state.to_dict("records"):
        index = resolve_player(record["giocatore"], pool)
        rows.append({**record, "row": index, "player": pool.at[index, "player"],
                     "team": pool.at[index, "team"], "role": pool.at[index, "role"]})
    resolved = pd.DataFrame(rows, columns=STATE_COLUMNS + ["row", "player", "team", "role"])
    dup = resolved["row"][resolved["row"].duplicated()]
    if not dup.empty:
        raise ValueError(f"Sold twice: {sorted(pool.loc[dup, 'player'])}")
    return resolved


def manager_summary(sales: pd.DataFrame, me: str, managers: int, budget: int) -> pd.DataFrame:
    """Credits and open slots per manager, with the largest legal bid.

    ``offerta_max`` keeps one credit for every other open slot. Managers who
    have not bought anything yet are shown as one aggregate row.
    """
    names = list(dict.fromkeys([me] + sales["acquirente"].tolist()))
    if len(names) > managers:
        raise ValueError(f"{len(names)} buyers in the log but the league has {managers} managers: {names}")
    total_slots = sum(ROSTER_SLOTS.values())
    rows = []
    for name in names:
        bought = sales[sales["acquirente"].eq(name)]
        open_by_role = {r: n - int(bought["role"].eq(r).sum()) for r, n in ROSTER_SLOTS.items()}
        if any(v < 0 for v in open_by_role.values()):
            raise ValueError(f"{name} holds more players than slots in a role: {open_by_role}")
        spent = int(bought["prezzo"].sum())
        open_slots = total_slots - len(bought)
        remaining = budget - spent
        if remaining < open_slots:
            raise ValueError(f"{name} cannot fill {open_slots} slots with {remaining} credits")
        rows.append({"acquirente": name, "spesi": spent, "rimasti": remaining,
                     "slot_aperti": open_slots,
                     **{f"aperti_{r}": v for r, v in open_by_role.items()},
                     "offerta_max": remaining - (open_slots - 1) if open_slots else 0})
    unseen = managers - len(names)
    if unseen > 0:
        rows.append({"acquirente": f"altri ({unseen}, nessun acquisto)", "spesi": 0,
                     "rimasti": budget, "slot_aperti": total_slots,
                     **{f"aperti_{r}": n for r, n in ROSTER_SLOTS.items()},
                     "offerta_max": budget - (total_slots - 1)})
    return pd.DataFrame(rows)


def market_factor(full: pd.DataFrame, sales: pd.DataFrame, managers: int, budget: int,
                  bounds: tuple[float, float] = (0.5, 2.0)) -> float:
    """Price level of the players still to be sold, from money conservation.

    Whatever the league has not spent yet will buy the slots still open.
    The factor is the credits left across all managers divided by the
    reference cost of the players needed to fill those slots (per role, the
    most expensive available players by reference). Early overspending on
    stars lowers it, underspending raises it; at the start it is ~1 because
    the dossier references split the same league budget.
    """
    money_left = managers * budget - float(sales["prezzo"].sum())
    available = full.drop(index=list(sales["row"]))
    reference_left = 0.0
    for role, slots in ROSTER_SLOTS.items():
        open_in_league = managers * slots - int(sales["role"].eq(role).sum())
        costs = available.loc[available["role"].eq(role), "auction_cost"]
        reference_left += float(costs.nlargest(max(open_in_league, 0)).sum())
    if reference_left <= 0:
        return 1.0
    return float(np.clip(money_left / reference_left, *bounds))


# ---------------------------------------------------------------------------
# Pruning
# ---------------------------------------------------------------------------

def _slot_weights(role: str) -> tuple[np.ndarray, np.ndarray]:
    count = ROSTER_SLOTS[role]
    depth = np.array(DEPTH_WEIGHTS[role][:count], dtype=float)
    modifier = np.array([MODIFIER_SLOT_WEIGHTS.get((role, d), 0.0) for d in range(1, count + 1)])
    return depth, modifier


def dominance_prune(frame: pd.DataFrame, keep: set[int], open_slots: dict[str, int]) -> pd.Index:
    """Rows that can never enter an optimal plan.

    Player q dominates p when, in *every* depth slot of the role, q's
    contribution (utility x slot weight + modifier premium x slot share) is
    at least p's and q costs no more. With at least as many free dominators
    as open slots in the role, any plan with p leaves one dominator unused,
    and swapping it into p's slot loses nothing, so p is never needed.
    ``keep`` rows (owned or quoted) are never dropped and never count as
    free dominators; ties are broken by row order so identical players do
    not eliminate each other.
    """
    drop: list[int] = []
    for role, block in frame.groupby("role"):
        free = block[~block.index.isin(keep)]
        need = max(open_slots.get(role, 0), 1)
        depth, modifier = _slot_weights(role)
        value = (np.outer(free["utility"].to_numpy(float), depth)
                 + np.outer(free["modifier_premium"].to_numpy(float), modifier))
        cost = free["auction_cost"].to_numpy(float)
        idx = free.index.to_numpy()
        tol = 1e-12
        for i in range(len(free)):
            no_worse = (value >= value[i] - tol).all(axis=1) & (cost <= cost[i])
            strictly = (value > value[i] + tol).any(axis=1) | (cost < cost[i])
            dominators = no_worse & (strictly | (idx < idx[i]))
            dominators[i] = False
            if int(dominators.sum()) >= need:
                drop.append(int(idx[i]))
    return pd.Index(drop)


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------

@dataclass
class LivePlan:
    roster: pd.DataFrame
    objective: float
    credit_value: float
    managers: pd.DataFrame
    my_budget_left: int
    my_max_bid: int
    seconds: float
    pool_size: int
    market_factor: float = 1.0


class _Context:
    """MILP for one auction state (sold players removed, own buys forced)."""

    def __init__(self, full: pd.DataFrame, sales: pd.DataFrame, me: str,
                 config: AuctionOptimizationConfig, keep: set[int], factor: float = 1.0):
        mine = sales[sales["acquirente"].eq(me)]
        sold_to_others = set(sales.loc[~sales["acquirente"].eq(me), "row"])
        available = full.drop(index=list(sold_to_others)).copy()
        # Market level for players still to be bought; own buys are replaced
        # by the price actually paid below.
        available["auction_cost"] = (available["auction_cost"] * factor).round().clip(lower=1)
        self.open_slots = {r: n - int(mine["role"].eq(r).sum()) for r, n in ROSTER_SLOTS.items()}
        owned = set(int(r) for r in mine["row"])
        pruned = dominance_prune(available, owned | set(keep), self.open_slots)
        frame = available.drop(index=pruned).copy()
        paid = dict(zip(mine["row"], mine["prezzo"]))
        frame["prezzo_pagato"] = frame.index.map(paid)
        frame["auction_cost"] = frame["prezzo_pagato"].fillna(frame["auction_cost"]).astype(float)
        self.labels = frame.index.to_numpy()
        self.position = {int(label): i for i, label in enumerate(self.labels)}
        self.frame = frame.reset_index(drop=True)
        self.config = config
        self.model = _Model(self.frame, config)
        self.owned = [self.position[o] for o in owned]
        self.costs = self.frame["auction_cost"].to_numpy(float)
        # The reserve is a planning buffer; confirmed legal purchases can
        # consume it. Always leave at least one credit per remaining slot.
        self.spend_cap = max(config.budget - config.reserve,
                             int(mine["prezzo"].sum()) + sum(self.open_slots.values()))
        self._utility = self.frame["utility"].to_numpy(float)
        self._premium = self.frame["modifier_premium"].to_numpy(float)

    def solve(self, forced=(), excluded=(), costs=None, cap=None):
        """(objective, assignment) with extra forced/excluded pool positions."""
        model = self.model
        n_slots = len(model.slots)
        lower, upper = model.base_lower.copy(), model.base_upper.copy()
        for p in list(self.owned) + list(forced):
            lower[n_slots + p] = 1.0
        for p in excluded:
            upper[n_slots + p] = 0.0
        saved = (model.base_lower, model.base_upper, model.config)
        model.base_lower, model.base_upper = lower, upper
        model.config = replace(self.config, budget=int(cap if cap is not None else self.spend_cap), reserve=0)
        try:
            assignment = model.solve(costs=self.costs if costs is None else costs)
        finally:
            model.base_lower, model.base_upper, model.config = saved
        value = sum(
            self._utility[p] * model.slots[s][2]
            + self._premium[p] * MODIFIER_SLOT_WEIGHTS.get(model.slots[s][:2], 0.0)
            for p, s in assignment
        )
        return float(value), assignment


class LivePlanner:
    """Re-optimizes the open slots given the auction log."""

    def __init__(self, players: pd.DataFrame, config: AuctionOptimizationConfig,
                 me: str = "io", managers: int = 8, market_scaling: bool = True):
        self.config = config
        self.me = me
        self.managers = managers
        self.market_scaling = market_scaling
        self.full = prepare_pool(players, config)
        self._cache: dict = {}

    def _context(self, state: pd.DataFrame, keep: set[int] = frozenset()):
        sales = resolve_state(state, self.full)
        manager_summary(sales, self.me, self.managers, self.config.budget)
        signature = (tuple(map(tuple, state.astype(str).to_numpy())), frozenset(keep))
        if signature in self._cache:
            return self._cache[signature]
        factor = (market_factor(self.full, sales, self.managers, self.config.budget)
                  if self.market_scaling else 1.0)
        context = _Context(self.full, sales, self.me, self.config, set(keep), factor)
        context.market_factor = factor
        base_value, assignment = context.solve()
        # Marginal value of a credit: objective lost when the budget the
        # plan actually uses shrinks by ~5% of the credits still to spend.
        used = float(context.costs[[p for p, _ in assignment]].sum())
        still_to_spend = used - float(context.costs[context.owned].sum())
        step = max(5.0, round(0.05 * still_to_spend))
        credit_value = 1e-9
        if sum(context.open_slots.values()):
            # At the end of an auction even a one-credit reduction may be
            # infeasible. That is a valid completed/minimum-cost plan.
            while step >= 1:
                try:
                    tighter, _ = context.solve(cap=used - step)
                except ValueError:
                    step = int(step // 2)
                    continue
                credit_value = max((base_value - tighter) / step, 1e-9)
                break
        result = (sales, context, base_value, assignment, credit_value)
        if len(self._cache) > 8:
            self._cache.clear()
        self._cache[signature] = result
        return result

    def plan(self, state: pd.DataFrame) -> LivePlan:
        """Best plan for the open slots (two MILP solves)."""
        started = time.perf_counter()
        sales, context, base_value, assignment, credit_value = self._context(state)
        managers = manager_summary(sales, self.me, self.managers, self.config.budget)
        mine = managers[managers["acquirente"].eq(self.me)].iloc[0]
        frame, model = context.frame, context.model
        owned = set(context.owned)
        rows = []
        for p, s in assignment:
            role, depth, _ = model.slots[s]
            rows.append({
                "role": role, "depth": depth, "player": frame.at[p, "player"],
                "team": frame.at[p, "team"],
                "stato": "preso" if p in owned else "obiettivo",
                "crediti": int(round(context.costs[p])),
                "expected_fantavoto": round(float(frame.at[p, "expected_fantavoto"]), 2),
                "p_plays": round(float(frame.at[p, "p_plays"]), 2),
            })
        roster = pd.DataFrame(rows)
        roster["_r"] = roster["role"].map(ROLE_ORDER.index)
        roster = roster.sort_values(["_r", "depth"]).drop(columns="_r").reset_index(drop=True)
        return LivePlan(
            roster=roster, objective=base_value, credit_value=credit_value,
            managers=managers, my_budget_left=int(mine["rimasti"]),
            my_max_bid=int(mine["offerta_max"]),
            seconds=time.perf_counter() - started, pool_size=len(frame),
            market_factor=context.market_factor,
        )

    def bid(self, state: pd.DataFrame, query: object) -> dict:
        """Maximum bid for one player (one or two extra MILP solves)."""
        label = resolve_player(query, self.full)
        sales = resolve_state(state, self.full)
        if label in set(sales["row"]):
            raise ValueError(f"{self.full.at[label, 'player']} is already sold")
        started = time.perf_counter()
        solved = self._context(state)
        if label not in solved[1].position:  # pruned: rebuild keeping him
            solved = self._context(state, keep={label})
        result = self._bid_at(solved, solved[1].position[label], self._legal_cap(sales))
        result["secondi"] = round(time.perf_counter() - started, 2)
        return result

    def _legal_cap(self, sales: pd.DataFrame) -> int:
        managers = manager_summary(sales, self.me, self.managers, self.config.budget)
        return int(managers.loc[managers["acquirente"].eq(self.me), "offerta_max"].iloc[0])

    def _bid_at(self, solved, p: int, legal: int, steps: int = 3) -> dict:
        _, context, base_value, assignment, credit_value = solved
        frame = context.frame
        chosen = {q for q, _ in assignment}
        ref = float(context.costs[p])
        role = frame.at[p, "role"]
        base = {"player": frame.at[p, "player"], "team": frame.at[p, "team"], "role": role,
                "riferimento": int(round(ref)), "nel_piano": p in chosen}
        if context.open_slots[role] == 0:
            return {**base, "offerta_max": 0, "motivo": f"nessuno slot {role} aperto",
                    "valore_vs_alternativa": 0.0, "se_lo_perdi": ""}
        if p in chosen:
            with_value = base_value
            without_value, without = context.solve(excluded=[p])
            entering = {q for q, _ in without} - chosen
            replaced = ", ".join(sorted(frame.loc[list(entering), "player"]))
        else:
            with_value, _ = context.solve(forced=[p])
            without_value = base_value
            replaced = ""
        gap = with_value - without_value
        refined = self._break_even(context, p, ref, gap, without_value, credit_value, steps)
        bid = int(np.floor(max(refined, 0.0)))
        return {**base, "offerta_max": min(bid, legal),
                "motivo": "limite di budget" if bid > legal else ("" if bid >= 1 else "non conviene"),
                "valore_vs_alternativa": round(gap, 4), "se_lo_perdi": replaced}

    @staticmethod
    def _break_even(context, p, ref, gap, without_value, credit_value, steps) -> float:
        """Price c where V(p forced at c) = V(best plan without p).

        f(c) = V(p at c) - V(without p) never increases with c and
        f(ref) = gap. Start from the linear estimate ref + gap / credit
        value, then bracket the root and interpolate on the real MILP.
        """
        def f(price: float) -> float:
            trial = context.costs.copy()
            trial[p] = price
            try:
                return context.solve(forced=[p], costs=trial)[0] - without_value
            except ValueError:  # over budget at this price
                return -np.inf

        lo = (ref, gap) if gap >= 0 else None   # f >= 0 here: buying is worth it
        hi = None if gap >= 0 else (ref, gap)   # f < 0 here
        guess = ref + gap / credit_value
        for _ in range(steps):
            guess = float(np.clip(guess, 1.0, context.spend_cap))
            if any(point and abs(guess - point[0]) < 0.5 for point in (lo, hi)):
                break
            value = f(guess)
            if value >= -1e-9:
                lo = (guess, value)
            else:
                hi = (guess, value)
            if lo and hi:
                guess = (lo[0] + (hi[0] - lo[0]) * lo[1] / (lo[1] - hi[1])
                         if np.isfinite(hi[1]) else (lo[0] + hi[0]) / 2)
            elif lo:   # still worth it: move up
                guess = max(lo[0] + lo[1] / credit_value, lo[0] + 1)
            else:      # still not worth it: move down
                guess = min(hi[0] + hi[1] / credit_value, hi[0] - 1)
        if lo is None:
            return 0.0 if hi[0] <= 1 else min(guess, hi[0] - 1)
        if hi is None:
            return lo[0]
        if not np.isfinite(hi[1]):
            return lo[0]
        return lo[0] + (hi[0] - lo[0]) * lo[1] / (lo[1] - hi[1])

    def plan_bids(self, state: pd.DataFrame) -> pd.DataFrame:
        """Maximum bid for every open target in the current plan (slower)."""
        sales = resolve_state(state, self.full)
        solved = self._context(state)
        legal = self._legal_cap(sales)
        context, assignment = solved[1], solved[3]
        owned = set(context.owned)
        return pd.DataFrame([
            self._bid_at(solved, p, legal) for p, _ in assignment if p not in owned
        ])
