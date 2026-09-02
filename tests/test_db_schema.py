import sqlite3
import tempfile
import unittest
from pathlib import Path

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
        self.assertIn("player_season_stat_values", tables)
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

    def test_understat_club_aliases_resolve_to_canonical_names(self):
        from src.db.ingestors.common import club_id

        milan = club_id(self.conn, "Milan", "fantacalcio")
        self.assertEqual(club_id(self.conn, "AC Milan", "understat", "111"), milan)
        parma = club_id(self.conn, "Parma", "fantacalcio")
        self.assertEqual(club_id(self.conn, "Parma Calcio 1913", "understat", "112"), parma)

    def test_missing_provider_player_ids_do_not_collapse_distinct_players(self):
        from src.db.ingestors.common import player_id

        first = player_id(self.conn, "First Player", "fantacalcio", float("nan"))
        second = player_id(self.conn, "Second Player", "fantacalcio", float("nan"))
        self.assertNotEqual(first, second)

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

    def test_init_schema_stamps_user_version(self):
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        self.assertEqual(version, db.CURRENT_SCHEMA_VERSION)

    def test_init_schema_refuses_a_newer_database(self):
        self.conn.execute(f"PRAGMA user_version = {db.CURRENT_SCHEMA_VERSION + 1}")
        with self.assertRaises(RuntimeError):
            db.init_schema(self.conn)

    def test_get_connection_refuses_a_newer_database(self):
        # Repository readers call get_connection without init_schema, so the
        # fail-fast check must live on the connection path too.
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "newer.db"
            raw = sqlite3.connect(str(path))
            raw.execute(f"PRAGMA user_version = {db.CURRENT_SCHEMA_VERSION + 1}")
            raw.close()
            with self.assertRaises(RuntimeError):
                db.get_connection(path)

    def test_legacy_zero_version_database_migrates_and_gets_stamped(self):
        # Simulate a database created before user_version was ever set, with
        # the additive columns missing (the pre-schema.sql-update shape).
        legacy = db.get_connection(":memory:")
        legacy.executescript(db.SCHEMA_FILE.read_text(encoding="utf-8"))
        legacy.execute("PRAGMA user_version = 0")
        db.init_schema(legacy)
        self.assertEqual(
            legacy.execute("PRAGMA user_version").fetchone()[0], db.CURRENT_SCHEMA_VERSION
        )
        legacy.close()


if __name__ == "__main__":
    unittest.main()
