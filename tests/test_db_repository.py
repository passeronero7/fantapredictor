import tempfile
import unittest
from pathlib import Path

from src.db import database, repository


class DatabaseRepositoryTests(unittest.TestCase):
    def test_loaders_return_normalized_model_inputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            conn = database.get_connection(Path(temporary) / "research.db")
            database.init_schema(conn)
            conn.execute("INSERT INTO seasons (name, start_year) VALUES ('2026/27', 2026)")
            season_id = conn.execute("SELECT id FROM seasons WHERE name = '2026/27'").fetchone()[0]
            understat_id = conn.execute("SELECT id FROM sources WHERE slug = 'understat'").fetchone()[0]
            fantasy_id = conn.execute("SELECT id FROM sources WHERE slug = 'fantacalcio'").fetchone()[0]
            conn.execute("INSERT INTO clubs (name) VALUES ('Test FC')")
            club_id = conn.execute("SELECT id FROM clubs WHERE name = 'Test FC'").fetchone()[0]
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
            votes = repository.load_votes(conn)
            prices = repository.load_prices(conn, "2627")
            skills = repository.load_player_skill_stats(conn, "2627")
            conn.close()

            self.assertEqual(rosters.loc[0, "status"], "confirmed")
            self.assertEqual(history.loc[0, "player_name"], "Test Player")
            self.assertEqual(history.loc[0, "xG"], 2.0)
            self.assertEqual(history.loc[0, "xGChain"], 3.0)
            self.assertEqual(history.loc[0, "xGBuildup"], 1.5)
            self.assertEqual(votes.loc[0, "fantavoto"], 9.0)
            self.assertEqual(prices.loc[0, "price_current"], 20.0)
            self.assertEqual(skills.loc[0, "fbref_passing_progressive_passes"], 12.0)


if __name__ == "__main__":
    unittest.main()
