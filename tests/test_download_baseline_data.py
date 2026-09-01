import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.download_baseline_data import parse_rosters
from scripts.download_understat_season import build_frame, build_match_frame


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


class UnderstatSeasonTests(unittest.TestCase):
    def test_build_frame_keeps_deep_metrics_and_adds_warehouse_metadata(self):
        frame = build_frame([
            {
                "id": "7", "player_name": "Test Player", "team_title": "Test FC",
                "position": "F", "time": "900", "xG": "4.2", "xA": "1.5",
                "xGChain": "5.4", "xGBuildup": "2.1",
            }
        ], 2026, "2026-08-28T00:00:00+00:00")
        self.assertEqual(frame.loc[0, "league"], "Serie_A")
        self.assertEqual(frame.loc[0, "year"], 2026)
        self.assertEqual(frame.loc[0, "primary_position"], "F")
        self.assertEqual(frame.loc[0, "xGBuildup"], "2.1")

    def test_build_match_frame_keeps_completed_results_and_assigns_matchdays(self):
        def match(identifier, home_id, home, away_id, away, completed=True):
            return {
                "id": str(identifier), "isResult": completed,
                "h": {"id": str(home_id), "title": home},
                "a": {"id": str(away_id), "title": away},
                "goals": {"h": "2" if completed else None, "a": "1" if completed else None},
                "xG": {"h": "1.5" if completed else None, "a": "0.8" if completed else None},
                "datetime": "2026-08-22 18:45:00",
            }

        dates = [
            match(1, 1, "A", 2, "B"), match(2, 3, "C", 4, "D"),
            match(3, 1, "A", 3, "C"), match(4, 2, "B", 4, "D", completed=False),
        ]
        frame = build_match_frame(dates, 2026, "2026-09-01T12:00:00+00:00")

        self.assertEqual(len(frame), 3)
        self.assertEqual(frame["matchday"].tolist(), [1, 1, 2])
        self.assertEqual(frame.loc[0, "home_xg"], "1.5")


if __name__ == "__main__":
    unittest.main()
