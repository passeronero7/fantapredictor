import tempfile
import unittest
from pathlib import Path

from src.data_processing.fbref_manual import load_manual_exports


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


if __name__ == "__main__":
    unittest.main()
