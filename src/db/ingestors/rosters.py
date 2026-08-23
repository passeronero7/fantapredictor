"""Offline loader for the provisional Virgilio roster snapshot."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.db.ingestors.common import club_id, finish_run, player_id, season_label, start_run


def load(conn, path: str | Path, season: str) -> int:
    """Load roster memberships from the existing CSV snapshot."""
    frame = pd.read_csv(path)
    run_id, _ = start_run(conn, "virgilio")
    label = season_label(season)
    season_id = _season_id(conn, label)
    loaded = 0
    try:
        for row in frame.to_dict("records"):
            name = str(row.get("player", "")).strip()
            club = str(row.get("club_2026_27", row.get("club", ""))).strip()
            if not name or not club:
                continue
            cid = club_id(conn, club, "virgilio")
            pid = player_id(conn, name, "virgilio")
            status = row.get("status", "confirmed")
            if status not in {"confirmed", "watchlist", "excluded"}:
                status = "watchlist"
            conn.execute(
                """INSERT INTO roster_memberships
                   (player_id, club_id, season_id, status, source_url, checked_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(player_id, club_id, season_id)
                   DO UPDATE SET status=excluded.status, source_url=excluded.source_url,
                     checked_at=excluded.checked_at""",
                (pid, cid, season_id, status, row.get("source_url"), row.get("checked_at")),
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
    cursor = conn.execute("INSERT INTO seasons (name, start_year) VALUES (?, ?)", (label, int(label[:4])))
    return int(cursor.lastrowid)
