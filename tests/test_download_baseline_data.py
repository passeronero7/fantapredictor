import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.download_baseline_data import parse_rosters


class RosterParsingTests(unittest.TestCase):
    def test_parse_rosters_extracts_current_club_player_records(self):
        clubs = [
            "Atalanta", "Bologna", "Cagliari", "Como", "Fiorentina", "Frosinone",
            "Genoa", "Inter", "Juventus", "Lazio", "Lecce", "Milan", "Monza",
            "Napoli", "Parma", "Roma", "Sassuolo", "Torino", "Udinese", "Venezia",
        ]
        html = "".join(f"<h3>{club}</h3><ul><li>{club} Player</li></ul>" for club in clubs)

        roster = parse_rosters(html, "2026-08-23T00:00:00+00:00")

        self.assertEqual(len(roster), 20)
        self.assertEqual(roster["club_2026_27"].nunique(), 20)
        self.assertIn("role", roster.columns)
        self.assertEqual(roster.loc[0, "status"], "watchlist")


if __name__ == "__main__":
    unittest.main()
