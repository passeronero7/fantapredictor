import unittest

import pandas as pd

from src.models.auction_optimizer import (
    AuctionOptimizationConfig,
    ROSTER_SLOTS,
    alternative_rosters,
    modifier_premium,
    optimize_auction_roster,
    player_utility,
    selection_robustness,
)


class AuctionOptimizerTests(unittest.TestCase):
    def build_players(self):
        rows = []
        for role, count in ROSTER_SLOTS.items():
            for index in range(count + 2):
                rows.append({
                    "player": f"{role}{index}",
                    "team": f"Club{index % 4}",
                    "role": role,
                    "auction_cost": 5 + index,
                    "expected_fantavoto": 6.0 + index / 10,
                    "p_plays": 0.9,
                    "p_horizon_median_good": 0.7 + index / 100,
                })
        return pd.DataFrame(rows)

    def test_returns_exact_legal_roster_under_budget(self):
        result = optimize_auction_roster(
            self.build_players(), AuctionOptimizationConfig(budget=500)
        )
        roster = result["roster"]
        self.assertEqual(len(roster), 25)
        self.assertEqual(roster.groupby("role").size().to_dict(), ROSTER_SLOTS)
        self.assertEqual(roster.player.nunique(), 25)
        self.assertLessEqual(result["total_cost"], 500)

    def test_rejects_incomplete_role_pool(self):
        frame = self.build_players().query("role != 'P'")
        with self.assertRaisesRegex(ValueError, "Insufficient eligible P"):
            optimize_auction_roster(frame)

    def test_returns_legal_roster_when_ineligible_rows_precede_eligible_ones(self):
        # Regression: rows without a usable auction_cost used to be dropped
        # *after* the frame was reindexed to range(len(players)), leaving
        # frame.index sparse while every row-position lookup downstream
        # assumed a dense range. Placing the dropped rows first reproduces
        # the resulting out-of-bounds / misaligned-constraint failure.
        bad = pd.DataFrame([
            {**self.build_players().iloc[0].to_dict(), "player": "bad1", "auction_cost": None},
            {**self.build_players().iloc[1].to_dict(), "player": "bad2", "auction_cost": None},
            {**self.build_players().iloc[2].to_dict(), "player": "bad3", "auction_cost": None},
        ])
        frame = pd.concat([bad, self.build_players()], ignore_index=True)
        result = optimize_auction_roster(frame, AuctionOptimizationConfig(budget=500))
        roster = result["roster"]
        self.assertEqual(len(roster), 25)
        self.assertEqual(roster.player.nunique(), 25)
        self.assertNotIn("bad1", set(roster.player))

    def test_reserve_is_kept_unspent(self):
        result = optimize_auction_roster(
            self.build_players(), AuctionOptimizationConfig(budget=500, reserve=50)
        )
        self.assertLessEqual(result["total_cost"], 450)
        self.assertEqual(result["reserve"], 50)

    def test_availability_factor_discounts_utility(self):
        frame = self.build_players().iloc[:2].copy()
        frame["availability_factor"] = [1.0, 0.35]
        utility = player_utility(frame)
        undiscounted_second = player_utility(frame.drop(columns="availability_factor")).iloc[1]
        self.assertAlmostEqual(utility.iloc[1], undiscounted_second * 0.35)

    def test_alternatives_differ_by_at_least_min_changes(self):
        results = alternative_rosters(
            self.build_players(), AuctionOptimizationConfig(budget=500), count=3, min_changes=2
        )
        self.assertEqual(len(results), 3)
        rosters = [set(r["roster"].player) for r in results]
        for i in range(len(rosters)):
            for j in range(i):
                self.assertGreaterEqual(len(rosters[i] - rosters[j]), 2)
        objectives = [r["objective"] for r in results]
        self.assertEqual(objectives, sorted(objectives, reverse=True))

    def test_modifier_premium_prefers_high_vote_defender_when_only_one_fits(self):
        frame = self.build_players()
        frame["expected_vote"] = 6.0
        # Two otherwise identical star defenders, each costing 200: the
        # budget fits one. Only the modifier premium can split them.
        stars = frame.player.isin(["D8", "D9"])
        frame.loc[stars, ["expected_fantavoto", "p_horizon_median_good", "auction_cost"]] = [7.5, 0.79, 200]
        frame.loc[frame.player.eq("D8"), "expected_vote"] = 6.8
        with_mod = optimize_auction_roster(frame, AuctionOptimizationConfig(defence_modifier=True))
        chosen = set(with_mod["roster"].player) & {"D8", "D9"}
        self.assertEqual(chosen, {"D8"})

    def test_modifier_premium_is_zero_without_modifier(self):
        frame = self.build_players()
        frame["expected_vote"] = 7.5
        result = optimize_auction_roster(frame, AuctionOptimizationConfig(defence_modifier=False))
        self.assertTrue((result["roster"].modifier_premium == 0).all())

    def test_robustness_reports_selection_rates(self):
        report = selection_robustness(
            self.build_players(), AuctionOptimizationConfig(budget=500), draws=5
        )
        self.assertTrue(report.selection_rate.between(0, 1).all())
        # Every draw picks exactly 25 players.
        self.assertAlmostEqual(report.selection_rate.sum(), 25.0)

    def test_modifier_premium_is_centred_on_role_replacement_vote(self):
        frame = pd.DataFrame({
            "role": ["D", "D", "D", "D", "C"],
            "p_plays": [0.9, 0.9, 0.9, 0.4, 0.9],
            "expected_vote": [6.0, 6.0, 6.4, 5.8, 7.0],
        })
        premium = modifier_premium(frame, AuctionOptimizationConfig(defence_modifier=True))
        # Regular defenders' median vote (6.0) is the zero point.
        self.assertAlmostEqual(premium.iloc[0], 0.0)
        self.assertGreater(premium.iloc[2], 0.0)
        # A below-replacement defender is penalised, and playing less must
        # not turn that into an advantage over a replacement-level regular.
        self.assertLess(premium.iloc[3], 0.0)
        self.assertEqual(premium.iloc[4], 0.0)


if __name__ == "__main__":
    unittest.main()
