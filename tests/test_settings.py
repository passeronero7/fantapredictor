import os
import unittest
from pathlib import Path
from unittest.mock import patch

from config.settings import _resolve_data_dir, config


class SeasonPathTests(unittest.TestCase):
    def test_2627_uses_canonical_season_directory(self):
        directory = config.get_season_dir("2627")

        self.assertEqual(directory.name, "season_2026_27")
        self.assertEqual(
            config.get_fbref_path("outfield_players.csv", "2627"),
            directory / "manual" / "outfield_players.csv",
        )

    def test_resolve_data_dir_explicit_env(self):
        with patch.dict(os.environ, {"FANTAPREDICTOR_DATA_DIR": "/tmp/custom_data"}):
            resolved = _resolve_data_dir()
            self.assertEqual(resolved, Path("/tmp/custom_data"))

    def test_resolve_data_dir_workspace_fallback(self):
        with patch.dict(os.environ, {}, clear=True):
            resolved = _resolve_data_dir()
            self.assertTrue(resolved.exists())
            self.assertTrue((resolved / "fantapredictor.db").exists() or (resolved / "season_2026_27").exists())


if __name__ == "__main__":
    unittest.main()
