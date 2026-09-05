#!/usr/bin/env python3
"""Ingest the SoFIFA/EA FC attribute snapshot into the warehouse."""
import argparse, json, sys
from pathlib import Path
import pandas as pd
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from config.settings import config
from src.db import database
from src.db.ingestors.common import player_id, start_run, finish_run, source_id
from src.utils.name_matching import normalize_name

TECHNIQUE = ["Finishing","Shot Power","Long Shots","Volleys","Penalties","Vision","Crossing",
             "Free Kick Accuracy","Short Passing","Long Passing","Curve","Dribbling","Agility",
             "Balance","Reactions","Ball Control","Composure","Interceptions","Heading Accuracy",
             "Def Awareness","Standing Tackle","Sliding Tackle","Jumping","Stamina","Strength"]
ATTITUDE = ["Aggression","Positioning","Vision","Composure","Reactions"]

def load(conn, path, snapshot="eafc26") -> int:
    frame = pd.read_csv(path)
    run_id, _ = start_run(conn, "leaf-node-manual")
    loaded = 0
    try:
        for row in frame.to_dict("records"):
            name = str(row.get("Name", "")).strip()
            if not name:
                continue
            pid = player_id(conn, name, "leaf-node-manual")
            technique = {k: row.get(k) for k in TECHNIQUE if pd.notna(row.get(k))}
            attitude = {k: row.get(k) for k in ATTITUDE if pd.notna(row.get(k))}
            conn.execute(
                """INSERT INTO player_attributes (player_id, snapshot, overall, position, technique, attitude)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(player_id, snapshot) DO UPDATE SET overall=excluded.overall,
                     position=excluded.position, technique=excluded.technique,
                     attitude=excluded.attitude, updated_at=datetime('now')""",
                (pid, snapshot, row.get("OVR"), row.get("Position"),
                 json.dumps(technique), json.dumps(attitude)),
            )
            loaded += 1
        finish_run(conn, run_id, "ok", loaded)
        conn.commit()
        return loaded
    except Exception as exc:
        finish_run(conn, run_id, "error", loaded, str(exc))
        conn.rollback()
        raise

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=config.DATA_DIR / "fantapredictor.db")
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--snapshot", default="eafc26")
    args = parser.parse_args()
    conn = database.get_connection(args.db)
    database.init_schema(conn)
    try:
        print(f"attributes loaded: {load(conn, args.csv, args.snapshot)}")
    finally:
        conn.close()
