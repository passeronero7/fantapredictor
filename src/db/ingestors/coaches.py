"""Offline loader for a human-curated coach history CSV."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.db.ingestors.common import club_id, finish_run, season_label, source_id, start_run
from src.utils.name_matching import normalize_name


def load(conn, path: str | Path) -> int:
    """Load coach tenures and optional season summaries from a CSV."""
    frame = pd.read_csv(path)
    required = {"season", "club", "coach"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Coach CSV missing columns: {', '.join(sorted(missing))}")
    run_id, _ = start_run(conn, "leaf-node-manual")
    sid = source_id(conn, "leaf-node-manual")
    loaded = 0
    try:
        for row in frame.to_dict("records"):
            coach_name = str(row["coach"]).strip()
            if not coach_name:
                continue
            label = season_label(row["season"])
            season_id = _season_id(conn, label)
            cid = club_id(conn, row["club"], "leaf-node-manual")
            coach = conn.execute(
                "SELECT id FROM coaches WHERE full_name = ? ORDER BY id LIMIT 1",
                (coach_name,),
            ).fetchone()
            if coach:
                coach_id = int(coach["id"])
            else:
                coach_id = int(conn.execute(
                    "INSERT INTO coaches (full_name, source_id, source_ref) VALUES (?, ?, ?)",
                    (coach_name, sid, normalize_name(coach_name)),
                ).lastrowid)
            conn.execute(
                """INSERT INTO coach_club_seasons
                   (coach_id, club_id, season_id, started_at, ended_at, source_url, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(coach_id, club_id, season_id, started_at)
                   DO UPDATE SET ended_at=excluded.ended_at, source_url=excluded.source_url,
                     notes=excluded.notes""",
                (coach_id, cid, season_id, row.get("started_at"), row.get("ended_at"),
                 row.get("source_url"), row.get("notes")),
            )
            if any(column in row for column in ("matches", "wins", "draws", "losses", "final_rank")):
                conn.execute(
                    """INSERT INTO coach_season_stats
                       (coach_id, club_id, season_id, matches, wins, draws, losses,
                        goals_for, goals_against, final_rank, source_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(coach_id, club_id, season_id)
                       DO UPDATE SET matches=excluded.matches, wins=excluded.wins,
                         draws=excluded.draws, losses=excluded.losses,
                         goals_for=excluded.goals_for, goals_against=excluded.goals_against,
                         final_rank=excluded.final_rank""",
                    (coach_id, cid, season_id, row.get("matches"), row.get("wins"),
                     row.get("draws"), row.get("losses"), row.get("goals_for"),
                     row.get("goals_against"), row.get("final_rank"), sid),
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
