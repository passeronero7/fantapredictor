import sqlite3
import unittest
import pandas as pd
import numpy as np

from src.models.tactical_matchups import (
    compute_style_delta,
    compute_coach_h2h_delta,
    evaluate_matchday_tactics,
    STYLE_INTERACTIONS,
)


class TacticalMatchupTests(unittest.TestCase):
    def test_style_delta_possession_vs_man_marking_boosts_midfield(self):
        delta = compute_style_delta(["possession"], ["man_marking"])
        self.assertGreater(delta["C"], 0.0)
        self.assertGreater(delta["A"], 0.0)
        self.assertLess(delta["D"], 0.0)

    def test_style_delta_is_bounded_and_zero_for_unknown_styles(self):
        delta_unknown = compute_style_delta(["unknown_style"], ["other_unknown"])
        for r in ("P", "D", "C", "A"):
            self.assertEqual(delta_unknown[r], 0.0)

        # Compounding tags remain strictly within [-0.05, +0.05]
        delta_multi = compute_style_delta(["possession", "high_block", "vertical"], ["man_marking", "pressing"])
        for r in ("P", "D", "C", "A"):
            self.assertGreaterEqual(delta_multi[r], -0.05)
            self.assertLessEqual(delta_multi[r], 0.05)

    def test_h2h_delta_returns_zero_on_insufficient_matches(self):
        delta, count, summary = compute_coach_h2h_delta(None, "Coach A", "Coach B")
        self.assertEqual(delta, 0.0)
        self.assertEqual(count, 0)

        empty_df = pd.DataFrame(columns=["home_coach", "away_coach", "home_goals", "away_goals"])
        delta, count, summary = compute_coach_h2h_delta(empty_df, "Coach A", "Coach B")
        self.assertEqual(delta, 0.0)
        self.assertEqual(count, 0)

    def test_h2h_empirical_bayes_shrinkage_regularizes_outliers(self):
        # 2 matches where Coach A scored 4 goals each time (extreme outlier)
        mock_matches = pd.DataFrame([
            {"home_coach": "Coach A", "away_coach": "Coach B", "home_goals": 4.0, "away_goals": 0.0},
            {"home_coach": "Coach B", "away_coach": "Coach A", "home_goals": 1.0, "away_goals": 4.0},
        ])
        delta, count, summary = compute_coach_h2h_delta(mock_matches, "Coach A", "Coach B", shrinkage=4.0)
        self.assertEqual(count, 2)
        # Even with raw mean 4.0 vs baseline 1.3 (+207%), shrunk delta must be safely bounded <= 0.06
        self.assertLessEqual(delta, 0.06)
        self.assertGreater(delta, 0.0)
        self.assertIn("2V-0P-0S", summary)

    def test_evaluate_matchday_tactics_integration(self):
        # Create an in-memory SQLite database simulating clubs, coaches, seasons, matches
        conn = sqlite3.connect(":memory:")
        conn.executescript("""
            CREATE TABLE seasons (id INTEGER PRIMARY KEY, name TEXT);
            CREATE TABLE clubs (id INTEGER PRIMARY KEY, name TEXT);
            CREATE TABLE coaches (id INTEGER PRIMARY KEY, full_name TEXT, preferred_module TEXT, style_tags TEXT);
            CREATE TABLE coach_club_seasons (id INTEGER PRIMARY KEY, season_id INTEGER, club_id INTEGER, coach_id INTEGER, started_at TEXT, ended_at TEXT);
            CREATE TABLE matches (id INTEGER PRIMARY KEY, season_id INTEGER, matchday INTEGER, match_date TEXT, home_club_id INTEGER, away_club_id INTEGER, home_goals REAL, away_goals REAL);

            INSERT INTO seasons VALUES (1, '2026/27');
            INSERT INTO clubs VALUES (1, 'Alpha'), (2, 'Beta');
            INSERT INTO coaches VALUES (1, 'Coach Alpha', '4-2-3-1', 'possession|high_block');
            INSERT INTO coaches VALUES (2, 'Coach Beta', '3-4-2-1', 'man_marking|pressing');
            INSERT INTO coach_club_seasons VALUES (1, 1, 1, 1, '2026-07-01', NULL);
            INSERT INTO coach_club_seasons VALUES (2, 1, 2, 2, '2026-07-01', NULL);
            INSERT INTO matches VALUES (1, 1, 6, '2026-10-11', 1, 2, NULL, NULL);
        """)

        evals = evaluate_matchday_tactics(conn, "2026/27", 6)
        self.assertIn("Alpha", evals)
        self.assertIn("Beta", evals)

        alpha_ev = evals["Alpha"]
        self.assertEqual(alpha_ev.coach, "Coach Alpha")
        self.assertEqual(alpha_ev.opponent_coach, "Coach Beta")
        # Possession vs man-marking boosts midfielder C
        self.assertGreater(alpha_ev.role_multipliers["C"], 1.0)
        self.assertGreaterEqual(alpha_ev.role_multipliers["C"], 0.92)
        self.assertLessEqual(alpha_ev.role_multipliers["C"], 1.08)


if __name__ == "__main__":
    unittest.main()
