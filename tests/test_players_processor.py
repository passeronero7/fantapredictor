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

    def test_merge_exposes_only_confirmed_roster_players(self):
        roster = pd.DataFrame([
            {"player": "Confirmed", "player_normalized": "confirmed", "status": "confirmed"},
            {"player": "Watchlist", "player_normalized": "watchlist", "status": "watchlist"},
            {"player": "Excluded", "player_normalized": "excluded", "status": "excluded"},
        ])

        result = PlayersProcessor(season="2627").merge_all_sources(
            roster_df=roster,
            history_df=pd.DataFrame(),
        )

        self.assertEqual(result["player_normalized"].tolist(), ["confirmed"])

    def test_merge_includes_provider_prefixed_manual_skill_metrics(self):
        roster = pd.DataFrame([
            {"player": "Player", "player_normalized": "player", "status": "confirmed"},
        ])
        skills = pd.DataFrame([
            {"player_normalized": "player", "fbref_passing_progressive_passes": 15.0},
        ])
        result = PlayersProcessor(season="2627").merge_all_sources(
            roster_df=roster, history_df=pd.DataFrame(), skill_stats_df=skills
        )
        self.assertEqual(result.loc[0, "fbref_passing_progressive_passes"], 15.0)

    def test_merge_excludes_current_and_future_season_aggregates(self):
        roster = pd.DataFrame([
            {"player": "Player", "player_normalized": "player", "status": "confirmed"},
        ])
        history = pd.DataFrame([
            {"player_normalized": "player", "year": 2023, "time": 900, "xG": 2.0, "xA": 1.0, "npxG": 2.0, "games": 10, "goals": 2, "assists": 1, "primary_position": "M"},
            {"player_normalized": "player", "year": 2024, "time": 900, "xG": 20.0, "xA": 10.0, "npxG": 20.0, "games": 10, "goals": 20, "assists": 10, "primary_position": "M"},
            {"player_normalized": "player", "year": 2025, "time": 900, "xG": 30.0, "xA": 15.0, "npxG": 30.0, "games": 10, "goals": 30, "assists": 15, "primary_position": "M"},
        ])

        result = PlayersProcessor(season="2425").merge_all_sources(
            roster_df=roster,
            history_df=history,
            skill_stats_df=pd.DataFrame(),
        )

        self.assertEqual(result.loc[0, "hist_xg"], 2.0)
        self.assertEqual(result.loc[0, "latest_year"], 2023)

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

    def test_match_builder_include_history_adds_prior_seasons_and_resets_priors(self):
        votes = pd.DataFrame([
            {"season": "2023/24", "player": "Player", "player_normalized": "player", "team": "Roma", "role": "D", "matchday": 1, "vote": 6.0, "fantavoto": 6.0},
            {"season": "2023/24", "player": "Player", "player_normalized": "player", "team": "Roma", "role": "D", "matchday": 2, "vote": 7.0, "fantavoto": 7.0},
            {"season": "2024/25", "player": "Player", "player_normalized": "player", "team": "Roma", "role": "D", "matchday": 1, "vote": 5.0, "fantavoto": 5.0},
            {"season": "2024/25", "player": "Player", "player_normalized": "player", "team": "Roma", "role": "D", "matchday": 2, "vote": 6.5, "fantavoto": 6.5},
        ])
        players = pd.DataFrame([
            {"player": "Player", "player_normalized": "player", "role": "D", "hist_minutes": 900},
        ])

        current = MatchDataBuilder(season="2425").build_complete_dataset(
            votes_df=votes, players_df=players
        )["outfield"]
        historical = MatchDataBuilder(season="2425").build_complete_dataset(
            include_historical=True, votes_df=votes, players_df=players
        )["outfield"]

        self.assertEqual(len(current), 2)
        self.assertEqual(len(historical), 4)
        first_rows = historical.sort_values(["season", "matchday"]).groupby("season").head(1)
        self.assertTrue(first_rows["mean_vote"].isna().all())


if __name__ == "__main__":
    unittest.main()
