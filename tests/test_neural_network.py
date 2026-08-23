import tempfile
import unittest
from pathlib import Path
import pandas as pd

from src.models.neural_network import FantacalcioPredictor


class NeuralNetworkPredictorTests(unittest.TestCase):
    def test_predictor_trains_and_outputs_quantiles(self):
        outfield_df = pd.DataFrame([
            {"hist_minutes": 1800, "hist_xg": 10.0, "hist_xa": 4.0, "hist_xg_per90": 0.5, "hist_xa_per90": 0.2, "target_vote": 6.8, "target_fantavoto": 8.5},
            {"hist_minutes": 1500, "hist_xg": 2.0, "hist_xa": 5.0, "hist_xg_per90": 0.1, "hist_xa_per90": 0.3, "target_vote": 6.2, "target_fantavoto": 6.8},
            {"hist_minutes": 2000, "hist_xg": 0.5, "hist_xa": 1.0, "hist_xg_per90": 0.02, "hist_xa_per90": 0.04, "target_vote": 6.0, "target_fantavoto": 5.9},
            {"hist_minutes": 900, "hist_xg": 4.0, "hist_xa": 1.0, "hist_xg_per90": 0.4, "hist_xa_per90": 0.1, "target_vote": 6.4, "target_fantavoto": 7.2},
        ])
        gk_df = pd.DataFrame([
            {"hist_minutes": 2700, "hist_xg": 0.0, "hist_xa": 0.0, "hist_xg_per90": 0.0, "hist_xa_per90": 0.0, "target_vote": 6.3, "target_fantavoto": 5.3},
            {"hist_minutes": 1800, "hist_xg": 0.0, "hist_xa": 0.0, "hist_xg_per90": 0.0, "hist_xa_per90": 0.0, "target_vote": 5.9, "target_fantavoto": 4.4},
        ])
        outfield_df = pd.concat([outfield_df, outfield_df], ignore_index=True)
        gk_df = pd.concat([gk_df, gk_df, gk_df, gk_df], ignore_index=True)

        predictor = FantacalcioPredictor(season="2627")
        train_res = predictor.train(outfield_df, gk_df, epochs=20)
        self.assertEqual(train_res["status"], "trained")

        test_players = pd.DataFrame([
            {"player": "Striker A", "role": "A", "hist_minutes": 1800, "hist_xg": 12.0, "hist_xa": 2.0, "hist_xg_per90": 0.6, "hist_xa_per90": 0.1},
            {"player": "Defender B", "role": "D", "hist_minutes": 2000, "hist_xg": 0.5, "hist_xa": 1.0, "hist_xg_per90": 0.02, "hist_xa_per90": 0.04},
        ])

        preds = predictor.predict_matchday(matchday=1, players_data=test_players)
        self.assertEqual(len(preds), 2)
        self.assertIn("ceiling_q90", preds.columns)
        self.assertIn("floor_q10", preds.columns)
        self.assertIn("dist_skewness", preds.columns)

        # Attacker ceiling should be substantially higher than floor
        striker = preds[preds["role"] == "A"].iloc[0]
        self.assertGreater(striker["ceiling_q90"], striker["floor_q10"])

    def test_save_and_load_restores_predictions(self):
        rows = [
            {
                "hist_minutes": 900 + i * 100,
                "hist_xg": i / 10,
                "hist_xa": (8 - i) / 10,
                "hist_xg_per90": i / 100,
                "hist_xa_per90": (8 - i) / 100,
                "target_vote": 6.0 + i / 10,
                "target_fantavoto": 6.5 + i / 10,
            }
            for i in range(8)
        ]
        training = pd.DataFrame(rows)
        players = pd.DataFrame([
            {"player": "Player A", "role": "A", **rows[2]},
            {"player": "Player B", "role": "D", **rows[4]},
        ])

        with tempfile.TemporaryDirectory() as temporary:
            model_dir = Path(temporary)
            predictor = FantacalcioPredictor(season="unit-persistence")
            predictor.models_dir = model_dir
            predictor.train(training, training, epochs=1)
            predictor.save_model("unit")
            expected = predictor.predict_matchday(1, players)

            restored = FantacalcioPredictor(season="unit-persistence")
            restored.models_dir = model_dir
            restored.load_latest_model()
            actual = restored.predict_matchday(1, players)

            self.assertEqual(restored.version, "unit")
            self.assertTrue(
                (expected["median_q50"].to_numpy() == actual["median_q50"].to_numpy()).all()
            )


if __name__ == "__main__":
    unittest.main()
