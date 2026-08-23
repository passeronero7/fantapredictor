import unittest

from config.settings import config


class SeasonPathTests(unittest.TestCase):
    def test_2627_uses_canonical_season_directory(self):
        directory = config.get_season_dir("2627")

        self.assertEqual(directory.name, "season_2026_27")
        self.assertEqual(
            config.get_fbref_path("outfield_players.csv", "2627"),
            directory / "manual" / "outfield_players.csv",
        )


if __name__ == "__main__":
    unittest.main()
