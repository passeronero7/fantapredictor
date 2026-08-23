import unittest
import pandas as pd

from src.data_processing.players_processor import PlayersProcessor
from src.data_processing.match_data_builder import MatchDataBuilder


class PlayersProcessorTests(unittest.TestCase):
    def test_merge_all_sources_computes_per90_and_vote_aggregates(self):
        roster_df = pd.DataFrame([
            {"player": "Lautaro Martínez", "club_2026_27": "Inter", "player_normalized": "lautaro martinez", "status": "confirmed"},
            {"player": "Nicolò Barella", "club_2026_27": "Inter", "player_normalized": "nicolo barella", "status": "confirmed"},
        ])

        history_df = pd.DataFrame([
            {"player_normalized": "lautaro martinez", "time": 1800, "xG": 12.5, "xA": 3.0, "npxG": 10.5, "games": 20, "goals": 14, "assists": 3, "year": 2025, "primary_position": "F"},
            {"player_normalized": "nicolo barella", "time": 2700, "xG": 3.5, "xA": 6.5, "npxG": 3.5, "games": 30, "goals": 3, "assists": 7, "year": 2025, "primary_position": "M"},
        ])

        votes_df = pd.DataFrame([
            {"player_normalized": "lautaro martinez", "matchday": 1, "vote": 7.0, "fantavoto": 10.0, "goals": 1, "assists": 0, "yellow_cards": 0, "red_cards": 0},
            {"player_normalized": "lautaro martinez", "matchday": 2, "vote": 6.5, "fantavoto": 6.5, "goals": 0, "assists": 0, "yellow_cards": 0, "red_cards": 0},
        ])

        processor = PlayersProcessor(season="2627")
        merged = processor.merge_all_sources(roster_df=roster_df, history_df=history_df, votes_df=votes_df)

        self.assertEqual(len(merged), 2)
        lautaro = merged[merged["player_normalized"] == "lautaro martinez"].iloc[0]
        self.assertAlmostEqual(lautaro["hist_xg_per90"], 90.0 * 12.5 / (1800.0 + 450.0))
        self.assertEqual(lautaro["season_appearances"], 2)
        self.assertEqual(lautaro["mean_vote"], 6.75)

    def test_match_builder_rejects_missing_observed_targets(self):
        players = pd.DataFrame([{"player": "Player", "role": "D"}])
        with self.assertRaises(ValueError):
            MatchDataBuilder(season="2425").build_complete_dataset(
                votes_df=pd.DataFrame(), players_df=players
            )

    def test_match_builder_uses_only_prior_votes_as_features(self):
        votes = pd.DataFrame([
            {"player": "Player", "player_normalized": "player", "team": "Roma", "role": "D", "matchday": 1, "vote": 7.0, "fantavoto": 7.0},
            {"player": "Player", "player_normalized": "player", "team": "Roma", "role": "D", "matchday": 2, "vote": 5.0, "fantavoto": 5.0},
        ])
        players = pd.DataFrame([
            {"player": "Player", "player_normalized": "player", "role": "D", "hist_minutes": 900},
        ])
        result = MatchDataBuilder(season="2425").build_complete_dataset(
            votes_df=votes, players_df=players
        )["outfield"].sort_values("matchday")
        self.assertTrue(pd.isna(result.iloc[0]["mean_vote"]))
        self.assertEqual(result.iloc[1]["mean_vote"], 7.0)


if __name__ == "__main__":
    unittest.main()
