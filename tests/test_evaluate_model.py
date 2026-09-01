import argparse
import unittest

import pandas as pd

from scripts.evaluate_model import breakdowns, parse_cutoffs


class EvaluateModelTests(unittest.TestCase):
    def test_parse_cutoffs_normalizes_comma_separated_values(self):
        self.assertEqual(parse_cutoffs("30, 10,20"), [30, 10, 20])
        with self.assertRaises(argparse.ArgumentTypeError):
            parse_cutoffs("ten,20")

    def test_breakdowns_include_role_club_and_minutes(self):
        frame = pd.DataFrame([
            {
                "role": "D", "team": "Roma", "hist_minutes": 0,
                "target_vote": 6.0, "target_fantavoto": 6.0,
                "predicted_vote": 6.0, "predicted_fantavoto": 6.0,
                "floor_q10": 5.0, "median_q50": 6.0, "ceiling_q90": 7.0,
            },
            {
                "role": "A", "team": "Inter", "hist_minutes": 3000,
                "target_vote": 7.0, "target_fantavoto": 10.0,
                "predicted_vote": 6.5, "predicted_fantavoto": 9.0,
                "floor_q10": 6.0, "median_q50": 9.0, "ceiling_q90": 11.0,
            },
        ])

        result = breakdowns(frame)

        self.assertEqual(set(result["by_role"]), {"A", "D"})
        self.assertEqual(set(result["by_club"]), {"Inter", "Roma"})
        self.assertEqual(
            set(result["by_historical_minutes"]), {"none", "high_2701_plus"}
        )


if __name__ == "__main__":
    unittest.main()
