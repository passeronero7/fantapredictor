import tempfile
import unittest
from pathlib import Path

import pandas as pd

from scripts.recommend_lineup import (
    attach_player_forecasts,
    load_user_roster,
    optimize_lineup_for_matchday,
)


class RecommendLineupTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)

        # Mock roster
        self.roster_file = self.temp_path / "mock_roster.csv"
        df = pd.DataFrame([
            {"giocatore": "Maignan", "ruolo": "P", "squadra": "Milan", "prezzo": 25},
            {"giocatore": "Torriani", "ruolo": "P", "squadra": "Milan", "prezzo": 1},
            {"giocatore": "Theo", "ruolo": "D", "squadra": "Milan", "prezzo": 30},
            {"giocatore": "Bastoni", "ruolo": "D", "squadra": "Inter", "prezzo": 20},
            {"giocatore": "Dimarco", "ruolo": "D", "squadra": "Inter", "prezzo": 25},
            {"giocatore": "Pavlovic", "ruolo": "D", "squadra": "Milan", "prezzo": 15},
            {"giocatore": "Barella", "ruolo": "C", "squadra": "Inter", "prezzo": 25},
            {"giocatore": "Calhanoglu", "ruolo": "C", "squadra": "Inter", "prezzo": 25},
            {"giocatore": "Pulisic", "ruolo": "C", "squadra": "Milan", "prezzo": 30},
            {"giocatore": "Leao", "ruolo": "A", "squadra": "Milan", "prezzo": 60},
            {"giocatore": "Lautaro", "ruolo": "A", "squadra": "Inter", "prezzo": 100},
            {"giocatore": "Thuram", "ruolo": "A", "squadra": "Inter", "prezzo": 80},
        ])
        df.to_csv(self.roster_file, index=False)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_load_user_roster(self):
        roster = load_user_roster(self.roster_file)
        self.assertEqual(len(roster), 12)
        self.assertIn("player_normalized", roster.columns)
        self.assertIn("role", roster.columns)

    def test_optimize_lineup_selection(self):
        roster = load_user_roster(self.roster_file)
        # Mock probabilities
        is_starter = {"maignan": True, "theo": True, "bastoni": True, "dimarco": True,
                      "barella": True, "calhanoglu": True, "pulisic": True,
                      "leao": True, "lautaro": True, "thuram": True}
        injuries = {}
        enriched = attach_player_forecasts(roster, None, is_starter, injuries)

        result = optimize_lineup_for_matchday(enriched, enable_defence_modifier=True)
        self.assertIsNotNone(result)
        self.assertEqual(len(result["starters"]), 11)
        self.assertIn("formation", result)
        self.assertGreater(result["expected_total_score"], 0)


if __name__ == "__main__":
    unittest.main()
