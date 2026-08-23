#!/usr/bin/env python3
"""Build the local FantaPredictor SQLite warehouse from downloaded files."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config.settings import config
from src.db import database
from src.db.ingestors import coaches, football_data, prices, rosters, understat, votes


def build(
    db_path: str | Path,
    roster_path: str | Path | None = None,
    understat_path: str | Path | None = None,
    votes_dir: str | Path | None = None,
    matches_dir: str | Path | None = None,
    coaches_path: str | Path | None = None,
    prices_path: str | Path | None = None,
    season: str = "2627",
) -> dict[str, int]:
    """Initialize and populate the warehouse from local source snapshots."""
    season_dir = config.get_season_dir(season)
    roster_path = Path(roster_path or season_dir / "rosters" / "virgilio_rosters_2026_27.csv")
    understat_path = Path(understat_path or season_dir / "raw" / "understat_players_aggregated_2014_td.csv")
    explicit_votes_dir = votes_dir is not None
    votes_dir = Path(votes_dir or season_dir / "fantacalcio" / config.VOTES_DIR)
    matches_dir = Path(matches_dir or config.DATA_DIR / "raw" / "football-data.co.uk")
    prices_path = Path(prices_path or season_dir / "fantacalcio" / "prices.csv")

    conn = database.get_connection(db_path)
    database.init_schema(conn)
    counts: dict[str, int] = {}
    try:
        if understat_path.exists():
            counts["understat"] = understat.load(conn, understat_path)
        if roster_path.exists():
            counts["rosters"] = rosters.load(conn, roster_path, season)
        if explicit_votes_dir:
            if votes_dir.exists():
                counts["votes"] = votes.load(conn, votes_dir, season)
        else:
            vote_directories = sorted(config.DATA_DIR.glob("season_*/fantacalcio/voti"))
            for directory in vote_directories:
                season_name = directory.parts[-3].removeprefix("season_")
                season_value = season_name.replace("_", "/")
                counts[f"votes_{season_name}"] = votes.load(conn, directory, season_value)
        if matches_dir.exists():
            counts["matches"] = football_data.load(conn, matches_dir)
        if coaches_path:
            counts["coaches"] = coaches.load(conn, coaches_path)
        if prices_path.exists():
            counts["prices"] = prices.load(conn, prices_path, season)
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
    )
    for name, count in counts.items():
        print(f"{name}: {count}")
    print(f"database: {args.db}")


if __name__ == "__main__":
    main()
