import tempfile
import unittest
from pathlib import Path

import pandas as pd

from scripts.calibrate_auction_prices import (
    fit_price_calibration,
    load_auction_data,
    predict_clearing_price,
)


class PriceCalibrationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)

        # Mock sales
        self.sales_file = self.temp_path / "stato_asta.csv"
        sales_df = pd.DataFrame([
            {"giocatore": "Lautaro", "acquirente": "Marco", "prezzo": 180},
            {"giocatore": "Barella", "acquirente": "Fede", "prezzo": 35},
            {"giocatore": "Bastoni", "acquirente": "io", "prezzo": 22},
            {"giocatore": "Sommer", "acquirente": "io", "prezzo": 18},
            {"giocatore": "Paz", "acquirente": "io", "prezzo": 50},
        ])
        sales_df.to_csv(self.sales_file, index=False)

        # Mock prices
        self.prices_file = self.temp_path / "prices.csv"
        prices_df = pd.DataFrame([
            {"player": "Lautaro Martinez", "role_classic": "A", "fvm": 250, "price_current": 38, "team": "Inter"},
            {"player": "Barella", "role_classic": "C", "fvm": 45, "price_current": 18, "team": "Inter"},
            {"player": "Bastoni", "role_classic": "D", "fvm": 35, "price_current": 14, "team": "Inter"},
            {"player": "Sommer", "role_classic": "P", "fvm": 30, "price_current": 15, "team": "Inter"},
            {"player": "Paz N.", "role_classic": "C", "fvm": 80, "price_current": 25, "team": "Como"},
        ])
        prices_df.to_csv(self.prices_file, index=False)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_load_and_fit_calibration(self):
        df = load_auction_data(self.sales_file, self.prices_file)
        self.assertEqual(len(df), 5)

        calibration = fit_price_calibration(df)
        self.assertEqual(calibration["sample_size"], 5)
        self.assertEqual(calibration["total_spend"], 305.0)
        self.assertIn("A", calibration["roles"])
        self.assertIn("C", calibration["roles"])

    def test_predict_clearing_price(self):
        calibration = {
            "roles": {
                "A": {"fvm_slope": 0.6, "fvm_intercept": -5.0},
                "C": {"fvm_slope": 0.4, "fvm_intercept": 2.0},
            }
        }
        pred_a = predict_clearing_price(100, "A", calibration)
        self.assertEqual(pred_a, 55.0)

        pred_low = predict_clearing_price(2, "A", calibration)
        self.assertGreaterEqual(pred_low, 1.0)


if __name__ == "__main__":
    unittest.main()
