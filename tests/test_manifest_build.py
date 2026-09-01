import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.build_database import build
from src.db import build as build_module


def _write_manifest(path: Path, sources: list[dict]) -> Path:
    manifest_file = path / "data_sources.json"
    manifest_file.write_text(
        json.dumps({"version": 1, "sources": sources}), encoding="utf-8"
    )
    return manifest_file


def _write_votes_file(season_dir: Path, giornata: str, row: str) -> None:
    voti_dir = season_dir / "fantacalcio" / "voti"
    voti_dir.mkdir(parents=True, exist_ok=True)
    (voti_dir / f"Voti_Fantacalcio_Stagione_2026-27_Giornata_{giornata}.csv").write_text(
        "Codice;Ruolo;Giocatore;Squadra;Voto;Fantavoto;Gol;Assist;Amm;Esp\n" + row,
        encoding="utf-8",
    )


VOTES_SOURCE = {
    "slug": "votes", "kind": "votes", "root": "season_dir",
    "pattern": "fantacalcio/voti", "seasons": ["*"],
}


class ManifestResolutionTests(unittest.TestCase):
    def test_resolves_target_season_data_dir_and_wildcard_directives(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "season_2026_27" / "rosters").mkdir(parents=True)
            roster = root / "season_2026_27" / "rosters" / "virgilio_rosters_2627.csv"
            roster.write_text("player,club_2026_27,role,status,source_url,checked_at\n", encoding="utf-8")

            (root / "season_2015_16" / "fantacalcio" / "voti").mkdir(parents=True)
            (root / "season_2015_16" / "fantacalcio" / "voti" / "Voti_Fantacalcio_Stagione_2015-16_Giornata_01.csv").write_text(
                "x\n", encoding="utf-8"
            )
            (root / "season_2026_27" / "fantacalcio" / "voti").mkdir(parents=True)
            (root / "season_2026_27" / "fantacalcio" / "voti" / "Voti_Fantacalcio_Stagione_2026-27_Giornata_01.csv").write_text(
                "x\n", encoding="utf-8"
            )

            manifest_file = _write_manifest(root, [
                {
                    "slug": "roster", "kind": "roster", "root": "season_dir",
                    "pattern": "rosters/virgilio_rosters_{season_compact}.csv",
                    "seasons": ["$target"],
                },
                VOTES_SOURCE,
                {
                    "slug": "football-data", "kind": "match-results-tree", "root": "data_dir",
                    "pattern": "raw/football-data.co.uk", "seasons": [None],
                },
            ])

            sources = build_module.resolve_sources("2627", manifest_file, root)
            by_slug = {source.slug: source for source in sources if source.slug == "roster"}
            self.assertEqual(by_slug["roster"].path, roster)

            votes_seasons = sorted(s.season for s in sources if s.slug == "votes")
            self.assertEqual(votes_seasons, ["1516", "2627"])

            # football-data's directory does not exist, so it must not resolve.
            self.assertFalse(any(s.slug == "football-data" for s in sources))


class ManifestBuildTests(unittest.TestCase):
    def test_manifest_checksum_skip_avoids_reingesting_unchanged_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            season_dir = root / "season_2026_27"
            _write_votes_file(season_dir, "01", "201;D;Test Defender;Test FC;7;10;1;0;0;0\n")
            manifest_file = _write_manifest(root, [VOTES_SOURCE])

            db_path = root / "fantapredictor.db"
            first = build(db_path, season="2627", manifest_file=manifest_file, data_dir=root)
            second = build(db_path, season="2627", manifest_file=manifest_file, data_dir=root)

            self.assertEqual(first.get("votes_2026_27"), 1)
            self.assertNotIn("votes_2026_27", second)  # unchanged checksum: skipped, not reloaded

            connection = sqlite3.connect(db_path)
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM ingestion_runs").fetchone()[0], 1
            )
            self.assertEqual(
                connection.execute("SELECT status FROM source_checksums").fetchall(),
                [("ok",)],
            )
            connection.close()

    def test_manifest_reingests_after_the_source_file_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            season_dir = root / "season_2026_27"
            _write_votes_file(season_dir, "01", "201;D;Test Defender;Test FC;7;10;1;0;0;0\n")
            manifest_file = _write_manifest(root, [VOTES_SOURCE])

            db_path = root / "fantapredictor.db"
            build(db_path, season="2627", manifest_file=manifest_file, data_dir=root)
            _write_votes_file(season_dir, "02", "202;C;Second Player;Test FC;6;6;0;0;0;0\n")
            second = build(db_path, season="2627", manifest_file=manifest_file, data_dir=root)

            # The directory checksum changed (a new file was added), so the whole
            # directory reloads: both matchday files are re-read, 2 rows total.
            self.assertEqual(second.get("votes_2026_27"), 2)
            connection = sqlite3.connect(db_path)
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM player_match_ratings").fetchone()[0], 2
            )
            connection.close()

    def test_a_failing_source_is_isolated_and_reported_without_aborting_the_build(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            season_dir = root / "season_2026_27"
            voti_dir = season_dir / "fantacalcio" / "voti"
            voti_dir.mkdir(parents=True)
            # Malformed: header present but a row has a matchday-less filename won't
            # trigger this; instead force a real ingestor error via a broken roster CSV
            # (missing required columns triggers rosters.load's own validation error).
            roster_dir = season_dir / "rosters"
            roster_dir.mkdir(parents=True)
            (roster_dir / "virgilio_rosters_2627.csv").write_text(
                "not,the,expected,columns\n1,2,3,4\n", encoding="utf-8"
            )
            (voti_dir / "Voti_Fantacalcio_Stagione_2026-27_Giornata_01.csv").write_text(
                "Codice;Ruolo;Giocatore;Squadra;Voto;Fantavoto;Gol;Assist;Amm;Esp\n"
                "201;D;Test Defender;Test FC;7;10;1;0;0;0\n",
                encoding="utf-8",
            )
            manifest_file = _write_manifest(root, [
                {
                    "slug": "roster", "kind": "roster", "root": "season_dir",
                    "pattern": "rosters/virgilio_rosters_{season_compact}.csv",
                    "seasons": ["$target"],
                },
                VOTES_SOURCE,
            ])

            db_path = root / "fantapredictor.db"
            result = build(db_path, season="2627", manifest_file=manifest_file, data_dir=root)

            # The roster source fails, but votes -- resolved and loaded after it --
            # still succeeds instead of the whole build aborting.
            self.assertEqual(result.get("votes_2026_27"), 1)
            self.assertIn("_errors", result)
            self.assertIn("roster:2627", result["_errors"])

    def test_rebuild_requires_confirm_wipe(self):
        with tempfile.TemporaryDirectory() as temporary:
            db_path = Path(temporary) / "fantapredictor.db"
            with self.assertRaises(ValueError):
                build(db_path, season="2627", rebuild=True)

    def test_rebuild_drops_prior_data_before_reloading(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            season_dir = root / "season_2026_27"
            _write_votes_file(season_dir, "01", "201;D;Test Defender;Test FC;7;10;1;0;0;0\n")
            manifest_file = _write_manifest(root, [VOTES_SOURCE])

            db_path = root / "fantapredictor.db"
            build(db_path, season="2627", manifest_file=manifest_file, data_dir=root)
            result = build(
                db_path, season="2627", manifest_file=manifest_file, data_dir=root,
                rebuild=True, confirm_wipe=True,
            )

            self.assertEqual(result.get("votes_2026_27"), 1)
            connection = sqlite3.connect(db_path)
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM player_match_ratings").fetchone()[0], 1
            )
            connection.close()


if __name__ == "__main__":
    unittest.main()
