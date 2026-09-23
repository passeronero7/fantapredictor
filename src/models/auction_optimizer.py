"""Budget-constrained optimizer for a complete Classic auction roster.

The optimizer consumes out-of-sample or simulated player forecasts.  It does
not train a model and deliberately keeps auction cost separate from the public
quotation used as a feature by upstream forecasts.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import csr_matrix, lil_matrix, vstack


ROSTER_SLOTS = {"P": 3, "D": 8, "C": 8, "A": 6}
DEPTH_WEIGHTS = {
    "P": (1.00, 0.22, 0.08),
    "D": (1.00, 0.96, 0.90, 0.82, 0.48, 0.38, 0.30, 0.24),
    "C": (1.00, 0.97, 0.92, 0.85, 0.62, 0.48, 0.36, 0.28),
    "A": (1.00, 0.97, 0.90, 0.72, 0.48, 0.32),
}
# Share of the defence modifier each slot feeds: the starting goalkeeper and
# the three best defenders always count; the fourth defender only when one of
# them does not play.
MODIFIER_SLOT_WEIGHTS = {("P", 1): 1.0, ("D", 1): 1.0, ("D", 2): 1.0, ("D", 3): 1.0, ("D", 4): 0.3}
# HiGHS stops by default within 0.01% of the optimum (~0.009 objective on a
# full roster), the same size as the objective gaps that separate
# near-equivalent plans and drive live bid limits. Solve to optimality.
MIP_REL_GAP = 1e-9


@dataclass(frozen=True)
class AuctionOptimizationConfig:
    budget: int = 500
    reserve: int = 0
    defence_modifier: bool = False
    reliability_weight: float = 0.25
    # d E[modifier points] / d(one player's expected vote), from
    # src.models.defence_modifier.calibrate on historical matchdays.
    modifier_marginal: float = 0.22
    # Players with at least this p_plays define each role's replacement
    # expected vote, the zero point of the premium.
    regular_p_plays: float = 0.7


def player_utility(frame: pd.DataFrame, reliability_weight: float = 0.25) -> pd.Series:
    """Risk-adjust expected fantasy contribution from Monte Carlo summaries."""
    expected = pd.to_numeric(frame["expected_fantavoto"], errors="coerce").fillna(0.0)
    plays = pd.to_numeric(frame["p_plays"], errors="coerce").fillna(0.0).clip(0.0, 1.0)
    reliable = pd.to_numeric(
        frame["p_horizon_median_good"], errors="coerce"
    ).fillna(0.0).clip(0.0, 1.0)
    availability = pd.to_numeric(
        frame.get("availability_factor", pd.Series(1.0, index=frame.index)),
        errors="coerce",
    ).fillna(1.0).clip(0.0, 1.0)
    multiplier = (1.0 - reliability_weight) + reliability_weight * reliable
    return expected * plays * multiplier * availability


def modifier_premium(frame: pd.DataFrame, config: AuctionOptimizationConfig) -> pd.Series:
    """Expected modifier points a GK/defender adds per matchday when starting."""
    if not config.defence_modifier or "expected_vote" not in frame:
        return pd.Series(0.0, index=frame.index)
    vote = pd.to_numeric(frame["expected_vote"], errors="coerce")
    plays = pd.to_numeric(frame["p_plays"], errors="coerce").fillna(0.0).clip(0.0, 1.0)
    availability = pd.to_numeric(
        frame.get("availability_factor", pd.Series(1.0, index=frame.index)),
        errors="coerce",
    ).fillna(1.0).clip(0.0, 1.0)
    # Zero point: the median expected vote of the role's regular starters in
    # this pool, i.e. whoever would otherwise fill the slot. (Centring on the
    # GK + best-three lineup average would make almost every premium
    # negative and, multiplied by p_plays, reward defenders who play less.)
    regular = plays.ge(config.regular_p_plays) & vote.notna()
    baseline = vote[regular].groupby(frame["role"][regular]).median()
    replacement = frame["role"].map(baseline)
    premium = config.modifier_marginal * (vote - replacement) * plays * availability
    return premium.where(frame["role"].isin(["P", "D"]), 0.0).fillna(0.0)


REQUIRED_COLUMNS = {
    "player", "team", "role", "auction_cost", "expected_fantavoto",
    "p_plays", "p_horizon_median_good",
}


def prepare_pool(players: pd.DataFrame, config: AuctionOptimizationConfig) -> pd.DataFrame:
    missing = REQUIRED_COLUMNS - set(players.columns)
    if missing:
        raise ValueError(f"Missing optimizer columns: {', '.join(sorted(missing))}")
    frame = players.copy()
    frame["role"] = frame["role"].astype(str).str.upper().str.strip()
    frame["auction_cost"] = pd.to_numeric(frame["auction_cost"], errors="coerce")
    # Filter before reindexing: every row-position lookup below assumes a
    # dense range(len(frame)) index.
    frame = frame[
        frame["role"].isin(ROSTER_SLOTS)
        & frame["auction_cost"].notna()
        & frame["auction_cost"].ge(1)
    ].copy().reset_index(drop=True)
    if frame["player"].duplicated().any():
        raise ValueError("Player names must be unique in the eligible pool")
    for role, count in ROSTER_SLOTS.items():
        if int(frame["role"].eq(role).sum()) < count:
            raise ValueError(f"Insufficient eligible {role} players")
    frame["utility"] = player_utility(frame, config.reliability_weight)
    frame["modifier_premium"] = modifier_premium(frame, config)
    return frame


class _Model:
    """Player-to-depth-slot assignment MILP over a prepared pool."""

    def __init__(self, frame: pd.DataFrame, config: AuctionOptimizationConfig):
        self.frame = frame
        self.config = config
        self.slots = [
            (role, depth, weight)
            for role, count in ROSTER_SLOTS.items()
            for depth, weight in enumerate(DEPTH_WEIGHTS[role][:count], start=1)
        ]
        self.variables = [
            (player, slot)
            for slot, (role, _, _) in enumerate(self.slots)
            for player in frame.index[frame["role"].eq(role)]
        ]
        n_players = len(frame)
        n_vars = len(self.variables)
        # Assignment rows (one player per slot, each player at most once),
        # plus a player-incidence matrix reused by exclusion cuts.
        self.incidence = lil_matrix((n_players, n_vars))
        slot_rows = lil_matrix((len(self.slots), n_vars))
        for index, (player, slot) in enumerate(self.variables):
            self.incidence[player, index] = 1.0
            slot_rows[slot, index] = 1.0
        self.incidence = self.incidence.tocsr()
        self.base = vstack([slot_rows.tocsr(), self.incidence])
        self.base_lower = np.concatenate([np.ones(len(self.slots)), np.zeros(n_players)])
        self.base_upper = np.concatenate([np.ones(len(self.slots)), np.ones(n_players)])
        self.player_of = np.array([player for player, _ in self.variables])
        self.slot_of = np.array([slot for _, slot in self.variables])

    def solve(
        self,
        costs: np.ndarray | None = None,
        utility: np.ndarray | None = None,
        exclusions: list[list[int]] = (),
        min_changes: int = 1,
    ) -> list[tuple[int, int]]:
        frame, config = self.frame, self.config
        costs = frame["auction_cost"].to_numpy(float) if costs is None else costs
        utility = frame["utility"].to_numpy(float) if utility is None else utility
        premium = frame["modifier_premium"].to_numpy(float)
        slot_weight = np.array([self.slots[s][2] for s in self.slot_of])
        modifier_weight = np.array([
            MODIFIER_SLOT_WEIGHTS.get(self.slots[s][:2], 0.0) for s in self.slot_of
        ])
        objective = -(utility[self.player_of] * slot_weight + premium[self.player_of] * modifier_weight)

        rows = [self.base, costs[self.player_of].reshape(1, -1)]
        lower = [self.base_lower, [-np.inf]]
        upper = [self.base_upper, [float(config.budget - config.reserve)]]
        total = sum(ROSTER_SLOTS.values())
        for previous in exclusions:
            mask = np.zeros(len(frame))
            mask[previous] = 1.0
            rows.append((mask @ self.incidence).reshape(1, -1))
            lower.append([-np.inf])
            upper.append([float(total - min_changes)])
        matrix = vstack([csr_matrix(r) for r in rows]).tocsr()
        solution = milp(
            c=objective,
            integrality=np.ones(len(self.variables)),
            bounds=Bounds(0.0, 1.0),
            constraints=LinearConstraint(matrix, np.concatenate(lower), np.concatenate(upper)),
            options={"time_limit": 60.0, "mip_rel_gap": MIP_REL_GAP},
        )
        if not solution.success or solution.x is None:
            raise ValueError(f"No legal roster found: {solution.message}")
        return [self.variables[int(v)] for v in np.flatnonzero(solution.x > 0.5)]

    def result(self, assignment: list[tuple[int, int]], costs: np.ndarray | None = None) -> dict:
        frame, config = self.frame, self.config
        rows = []
        for player, slot in assignment:
            role, depth, weight = self.slots[slot]
            row = frame.loc[player].to_dict()
            if costs is not None:
                row["auction_cost"] = float(costs[player])
            modifier_share = MODIFIER_SLOT_WEIGHTS.get((role, depth), 0.0)
            row.update({
                "depth": depth,
                "depth_weight": weight,
                "weighted_utility": float(row["utility"]) * weight
                + float(row["modifier_premium"]) * modifier_share,
            })
            rows.append(row)
        selected = pd.DataFrame(rows).sort_values(["role", "depth"])
        counts = selected.groupby("role").size().to_dict()
        if counts != ROSTER_SLOTS or selected["player"].duplicated().any():
            raise RuntimeError("Solver returned an invalid roster")
        total_cost = int(round(selected["auction_cost"].sum()))
        if total_cost > config.budget - config.reserve:
            raise RuntimeError("Solver returned an over-budget roster")
        return {
            "roster": selected.reset_index(drop=True),
            "total_cost": total_cost,
            "budget": config.budget,
            "reserve": config.reserve,
            "budget_remaining": config.budget - total_cost,
            "objective": float(selected["weighted_utility"].sum()),
            "defence_modifier": config.defence_modifier,
            "spend_by_role": {
                role: int(round(value))
                for role, value in selected.groupby("role")["auction_cost"].sum().items()
            },
        }


def optimize_auction_roster(
    players: pd.DataFrame,
    config: AuctionOptimizationConfig = AuctionOptimizationConfig(),
) -> dict[str, object]:
    """Select exactly 3P/8D/8C/6A under the auction budget with MILP.

    Players are assigned to ordered depth slots.  This avoids pretending that
    the eighth defender contributes as much season utility as a regular
    starter, while retaining a linear and exactly reproducible optimization.
    """
    model = _Model(prepare_pool(players, config), config)
    return model.result(model.solve())


def alternative_rosters(
    players: pd.DataFrame,
    config: AuctionOptimizationConfig = AuctionOptimizationConfig(),
    count: int = 5,
    min_changes: int = 3,
) -> list[dict[str, object]]:
    """The best roster plus ``count - 1`` runners-up.

    Each runner-up must differ from *every* earlier roster by at least
    ``min_changes`` players, so the list shows genuinely different plans
    rather than one-for-one swaps of a 1-credit bench player.
    """
    model = _Model(prepare_pool(players, config), config)
    results, chosen = [], []
    for _ in range(count):
        try:
            assignment = model.solve(exclusions=chosen, min_changes=min_changes)
        except ValueError:
            break
        chosen.append(sorted({player for player, _ in assignment}))
        results.append(model.result(assignment))
    return results


def selection_robustness(
    players: pd.DataFrame,
    config: AuctionOptimizationConfig = AuctionOptimizationConfig(),
    draws: int = 100,
    cost_sigma: float = 0.25,
    utility_sigma: float = 0.05,
    seed: int = 20260923,
) -> pd.DataFrame:
    """How often each player is selected when costs and forecasts are perturbed.

    Costs get independent log-normal multipliers (auction prices are
    uncertain, ``cost_sigma`` ~ ±25%); utilities get a smaller multiplicative
    error standing in for forecast uncertainty.  Players picked in most draws
    are robust targets; players picked only in the base solution are
    artefacts of point estimates.
    """
    frame = prepare_pool(players, config)
    model = _Model(frame, config)
    rng = np.random.default_rng(seed)
    base_cost = frame["auction_cost"].to_numpy(float)
    base_utility = frame["utility"].to_numpy(float)
    picks = np.zeros(len(frame))
    depth_sum = np.zeros(len(frame))
    paid: list[list[float]] = [[] for _ in range(len(frame))]
    for _ in range(draws):
        costs = np.maximum(1.0, np.round(base_cost * rng.lognormal(0.0, cost_sigma, len(frame))))
        utility = base_utility * rng.lognormal(0.0, utility_sigma, len(frame))
        for player, slot in model.solve(costs=costs, utility=utility):
            picks[player] += 1
            depth_sum[player] += model.slots[slot][1]
            paid[player].append(costs[player])
    selected = picks > 0
    report = frame.loc[selected, ["player", "team", "role", "auction_cost"]].copy()
    report["selection_rate"] = picks[selected] / draws
    report["mean_depth"] = depth_sum[selected] / picks[selected]
    report["median_cost_when_selected"] = [float(np.median(paid[i])) for i in np.flatnonzero(selected)]
    report["tier"] = pd.cut(
        report["selection_rate"], [0, 0.3, 0.7, 1.0001],
        labels=["occasionale", "frequente", "pilastro"], right=False,
    )
    return report.sort_values(["role", "selection_rate"], ascending=[True, False]).reset_index(drop=True)
