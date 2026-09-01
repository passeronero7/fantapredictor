"""Offline importer for browser-exported FBref player tables.

FBref must be exported by a user in a browser; this module deliberately makes
no HTTP requests.  Every numeric column is retained in the generic
``player_season_stat_values`` table, which keeps the provider's detailed skill
metrics available without silently mapping unlike definitions together.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from src.data_processing.fbref_manual import load_manual_exports
from src.db.ingestors.common import (
    club_id,
    finish_run,
    player_id,
    season_label,
    source_id,
    start_run,
)
from src.utils.name_matching import normalize_name

_IDENTIFIER_COLUMNS = {
    "player", "player_name", "squad", "team", "club", "nation", "nationality",
    "position", "pos", "age", "born", "rank", "fbref_player_id", "matches",
    "comp", "competition",
}
_CLUB_COLUMNS = ("squad", "team", "club")


def _metric_name(column: object) -> str:
    """Turn a provider header into a stable, readable SQLite metric key."""
    text = str(column).strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return text


def _club_column(frame: pd.DataFrame) -> str | None:
    return next((column for column in frame.columns if _metric_name(column) in _CLUB_COLUMNS), None)


def _numeric_value(value: object) -> float | None:
    """Parse FBref's display values while preserving blank/missing values."""
    if value is None or pd.isna(value):
        return None
    text = str(value).strip().replace(",", "").removesuffix("%")
    if text.lower() in {"", "-", "nan", "n/a"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _player_for_club(conn, name: str, club: str, season_id: int) -> int:
    """Resolve a manual-export row against the season roster before name fallback.

    FBref CSVs do not reliably contain a portable player identifier. Matching a
    unique season-and-club roster record first prevents two players with the
    same normalized name at different clubs from being silently conflated.
    """
    normalized = normalize_name(name)
    rows = conn.execute(
        """SELECT p.id
           FROM roster_memberships AS rm
           JOIN players AS p ON p.id = rm.player_id
           WHERE rm.season_id = ? AND rm.club_id = ? AND p.normalized_name = ?
           ORDER BY p.id""",
        (season_id, club, normalized),
    ).fetchall()
    if len(rows) == 1:
        return int(rows[0]["id"])
    return player_id(conn, name, "fbref")


def load(conn, directory: str | Path, season: str) -> int:
    """Import all available local FBref exports and return metrics upserted."""
    exports = load_manual_exports(directory, season)
    if not exports:
        return 0
    run_id, _ = start_run(conn, "fbref")
    sid = source_id(conn, "fbref")
    season_id = _season_id(conn, season_label(season))
    loaded = 0
    try:
        for category, frame in exports.items():
            club_column = _club_column(frame)
            player_column = "player"
            numeric_columns = [
                column for column in frame.columns
                if _metric_name(column) not in _IDENTIFIER_COLUMNS | {"source_file"}
            ]
            for row in frame.to_dict("records"):
                name = str(row.get(player_column, "")).strip()
                # Browser-exported tables occasionally repeat their header in
                # the body; do not create a fictional player called "Player".
                if not name or _metric_name(name) == "player":
                    continue
                club = str(row.get(club_column, "Unknown")).strip() if club_column else "Unknown"
                cid = club_id(conn, club or "Unknown", "fbref")
                pid = _player_for_club(conn, name, cid, season_id)
                source_file = str(row.get("source_file", ""))
                for column in numeric_columns:
                    value = _numeric_value(row.get(column))
                    if value is None:
                        continue
                    metric = _metric_name(column)
                    if not metric:
                        continue
                    conn.execute(
                        """INSERT INTO player_season_stat_values
                           (player_id, club_id, season_id, category, metric, metric_label,
                            value, source_id, source_file)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                           ON CONFLICT(player_id, club_id, season_id, category, metric,
                                       source_id, source_file)
                           DO UPDATE SET metric_label=excluded.metric_label,
                             value=excluded.value, updated_at=datetime('now')""",
                        (pid, cid, season_id, category, metric, str(column), value, sid, source_file),
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
    cursor = conn.execute(
        "INSERT INTO seasons (name, start_year) VALUES (?, ?)", (label, int(label[:4]))
    )
    return int(cursor.lastrowid)
