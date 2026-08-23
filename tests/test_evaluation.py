import unittest

import pandas as pd

from src.models.evaluation import score_predictions


class EvaluationTests(unittest.TestCase):
    def test_scores_point_error_and_interval_coverage(self):
        predictions = pd.DataFrame([
            {
                "target_vote": 6.0,
                "target_fantavoto": 7.0,
                "predicted_vote": 6.5,
                "predicted_fantavoto": 6.0,
                "floor_q10": 5.0,
                "median_q50": 6.0,
                "ceiling_q90": 8.0,
            },
            {
                "target_vote": 7.0,
                "target_fantavoto": 10.0,
                "predicted_vote": 7.0,
                "predicted_fantavoto": 8.0,
                "floor_q10": 6.0,
                "median_q50": 8.0,
                "ceiling_q90": 9.0,
            },
        ])

        result = score_predictions(predictions)

        self.assertEqual(result["n"], 2)
        self.assertEqual(result["vote_mae"], 0.25)
        self.assertEqual(result["fantavoto_mae"], 1.5)
        self.assertEqual(result["fantavoto_interval_coverage"], 0.5)

    def test_rejects_unordered_quantiles(self):
        predictions = pd.DataFrame([{
            "target_vote": 6,
            "target_fantavoto": 7,
            "predicted_vote": 6,
            "predicted_fantavoto": 7,
            "floor_q10": 8,
            "median_q50": 7,
            "ceiling_q90": 9,
        }])

        with self.assertRaises(ValueError):
            score_predictions(predictions)


if __name__ == "__main__":
    unittest.main()
