import unittest

import pandas as pd

from src.models.confidence_model import build_confidence_scores


RULES = {
    "event_points": {"goal": 3, "assist": 1, "yellow_card": -0.5, "red_card": -1},
    "model": {"season_half_life_years": 1.5, "prior_minutes": 1800,
              "minimum_history_minutes": 180, "max_history_seasons": 6},
}


class ConfidenceModelTests(unittest.TestCase):
    def test_low_minute_player_is_shrunk_toward_role_prior(self):
        history = pd.DataFrame([
            {"id": 1, "player": "Established", "club_2026_27": "Club", "year": 2025,
             "time": 1800, "xG": 10, "xA": 5, "yellow_cards": 0, "red_cards": 0,
             "primary_position": "F"},
            {"id": 2, "player": "Small sample", "club_2026_27": "Club", "year": 2025,
             "time": 90, "xG": 3, "xA": 1, "yellow_cards": 0, "red_cards": 0,
             "primary_position": "F"},
        ])

        scores = build_confidence_scores(history, RULES, as_of_year=2026).set_index("player")

        self.assertLess(scores.loc["Small sample", "shrinkage_weight"], 0.1)
        self.assertLess(scores.loc["Small sample", "data_confidence"], scores.loc["Established", "data_confidence"])
        self.assertGreater(scores.loc["Small sample", "projected_event_points_per90"], 0)

    def test_goalkeepers_are_marked_unsupported_without_goalkeeper_events(self):
        history = pd.DataFrame([
            {"id": 3, "player": "Goalkeeper", "club_2026_27": "Club", "year": 2025,
             "time": 1800, "xG": 0, "xA": 0, "yellow_cards": 1, "red_cards": 0,
             "primary_position": "GK"},
        ])

        score = build_confidence_scores(history, RULES, as_of_year=2026).iloc[0]

        self.assertEqual(score["model_scope"], "insufficient_goalkeeper_event_coverage")
        self.assertTrue(pd.isna(score["selection_score"]))
