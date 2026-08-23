"""Offline loader for Fantacalcio quotation CSV snapshots."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.db.ingestors.common import club_id, finish_run, player_id, season_label, source_id, start_run


def load(conn, path: str | Path, season: str) -> int:
    """Load classic auction quotations and FVM values."""
    frame = pd.read_csv(path)
    run_id, _ = start_run(conn, "fantacalcio")
    season_id = _season_id(conn, season_label(season))
    sid = source_id(conn, "fantacalcio")
    loaded = 0
    try:
        for row in frame.to_dict("records"):
            name = str(row.get("player", "")).strip()
            if not name:
                continue
            pid = player_id(conn, name, "fantacalcio", row.get("source_ref"), row.get("role_classic"))
            cid = club_id(conn, str(row.get("team", "Unknown")), "fantacalcio")
            conn.execute(
                """INSERT INTO player_prices
                   (season_id, player_id, club_id, role_classic, role_mantra,
                    price_initial, price_current, fvm, source_id, source_ref)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(season_id, player_id, source_id)
                   DO UPDATE SET club_id=excluded.club_id, role_classic=excluded.role_classic,
                     role_mantra=excluded.role_mantra, price_current=excluded.price_current,
                     fvm=excluded.fvm, updated_at=datetime('now')""",
                (season_id, pid, cid, row.get("role_classic"), row.get("role_mantra"),
                 row.get("price_initial"), row.get("price_current"), row.get("fvm"), sid,
                 row.get("source_ref")),
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
