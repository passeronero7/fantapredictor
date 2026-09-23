import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.live_auction import parse_sale, write_state
from src.models.auction_optimizer import (
    AuctionOptimizationConfig,
    ROSTER_SLOTS,
    _Model,
    prepare_pool,
)
from src.models.live_auction import (
    LivePlanner,
    dominance_prune,
    manager_summary,
    market_factor,
    read_state,
    resolve_player,
    resolve_state,
)


def build_pool(seed: int = 3, per_role: int = 18) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    ref = 1000
    for role in ROSTER_SLOTS:
        for index in range(per_role):
            quality = rng.uniform(0, 1)
            rows.append({
                "player": f"{role} Player{index}",
                "player_normalized": f"{role.lower()} player{index}",
                "source_ref": ref,
                "team": f"Club{index % 6}",
                "role": role,
                "auction_cost": float(max(1, round(1 + 60 * quality ** 2 + rng.normal(0, 3)))),
                "expected_fantavoto": 5.8 + 1.4 * quality,
                "p_plays": float(np.clip(0.5 + 0.5 * quality + rng.normal(0, 0.1), 0, 1)),
                "p_horizon_median_good": float(np.clip(0.4 + 0.5 * quality, 0, 1)),
                "expected_vote": 5.9 + 0.6 * quality,
            })
            ref += 1
    return pd.DataFrame(rows)


class ResolveTests(unittest.TestCase):
    def setUp(self):
        self.pool = pd.DataFrame({
            "player": ["Laurientè", "Thuram", "Thuram K.", "Martinez L.", "Martinez Jo."],
            "player_normalized": ["lauriente", "thuram", "thuram k", "martinez l", "martinez jo"],
            "team": ["Sassuolo", "Inter", "Juventus", "Inter", "Inter"],
            "role": ["A", "A", "C", "A", "P"],
            "source_ref": [6060, 4871, 9001, 2764, 5116],
        })

    def test_accents_case_ids_and_prefixes(self):
        self.assertEqual(resolve_player("lauriente", self.pool), 0)
        self.assertEqual(resolve_player("LAURIENTÈ", self.pool), 0)
        self.assertEqual(resolve_player("4871", self.pool), 1)
        self.assertEqual(resolve_player("thuram", self.pool), 1)   # exact beats prefix
        self.assertEqual(resolve_player("thuram k", self.pool), 2)
        self.assertEqual(resolve_player("martinez l", self.pool), 3)

    def test_ambiguous_or_unknown_names_raise_with_hints(self):
        with self.assertRaisesRegex(KeyError, "Martinez"):
            resolve_player("martinez", self.pool)
        with self.assertRaisesRegex(KeyError, "Unknown"):
            resolve_player("nessuno", self.pool)


class StateTests(unittest.TestCase):
    def test_round_trip_and_validation(self):
        folder = Path(tempfile.mkdtemp())
        path = folder / "stato.csv"
        self.assertTrue(read_state(path).empty)
        state = pd.DataFrame([{"giocatore": "A Player1", "acquirente": "io", "prezzo": 12}])
        write_state(state, path)
        pd.testing.assert_frame_equal(read_state(path), state)
        path.write_text("giocatore,acquirente,prezzo\nA Player1,io,0\n")
        with self.assertRaises(ValueError):
            read_state(path)

    def test_double_sale_is_rejected(self):
        pool = build_pool()
        state = pd.DataFrame([
            {"giocatore": "A Player1", "acquirente": "io", "prezzo": 5},
            {"giocatore": "a player1", "acquirente": "Marco", "prezzo": 6},
        ])
        with self.assertRaisesRegex(ValueError, "Sold twice"):
            resolve_state(state, pool)

    def test_parse_sale(self):
        self.assertEqual(parse_sale(["Martinez", "L.", "150"], True, "io"),
                         {"giocatore": "Martinez L.", "acquirente": "io", "prezzo": 150})
        self.assertEqual(parse_sale(["De", "Gea", "20", "Marco"], False, "io")["acquirente"], "Marco")
        with self.assertRaises(ValueError):
            parse_sale(["Kean", "zero"], True, "io")


class ManagerSummaryTests(unittest.TestCase):
    def test_legal_bid_keeps_one_credit_per_other_open_slot(self):
        sales = pd.DataFrame({"acquirente": ["io", "Marco"], "prezzo": [100, 30],
                              "role": ["A", "P"], "row": [0, 1]})
        table = manager_summary(sales, "io", managers=8, budget=500).set_index("acquirente")
        self.assertEqual(table.at["io", "rimasti"], 400)
        self.assertEqual(table.at["io", "offerta_max"], 400 - 23)
        self.assertEqual(table.at["Marco", "aperti_P"], 2)
        self.assertIn("altri (6, nessun acquisto)", table.index)

    def test_too_many_players_in_a_role_is_rejected(self):
        sales = pd.DataFrame({"acquirente": ["io"] * 4, "prezzo": [1] * 4,
                              "role": ["P"] * 4, "row": range(4)})
        with self.assertRaisesRegex(ValueError, "more players than slots"):
            manager_summary(sales, "io", 8, 500)


