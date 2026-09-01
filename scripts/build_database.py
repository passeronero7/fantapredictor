#!/usr/bin/env python3
"""Build the local FantaPredictor SQLite warehouse from downloaded files."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config.settings import config
from src.db import build as build_module
from src.db import database
from src.db.ingestors import coaches, fbref, football_data, prices, rosters, understat, votes
from src.db.ingestors.common import season_label


def build(
    db_path: str | Path,
    roster_path: str | Path | None = None,
    understat_path: str | Path | None = None,
    votes_dir: str | Path | None = None,
    matches_dir: str | Path | None = None,
    coaches_path: str | Path | None = None,
    prices_path: str | Path | None = None,
    season: str = "2627",
    manual_fbref_dir: str | Path | None = None,
    rebuild: bool = False,
    confirm_wipe: bool = False,
    force: bool = False,
    manifest_file: str | Path | None = None,
    data_dir: str | Path | None = None,
) -> dict[str, object]:
    """Initialize and populate the warehouse from local source snapshots.

    A source with an explicit path argument is loaded directly from that
    path. Every other source resolves from the declared
    ``config/data_sources.json`` manifest (see
    ``docs/ingestion_and_fixing_strategy.md``, Strategy B1) instead of
    globbing the data directory. ``--rebuild`` drops the database first and
    always loads the full manifest, ignoring explicit single-source paths
    (except ``coaches``, which the manifest never declares).

    A failing manifest source is isolated: it is recorded and skipped, and
    the rest of the build continues (see the ``"_errors"`` key).
    """
    if rebuild:
        if not confirm_wipe:
            raise ValueError(
                "rebuild=True drops and recreates the schema; pass confirm_wipe=True "
                "(--rebuild --confirm-wipe on the CLI) to proceed"
            )
        database.wipe_database_file(db_path)
        roster_path = understat_path = votes_dir = matches_dir = prices_path = None
        manual_fbref_dir = None
        force = True

    conn = database.get_connection(db_path)
    database.init_schema(conn)
    counts: dict[str, object] = {}
    errors: dict[str, str] = {}
    manifest_sources = build_module.resolve_sources(season, manifest_file, data_dir)

    def load_kind(kind: str) -> int:
        total = 0
        for source in manifest_sources:
            if source.kind != kind:
                continue
            result = build_module.load_one_source(conn, source, force=force)
            if result.status == "error":
                errors[result.key] = result.detail or ""
            total += result.rows
        return total

    try:
        # Roster: load first so multi-club current-season aggregates can
        # resolve to the officially reconciled destination club.
        if roster_path is not None:
            roster_path = Path(roster_path)
            if roster_path.exists():
                counts["rosters"] = rosters.load(conn, roster_path, season)
        else:
            counts["rosters"] = load_kind("roster")

        if understat_path is not None:
            counts["understat"] = understat.load(conn, Path(understat_path))
        else:
            counts["understat"] = load_kind("player-season")
            counts["understat_matches"] = load_kind("understat-matches")

        if votes_dir is not None:
            votes_dir = Path(votes_dir)
            if votes_dir.exists():
                counts["votes"] = votes.load(conn, votes_dir, season)
        else:
            for source in manifest_sources:
                if source.kind != "votes":
                    continue
                result = build_module.load_one_source(conn, source, force=force)
                if result.status == "error":
                    errors[result.key] = result.detail or ""
                elif result.rows:
                    season_key = season_label(source.season).replace("/", "_")
                    counts[f"votes_{season_key}"] = result.rows

        if matches_dir is not None:
            matches_dir = Path(matches_dir)
            if matches_dir.exists():
                counts["matches"] = football_data.load(conn, matches_dir)
        else:
            counts["matches"] = load_kind("match-results-tree")

        if coaches_path:
            counts["coaches"] = coaches.load(conn, Path(coaches_path))

        if prices_path is not None:
            prices_path = Path(prices_path)
            if prices_path.exists():
                counts["prices"] = prices.load(conn, prices_path, season)
        else:
            counts["prices"] = load_kind("prices")

        if manual_fbref_dir is not None:
            manual_fbref_dir = Path(manual_fbref_dir)
            if manual_fbref_dir.exists():
                counts["fbref"] = fbref.load(conn, manual_fbref_dir, season)
        else:
            counts["fbref"] = load_kind("fbref-manual")

        counts = {key: value for key, value in counts.items() if value}
        if errors:
            counts["_errors"] = errors
        conn.commit()
        return counts
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=config.DATA_DIR / "fantapredictor.db")
    parser.add_argument("--season", default="2627")
    parser.add_argument("--roster", type=Path)
    parser.add_argument("--understat", type=Path)
    parser.add_argument("--votes-dir", type=Path)
    parser.add_argument("--matches-dir", type=Path)
    parser.add_argument("--coaches", type=Path)
    parser.add_argument("--prices", type=Path)
    parser.add_argument("--manual-fbref-dir", type=Path)
    parser.add_argument(
        "--rebuild", action="store_true",
        help="Drop and recreate the schema, then reload the full declared manifest.",
    )
    parser.add_argument(
        "--confirm-wipe", action="store_true",
        help="Required alongside --rebuild to acknowledge the database is dropped first.",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Reload every manifest source even if its checksum has not changed.",
    )
    args = parser.parse_args()
    counts = build(
        args.db,
        args.roster,
        args.understat,
        args.votes_dir,
        args.matches_dir,
        args.coaches,
        args.prices,
        args.season,
        args.manual_fbref_dir,
        rebuild=args.rebuild,
        confirm_wipe=args.confirm_wipe,
        force=args.force,
    )
    errors = counts.pop("_errors", None)
    for name, count in counts.items():
        print(f"{name}: {count}")
    if errors:
        print("errors:")
        for source_key, message in errors.items():
            print(f"  {source_key}: {message}")
    print(f"database: {args.db}")
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
