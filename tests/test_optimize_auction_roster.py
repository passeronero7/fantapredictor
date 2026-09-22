import tempfile
import unittest
from pathlib import Path

import pandas as pd

from scripts.optimize_auction_roster import build_pool


class BuildPoolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.forecast_path = Path(self.tmp.name) / "forecast.csv"
        self.dossier_path = Path(self.tmp.name) / "dossier.csv"

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, forecast_rows, dossier_rows):
        pd.DataFrame(forecast_rows).to_csv(self.forecast_path, index=False)
        pd.DataFrame(dossier_rows).to_csv(self.dossier_path, index=False)

    def test_joins_on_identity_key_not_redundant_name_normalization(self):
        # Display spelling differs (accent, suffix) but the warehouse identity
        # key is the same for both sides: the join must still succeed.
        self.write(
            forecast_rows=[{
                "player": "K. Thuram", "player_normalized": "thuram k", "team": "Juventus",
                "role": "C", "expected_fantavoto": 6.5, "p_plays": 0.8,
                "p_horizon_median_good": 0.6,
            }],
            dossier_rows=[{
                "player": "Thuram K.", "player_normalized": "thuram k", "club": "Juventus",
                "riferimento_con_modificatore": 12, "rischio_disponibilita": False,
                "note": "",
            }],
        )
        pool, report = build_pool(self.forecast_path, self.dossier_path, defence_modifier=True)
        self.assertEqual(len(pool), 1)
        self.assertEqual(report["matched"], 1)
        self.assertEqual(report["unmatched_forecast"], [])
        self.assertEqual(report["unmatched_dossier"], [])

    def test_unmatched_rows_are_reported_not_silently_dropped(self):
        self.write(
            forecast_rows=[
                {"player": "A", "player_normalized": "a", "team": "X", "role": "C",
                 "expected_fantavoto": 6.5, "p_plays": 0.8, "p_horizon_median_good": 0.6},
                {"player": "Ghost", "player_normalized": "ghost", "team": "X", "role": "C",
                 "expected_fantavoto": 6.5, "p_plays": 0.8, "p_horizon_median_good": 0.6},
            ],
            dossier_rows=[
                {"player": "A", "player_normalized": "a", "club": "X",
                 "riferimento_con_modificatore": 10, "rischio_disponibilita": False, "note": ""},
                {"player": "Phantom", "player_normalized": "phantom", "club": "X",
                 "riferimento_con_modificatore": 5, "rischio_disponibilita": False, "note": ""},
            ],
        )
        pool, report = build_pool(self.forecast_path, self.dossier_path, defence_modifier=True)
        self.assertEqual(len(pool), 1)
        self.assertEqual(report["unmatched_forecast"], ["ghost"])
        self.assertEqual(report["unmatched_dossier"], ["phantom"])

    def test_duplicate_identity_raises_instead_of_silently_merging(self):
        self.write(
            forecast_rows=[
                {"player": "A", "player_normalized": "dup", "team": "X", "role": "C",
                 "expected_fantavoto": 6.5, "p_plays": 0.8, "p_horizon_median_good": 0.6},
                {"player": "B", "player_normalized": "dup", "team": "X", "role": "C",
                 "expected_fantavoto": 6.0, "p_plays": 0.7, "p_horizon_median_good": 0.5},
            ],
            dossier_rows=[
                {"player": "A", "player_normalized": "dup", "club": "X",
                 "riferimento_con_modificatore": 10, "rischio_disponibilita": False, "note": ""},
            ],
        )
        with self.assertRaisesRegex(ValueError, "duplicate identities"):
            build_pool(self.forecast_path, self.dossier_path, defence_modifier=True)

    def test_structured_availability_is_not_double_discounted(self):
        # A player already discounted through the dated availability channel
        # (availability_structured=True) must not also take the note-based
        # heuristic haircut, even though the dossier still flags him at risk.
        self.write(
            forecast_rows=[{
                "player": "Injured", "player_normalized": "injured", "team": "X", "role": "C",
                "expected_fantavoto": 6.5, "p_plays": 0.4, "p_horizon_median_good": 0.6,
                "availability_structured": True,
            }],
            dossier_rows=[{
                "player": "Injured", "player_normalized": "injured", "club": "X",
                "riferimento_con_modificatore": 10, "rischio_disponibilita": True,
                "note": "operato, rientro previsto a novembre",
            }],
        )
        pool, _ = build_pool(self.forecast_path, self.dossier_path, defence_modifier=True)
        self.assertEqual(pool["availability_factor"].iloc[0], 1.0)

    def test_unstructured_risk_still_gets_the_heuristic_discount(self):
        self.write(
            forecast_rows=[{
                "player": "Injured", "player_normalized": "injured", "team": "X", "role": "C",
                "expected_fantavoto": 6.5, "p_plays": 0.8, "p_horizon_median_good": 0.6,
            }],
            dossier_rows=[{
                "player": "Injured", "player_normalized": "injured", "club": "X",
                "riferimento_con_modificatore": 10, "rischio_disponibilita": True,
                "note": "operato, rientro previsto a novembre",
            }],
        )
        pool, _ = build_pool(self.forecast_path, self.dossier_path, defence_modifier=True)
        self.assertEqual(pool["availability_factor"].iloc[0], 0.35)


if __name__ == "__main__":
    unittest.main()
