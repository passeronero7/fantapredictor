import unittest

import pandas as pd

from src.models.auction_optimizer import (
    AuctionOptimizationConfig,
    ROSTER_SLOTS,
    optimize_auction_roster,
    player_utility,
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


if __name__ == "__main__":
    unittest.main()
