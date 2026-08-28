#!/usr/bin/env python3
"""Inspect a local FantaPredictor SQLite warehouse without the sqlite3 CLI."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config.settings import config
from src.db import __version__ as schema_version

TABLES = (
    "sources", "ingestion_runs", "clubs", "players", "seasons",
    "roster_memberships", "matches", "match_team_stats", "match_odds",
    "player_season_stats", "player_season_stat_values", "player_match_ratings", "player_prices",
)


def connection(path: str | Path) -> sqlite3.Connection:
    """Open a read-only connection to avoid accidental inspection writes."""
    path = Path(path).resolve()
    if not path.exists():
        raise FileNotFoundError(path)
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def summary(path: str | Path) -> None:
    """Print schema version and row counts for warehouse tables."""
    conn = connection(path)
    try:
        print(f"database: {Path(path).resolve()}")
        print(f"schema_version: {schema_version}")
        print(f"integrity: {conn.execute('PRAGMA integrity_check').fetchone()[0]}")
        for table in TABLES:
            count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            print(f"{table}: {count}")
    finally:
        conn.close()


def run_sql(path: str | Path, statement: str) -> None:
    """Run a read-only SQL statement and print column names and rows."""
    conn = connection(path)
    try:
        cursor = conn.execute(statement)
        if cursor.description:
            print("\t".join(column[0] for column in cursor.description))
            for row in cursor:
                print("\t".join("" if value is None else str(value) for value in row))
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=config.DATA_DIR / "fantapredictor.db")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("summary", help="show schema, integrity, and table counts")
    sql_parser = subparsers.add_parser("sql", help="run one read-only SQL statement")
    sql_parser.add_argument("statement")
    args = parser.parse_args()
    if args.command == "summary":
        summary(args.db)
    else:
        run_sql(args.db, args.statement)


if __name__ == "__main__":
    main()
