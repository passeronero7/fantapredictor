import tempfile
import unittest
from pathlib import Path

from src.db import database, repository


class DatabaseRepositoryTests(unittest.TestCase):
    def test_loaders_return_normalized_model_inputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            conn = database.get_connection(Path(temporary) / "research.db")
            database.init_schema(conn)
            conn.execute("INSERT INTO seasons (name, start_year) VALUES ('2025/26', 2025)")
            conn.execute("INSERT INTO seasons (name, start_year) VALUES ('2026/27', 2026)")
            prior_season_id = conn.execute(
                "SELECT id FROM seasons WHERE name = '2025/26'"
            ).fetchone()[0]
            season_id = conn.execute("SELECT id FROM seasons WHERE name = '2026/27'").fetchone()[0]
            understat_id = conn.execute("SELECT id FROM sources WHERE slug = 'understat'").fetchone()[0]
            fantasy_id = conn.execute("SELECT id FROM sources WHERE slug = 'fantacalcio'").fetchone()[0]
            football_data_id = conn.execute(
                "SELECT id FROM sources WHERE slug = 'football-data.co.uk'"
            ).fetchone()[0]
            conn.execute("INSERT INTO clubs (name) VALUES ('Test FC')")
            conn.execute("INSERT INTO clubs (name) VALUES ('Opponent FC')")
            club_id = conn.execute("SELECT id FROM clubs WHERE name = 'Test FC'").fetchone()[0]
            opponent_id = conn.execute(
                "SELECT id FROM clubs WHERE name = 'Opponent FC'"
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO players (full_name, normalized_name, role) VALUES (?, ?, ?)",
                ("Test Player", "test player", "A"),
            )
            player_id = conn.execute(
                "SELECT id FROM players WHERE normalized_name = 'test player'"
            ).fetchone()[0]
            conn.execute(
                """INSERT INTO roster_memberships
                   (player_id, club_id, season_id, status, source_url, checked_at)
                   VALUES (?, ?, ?, 'confirmed', 'https://example.test/roster', '2026-08-24')""",
                (player_id, club_id, season_id),
            )
            conn.execute(
                """INSERT INTO player_season_stats
                   (player_id, club_id, season_id, games, minutes, xg, xa, xg_chain, xg_buildup,
                    source_id, source_ref)
                   VALUES (?, ?, ?, 10, 900, 2.0, 1.0, 3.0, 1.5, ?, 'understat-1')""",
                (player_id, club_id, season_id, understat_id),
            )
            conn.execute(
                """INSERT INTO player_season_stats
                   (player_id, club_id, season_id, games, minutes, xg, xa,
                    source_id, source_ref)
                   VALUES (?, ?, ?, 20, 1800, 4.0, 2.0, ?, 'understat-prior')""",
                (player_id, club_id, prior_season_id, understat_id),
            )
            conn.execute(
                """INSERT INTO player_match_ratings
                   (season_id, matchday, player_id, club_id, vote, fantavoto,
                    source_id, source_ref)
                   VALUES (?, 1, ?, ?, 7.0, 9.0, ?, 'vote-1')""",
                (season_id, player_id, club_id, fantasy_id),
            )
            conn.execute(
                """INSERT INTO player_prices
                   (season_id, player_id, club_id, role_classic, price_current,
                    source_id, source_ref)
                   VALUES (?, ?, ?, 'A', 20, ?, 'price-1')""",
                (season_id, player_id, club_id, fantasy_id),
            )
            conn.executemany(
                """INSERT INTO matches
                   (season_id, matchday, match_date, home_club_id, away_club_id,
                    home_goals, away_goals, home_xg, away_xg, source_id,
                    source_match_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (season_id, 1, "2026-08-22", club_id, opponent_id, 2, 1, 1.5, 0.8, football_data_id, "match-1"),
                    (season_id, 2, "2026-08-29", opponent_id, club_id, 0, 0, 0.7, 1.1, football_data_id, "match-2"),
                ],
            )
            fbref_id = conn.execute("SELECT id FROM sources WHERE slug = 'fbref'").fetchone()[0]
            conn.execute(
                """INSERT INTO player_season_stat_values
                   (player_id, club_id, season_id, category, metric, metric_label, value, source_id, source_file)
                   VALUES (?, ?, ?, 'passing', 'progressive_passes', 'Progressive Passes', 12.0, ?, 'fbref_passing_2627.csv')""",
                (player_id, club_id, season_id, fbref_id),
            )
            conn.commit()

            rosters = repository.load_rosters(conn, "2627")
            history = repository.load_player_history(conn)
            safe_history = repository.load_player_history(conn, before_season="2627")
            votes = repository.load_votes(conn)
            season_votes = repository.load_votes(conn, season="2627")
            prices = repository.load_prices(conn, "2627")
            skills = repository.load_player_skill_stats(conn, "2627")
            context = repository.load_match_context(conn, through_season="2627")
            conn.close()

            self.assertEqual(rosters.loc[0, "status"], "confirmed")
            current_history = history[history["year"].eq(2026)].iloc[0]
            self.assertEqual(current_history["player_name"], "Test Player")
            self.assertEqual(current_history["xG"], 2.0)
            self.assertEqual(current_history["xGChain"], 3.0)
            self.assertEqual(current_history["xGBuildup"], 1.5)
            self.assertEqual(safe_history["year"].tolist(), [2025])
            self.assertEqual(votes.loc[0, "fantavoto"], 9.0)
            self.assertEqual(season_votes["season"].unique().tolist(), ["2026/27"])
            self.assertEqual(prices.loc[0, "price_current"], 20.0)
            self.assertEqual(skills.loc[0, "fbref_passing_progressive_passes"], 12.0)
            test_second = context[
                context["team_normalized"].eq("Test FC")
                & context["matchday"].eq(2)
            ].iloc[0]
            self.assertEqual(test_second["is_home"], 0.0)
            self.assertEqual(test_second["team_xg_for_last5"], 1.5)
            self.assertEqual(test_second["team_xg_against_last5"], 0.8)
            self.assertEqual(test_second["team_points_last5"], 3.0)

    def test_load_team_match_stats_returns_one_row_per_side(self):
        conn = database.get_connection(":memory:")
        database.init_schema(conn)
        try:
            conn.executemany(
                "INSERT INTO sources (slug, name) VALUES (?, ?)",
                [("test", "Test"), ("test2", "Test 2")],
            )
            conn.execute("INSERT INTO seasons (name, start_year) VALUES ('2026/27', 2026)")
            conn.execute("INSERT INTO clubs (name) VALUES ('Home FC')")
            conn.execute("INSERT INTO clubs (name) VALUES ('Away FC')")
            conn.execute(
                """INSERT INTO matches (season_id, matchday, match_date, home_club_id,
                   away_club_id, home_goals, away_goals, source_id, source_match_id)
                   VALUES (1, 1, '2026-08-20', 1, 2, 2, 1, 1, 'm1')"""
            )
            conn.executemany(
                """INSERT INTO match_team_stats (match_id, club_id, side, shots, xg)
                   VALUES (1, ?, ?, ?, ?)""",
                [(1, "home", 15, 1.8), (2, "away", 8, 0.9)],
            )
            conn.commit()
            stats = repository.load_team_match_stats(conn)
            self.assertEqual(len(stats), 2)
            home = stats[stats["team"] == "Home FC"].iloc[0]
            self.assertEqual(home["goals_for"], 2)
            self.assertEqual(home["goals_against"], 1)
            self.assertEqual(home["shots"], 15)
            away = stats[stats["team"] == "Away FC"].iloc[0]
            self.assertEqual(away["goals_for"], 1)
            self.assertEqual(away["shots"], 8)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
