import unittest

from src.db import __version__
from src.db import database as db


class SchemaTests(unittest.TestCase):
    def test_version_parses(self):
        major, minor, _ = (int(part) for part in __version__.split("."))
        self.assertGreaterEqual(major, 0)
        self.assertGreaterEqual(minor, 0)

    def setUp(self):
        self.conn = db.get_connection(":memory:")
        db.init_schema(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_schema_creates_all_tables(self):
        tables = {
            row[0]
            for row in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        self.assertIn("clubs", tables)
        self.assertIn("players", tables)
        self.assertIn("coaches", tables)
        self.assertIn("seasons", tables)
        self.assertIn("matches", tables)
        self.assertIn("player_season_stats", tables)
        self.assertIn("roster_memberships", tables)
        columns = {
            row["name"] for row in self.conn.execute("PRAGMA table_info(roster_memberships)")
        }
        self.assertIn("role", columns)
        self.assertIn("match_odds", tables)
        self.assertIn("ingestion_runs", tables)

    def test_sources_are_seeded(self):
        slugs = {
            row["slug"]
            for row in self.conn.execute("SELECT slug FROM sources").fetchall()
        }
        self.assertIn("understat", slugs)
        self.assertIn("football-data.co.uk", slugs)
        self.assertIn("virgilio", slugs)

    def test_get_or_create_club_is_idempotent(self):
        first = db.get_or_create_club(self.conn, "Inter")
        second = db.get_or_create_club(self.conn, "Inter")
        self.assertEqual(first, second)
        count = self.conn.execute(
            "SELECT COUNT(*) FROM clubs WHERE name='Inter'"
        ).fetchone()[0]
        self.assertEqual(count, 1)

    def test_get_or_create_season_is_idempotent(self):
        first = db.get_or_create_season(self.conn, "2026/27")
        second = db.get_or_create_season(self.conn, "2026/27")
        self.assertEqual(first, second)
        count = self.conn.execute(
            "SELECT COUNT(*) FROM seasons WHERE name='2026/27'"
        ).fetchone()[0]
        self.assertEqual(count, 1)

    def test_seed_is_idempotent(self):
        # Calling init_schema twice must not duplicate sources
        db.init_schema(self.conn)
        count = self.conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
        self.assertEqual(count, 7)


if __name__ == "__main__":
    unittest.main()
