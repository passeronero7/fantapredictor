import csv
import tempfile
import unittest
from pathlib import Path

from src.data_processing.fbref_manual import load_manual_exports, normalize_fbref_export


class FBrefManualExportTests(unittest.TestCase):
    def test_loads_local_exports_without_network_access(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "fbref_scouting_2627.csv").write_text(
                "Player,minutes\nTest Player,900\n", encoding="utf-8"
            )

            exports = load_manual_exports(directory, "2627")

            self.assertEqual(exports["scouting"].loc[0, "player"], "Test Player")
            self.assertEqual(exports["scouting"].loc[0, "source_file"], "fbref_scouting_2627.csv")
            self.assertNotIn("passing", exports)

    def test_rejects_export_without_player_identifier(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "fbref_passing_2627.csv").write_text(
                "minutes\n900\n", encoding="utf-8"
            )

            with self.assertRaises(ValueError):
                load_manual_exports(directory, "2627")

    def test_normalizes_raw_browser_csv_preamble_and_duplicate_headers(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source = directory / "raw.csv"
            destination = directory / "fbref_standard_2627.csv"
            source.write_text(
                "--- Please cite Sports Reference\n\n\n\n"
                ",,,,Performance,Per 90 Minutes\n"
                "Rk,Player,Squad,MP,Gls,Gls\n"
                "1,Test Player,Test Club,2,1,0.50\n",
                encoding="utf-8",
            )

            rows = normalize_fbref_export(source, destination)
            with destination.open(encoding="utf-8", newline="") as handle:
                normalized = list(csv.reader(handle))

            self.assertEqual(rows, 1)
            self.assertEqual(normalized[1][1], "Test Player")
            self.assertIn("Performance Gls", normalized[0])
            self.assertIn("Per 90 Minutes Gls", normalized[0])

    def test_rejects_raw_csv_without_fbref_player_header(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "raw.csv"
            source.write_text("not,a,fbref,export\n", encoding="utf-8")

            with self.assertRaises(ValueError):
                normalize_fbref_export(source, Path(temporary) / "output.csv")


if __name__ == "__main__":
    unittest.main()
