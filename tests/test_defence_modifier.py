import unittest

import pandas as pd
from scipy.stats import norm

from src.models.defence_modifier import calibrate, expected_points, lineup_averages, modifier_points


class DefenceModifierTests(unittest.TestCase):
    def test_thresholds_are_strict(self):
        self.assertEqual(list(modifier_points([6.5, 6.51, 7.0, 7.01])), [0.0, 1.0, 1.0, 3.0])

    def test_expected_points_follow_league_rule(self):
        # Far below 6.5 nothing, far above 7.0 the full +3, never the +6 tier.
        self.assertAlmostEqual(expected_points(5.5, 0.28), 0.0, places=3)
        self.assertAlmostEqual(expected_points(8.0, 0.28), 3.0, places=3)
        # Centred on a threshold: half of that step.
        self.assertAlmostEqual(expected_points(6.5, 0.28),
                               0.5 + 2.0 * norm.sf(7.0, 6.5, 0.28), places=6)
        self.assertEqual(expected_points(6.75, 0.0), 1.0)

    def test_lineup_uses_goalkeeper_and_best_three_defenders(self):
        votes = pd.DataFrame([
            {"season": "s", "team": "T", "matchday": 1, "role": "P", "vote": 7.0},
            {"season": "s", "team": "T", "matchday": 1, "role": "D", "vote": 7.0},
            {"season": "s", "team": "T", "matchday": 1, "role": "D", "vote": 6.5},
            {"season": "s", "team": "T", "matchday": 1, "role": "D", "vote": 6.5},
            {"season": "s", "team": "T", "matchday": 1, "role": "D", "vote": 5.0},
            # Only two voted defenders: no modifier that day.
            {"season": "s", "team": "T", "matchday": 2, "role": "P", "vote": 6.0},
            {"season": "s", "team": "T", "matchday": 2, "role": "D", "vote": 6.0},
            {"season": "s", "team": "T", "matchday": 2, "role": "D", "vote": 6.0},
        ])
        averages = lineup_averages(votes)
        self.assertEqual(len(averages), 1)
        self.assertAlmostEqual(averages.average.iloc[0], 6.75)

    def test_calibration_marginal_is_positive_and_bounded(self):
        averages = pd.DataFrame({
            "season": ["s"] * 6, "team": ["A", "A", "A", "B", "B", "B"],
            "matchday": [1, 2, 3, 1, 2, 3],
            "average": [6.0, 6.3, 6.6, 5.9, 6.2, 6.8],
        })
        result = calibrate(averages)
        self.assertGreater(result.marginal_per_player, 0.0)
        # Even a vertical density cannot exceed the +3 jump shared by 4 votes.
        self.assertLess(result.marginal_per_player, 3.0)


if __name__ == "__main__":
    unittest.main()
