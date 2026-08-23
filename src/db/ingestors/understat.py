"""Offline loader for the public Understat aggregate CSV."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.db.ingestors.common import club_id, finish_run, player_id, season_label, source_id, start_run


def load(conn, path: str | Path, league: str = "Serie_A") -> int:
    """Load Understat player-season rows and return the inserted row count."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    frame = pd.read_csv(path)
    if "league" in frame.columns:
        frame = frame[frame["league"].eq(league)].copy()
    run_id, _ = start_run(conn, "understat")
    loaded = 0
    try:
        sid = source_id(conn, "understat")
        for row in frame.to_dict("records"):
            name = str(row.get("player_name", "")).strip()
            if not name:
                continue
            season = season_label(row["year"])
            season_id = _season_id(conn, season)
            cid = club_id(conn, row.get("team_title", "Unknown"), "understat")
            pid = player_id(conn, name, "understat", row.get("id"), row.get("primary_position"))
            values = {
                "games": row.get("games"),
                "minutes": row.get("time"),
                "goals": row.get("goals"),
                "assists": row.get("assists"),
                "goals_pens": row.get("npg"),
                "xg": row.get("xG"),
                "xa": row.get("xA"),
                "npxg": row.get("npxG"),
                "xg_plus_xa": (row.get("xG", 0) or 0) + (row.get("xA", 0) or 0),
                "shots": row.get("shots"),
                "key_passes": row.get("key_passes"),
                "yellow_cards": row.get("yellow_cards"),
                "red_cards": row.get("red_cards"),
            }
            conn.execute(
                """INSERT INTO player_season_stats
                   (player_id, club_id, season_id, games, minutes, goals, assists,
                    goals_pens, xg, xa, npxg, xg_plus_xa, shots, key_passes,
                    yellow_cards, red_cards, source_id, source_ref)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(player_id, season_id, club_id, source_id, source_ref)
                   DO UPDATE SET games=excluded.games, minutes=excluded.minutes,
                     goals=excluded.goals, assists=excluded.assists, xg=excluded.xg,
                     xa=excluded.xa, npxg=excluded.npxg, updated_at=datetime('now')""",
                (pid, cid, season_id, *[values[key] for key in values], sid, str(row.get("id", ""))),
            )
            loaded += 1
        finish_run(conn, run_id, "ok", loaded)
        conn.commit()
        return loaded
    except Exception as exc:
        finish_run(conn, run_id, "error", loaded, str(exc))
        conn.rollback()
        raise


def _season_id(conn, label: str) -> int:
    row = conn.execute("SELECT id FROM seasons WHERE name = ?", (label,)).fetchone()
    if row:
        return int(row["id"])
    start_year = int(label[:4])
    cursor = conn.execute("INSERT INTO seasons (name, start_year) VALUES (?, ?)", (label, start_year))
    return int(cursor.lastrowid)