class PruningTests(unittest.TestCase):
    def test_pruning_keeps_the_optimum(self):
        config = AuctionOptimizationConfig(budget=500, reserve=10, defence_modifier=True)
        for seed in (1, 2, 3):
            frame = prepare_pool(build_pool(seed, per_role=22), config)
            full = _Model(frame, config)
            best = full.result(full.solve())["objective"]
            dropped = dominance_prune(frame, set(), ROSTER_SLOTS)
            self.assertGreater(len(dropped), 0)
            small = frame.drop(index=dropped).reset_index(drop=True)
            model = _Model(small, config)
            self.assertAlmostEqual(model.result(model.solve())["objective"], best, places=7)


class LivePlannerTests(unittest.TestCase):
    def setUp(self):
        self.config = AuctionOptimizationConfig(budget=500, reserve=10)
        self.pool = build_pool(4, per_role=20)
        self.planner = LivePlanner(self.pool, self.config, me="io", managers=8)

    def empty(self):
        return pd.DataFrame(columns=["giocatore", "acquirente", "prezzo"])

    def test_own_buys_are_kept_at_paid_price_and_others_removed(self):
        base = self.planner.plan(self.empty())
        target = base.roster.iloc[0]["player"]
        rival_target = base.roster.iloc[5]["player"]
        state = pd.DataFrame([
            {"giocatore": target, "acquirente": "io", "prezzo": 77},
            {"giocatore": rival_target, "acquirente": "Marco", "prezzo": 5},
        ])
        plan = self.planner.plan(state)
        mine = plan.roster.set_index("player")
        self.assertEqual(mine.at[target, "stato"], "preso")
        self.assertEqual(mine.at[target, "crediti"], 77)
        self.assertNotIn(rival_target, mine.index)
        self.assertEqual(len(plan.roster), sum(ROSTER_SLOTS.values()))
        self.assertLessEqual(plan.roster["crediti"].sum(), 490)
        self.assertEqual(plan.my_budget_left, 423)

    def test_bid_matches_exact_break_even_price(self):
        state = self.empty()
        plan = self.planner.plan(state)
        solved = self.planner._context(state)
        _, context, base_value, assignment, _ = solved
        chosen = {p for p, _ in assignment}
        for name in plan.roster["player"].head(6):
            bid = self.planner.bid(state, name)
            p = context.position[resolve_player(name, self.planner.full)]
            without = context.solve(excluded=[p])[0] if p in chosen else base_value

            def value(price):
                costs = context.costs.copy()
                costs[p] = price
                try:
                    return context.solve(forced=[p], costs=costs)[0]
                except ValueError:
                    return -np.inf

            lo, hi = 0, 490
            while hi - lo > 1:
                mid = (lo + hi) // 2
                lo, hi = (mid, hi) if value(mid) >= without - 1e-9 else (lo, mid)
            self.assertGreaterEqual(bid["offerta_max"], bid["riferimento"] - 1)
            self.assertLessEqual(abs(bid["offerta_max"] - lo), 3, name)

    def test_player_outside_plan_is_worth_at_most_his_reference(self):
        state = self.empty()
        plan = self.planner.plan(state)
        outside = self.pool.loc[~self.pool["player"].isin(plan.roster["player"])]
        name = outside.sort_values("auction_cost").iloc[-1]["player"]
        bid = self.planner.bid(state, name)
        self.assertFalse(bid["nel_piano"])
        self.assertLessEqual(bid["offerta_max"], bid["riferimento"])

    def test_sold_player_cannot_be_quoted(self):
        state = pd.DataFrame([{"giocatore": "A Player1", "acquirente": "Marco", "prezzo": 3}])
        with self.assertRaisesRegex(ValueError, "already sold"):
            self.planner.bid(state, "A Player1")

    def test_market_factor_falls_when_others_overpay(self):
        full = self.planner.full
        # A league budget matching the references, as the dossier builds them.
        needed = sum(full.loc[full.role.eq(r), "auction_cost"].nlargest(8 * n).sum()
                     for r, n in ROSTER_SLOTS.items())
        budget = int(round(needed / 8))
        start = market_factor(full, resolve_state(self.empty(), full), 8, budget)
        self.assertAlmostEqual(start, 1.0, delta=0.01)
        top = full.sort_values("auction_cost", ascending=False).head(3)
        state = pd.DataFrame({"giocatore": top["player"], "acquirente": "Marco",
                              "prezzo": (top["auction_cost"] * 2).astype(int)})
        after = market_factor(full, resolve_state(state, full), 8, budget)
        self.assertLess(after, start)


if __name__ == "__main__":
    unittest.main()
