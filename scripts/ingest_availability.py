#!/usr/bin/env python3
"""Ingest the curated availability (injury/stop) CSV into the warehouse."""
import argparse, sys
from datetime import date
from pathlib import Path
import pandas as pd
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from config.settings import config
from src.db import database
from src.db.ingestors.common import player_id

def load(conn, path: Path) -> int:
    frame = pd.read_csv(path)
    for row in frame.to_dict("records"):
        pid = player_id(conn, str(row["player"]), "leaf-node-manual")
        conn.execute(
            """INSERT INTO availability_notes (player_id, club, kind, expected_return, source_url, checked_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(player_id, kind) DO UPDATE SET club=excluded.club,
                 expected_return=excluded.expected_return, source_url=excluded.source_url,
                 checked_at=excluded.checked_at""",
            (pid, row.get("club"), row["kind"], row.get("expected_return"),
             row.get("source_url"), row.get("checked_at")),
        )
    conn.commit()
    return len(frame)

def horizon_factor(expected_return: str, horizon_start: date, horizon_days: int) -> float:
    """Fraction of the horizon the player is available, as a p_plays multiplier."""
    try:
        ret = date.fromisoformat(str(expected_return)[:10])
    except (TypeError, ValueError):
        return 1.0
    if ret <= horizon_start:
        return 1.0
    missed = (ret - horizon_start).days
    return max(0.0, 1.0 - min(missed, horizon_days) / max(horizon_days, 1))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=config.DATA_DIR / "fantapredictor.db")
    parser.add_argument("--csv", type=Path, required=True)
    args = parser.parse_args()
    conn = database.get_connection(args.db)
    database.init_schema(conn)
    try:
        print(f"availability rows loaded: {load(conn, args.csv)}")
    finally:
        conn.close()
