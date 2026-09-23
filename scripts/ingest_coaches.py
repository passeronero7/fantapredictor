#!/usr/bin/env python3
"""Load the curated, dated coach history CSV into the warehouse (idempotent).

Columns: season, club, coach, started_at, ended_at, preferred_module,
style_tags, source_url, notes. Record an in-season change by setting
``ended_at`` on the outgoing stint and adding the incoming stint with the
same date as ``started_at``; re-running updates rows in place.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config.settings import config
from src.db import database
from src.db.ingestors import coaches
from src.models.coach_profiles import coach_matchdays


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=config.DATA_DIR / "fantapredictor.db")
    parser.add_argument("--csv", type=Path, required=True)
    args = parser.parse_args()
    conn = database.get_connection(args.db)
    database.init_schema(conn)
    try:
        loaded = coaches.load(conn, args.csv)
        stints = conn.execute("SELECT COUNT(*) FROM coach_club_seasons").fetchone()[0]
        current = conn.execute(
            """SELECT c.name, co.full_name FROM coach_club_seasons ccs
               JOIN coaches co ON co.id = ccs.coach_id JOIN clubs c ON c.id = ccs.club_id
               JOIN seasons s ON s.id = ccs.season_id
               WHERE ccs.ended_at IS NULL AND s.start_year = (SELECT MAX(start_year) FROM seasons
                 WHERE id IN (SELECT season_id FROM coach_club_seasons))
               ORDER BY c.name""").fetchall()
        attributed = len(coach_matchdays(conn))
    finally:
        conn.close()
    print(f"coach rows loaded: {loaded}; stints in warehouse: {stints}; "
          f"club-matchdays attributed: {attributed}")
    print("current coaches: " + "; ".join(f"{club}: {coach}" for club, coach in current))


if __name__ == "__main__":
    main()
