import argparse
import unittest

import pandas as pd

from scripts.evaluate_model import breakdowns, gate_result, parse_cutoffs


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

    def test_gate_fails_when_model_loses_to_either_baseline(self):
        result = gate_result({
            "overall": {"fantavoto_mae": 1.860},
            "baseline": {"fantavoto_mae": 0.801},
            "expanding_prior_baseline": {"fantavoto_mae": 0.908},
        })
        self.assertFalse(result["passed"])
        self.assertFalse(result["beats_baseline"])
        self.assertFalse(result["beats_expanding_prior_baseline"])

    def test_gate_passes_only_when_model_beats_both_baselines(self):
        result = gate_result({
            "overall": {"fantavoto_mae": 0.75},
            "baseline": {"fantavoto_mae": 0.801},
            "expanding_prior_baseline": {"fantavoto_mae": 0.908},
        })
        self.assertTrue(result["passed"])

        mixed = gate_result({
            "overall": {"fantavoto_mae": 0.85},
            "baseline": {"fantavoto_mae": 0.801},
            "expanding_prior_baseline": {"fantavoto_mae": 0.908},
        })
        self.assertFalse(mixed["passed"])
        self.assertFalse(mixed["beats_baseline"])
        self.assertTrue(mixed["beats_expanding_prior_baseline"])


if __name__ == "__main__":
    unittest.main()
