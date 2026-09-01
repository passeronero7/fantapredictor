"""Small shared helpers for offline source ingestors."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from numbers import Integral
from typing import Any

from src.db.database import TEAM_ALIAS_MAP, get_or_create_club
from src.utils.name_matching import normalize_name


def utc_now() -> str:
    """Return a sortable UTC timestamp."""
    return datetime.now(UTC).isoformat()


def source_id(conn, slug: str) -> int:
    """Resolve a registered source slug to its database id."""
    row = conn.execute("SELECT id FROM sources WHERE slug = ?", (slug,)).fetchone()
    if row is None:
        raise ValueError(f"Source is not registered: {slug}")
    return int(row["id"])


def season_label(value: str | int) -> str:
    """Convert compact or full season identifiers to ``YYYY/YY``."""
    if isinstance(value, Integral):
        start = int(value)
        return f"{start}/{(start + 1) % 100:02d}"
    text = str(value).strip().replace("-", "/").replace("_", "/")
    if re.fullmatch(r"\d{4}", text):
        short_start, short_end = int(text[:2]), int(text[2:])
        if short_end == (short_start + 1) % 100:
            start = (2000 if short_start < 70 else 1900) + short_start
        else:
            start = int(text)
        return f"{start}/{(start + 1) % 100:02d}"
    if re.fullmatch(r"\d{2}/\d{2}", text):
        start = int(text[:2])
        start += 2000 if start < 70 else 1900
        return f"{start}/{int(text[-2:]):02d}"
    if re.fullmatch(r"\d{4}/\d{2}", text):
        return text
    raise ValueError(f"Unsupported season value: {value!r}")


def number(value: Any, default: float | None = None) -> float | None:
    """Parse provider numbers, returning ``default`` for blanks and markers."""
    if value is None:
        return default
    text = str(value).strip().replace(",", ".")
    if text.lower() in {"", "nan", "null", "-", "na", "n/a"}:
        return default
    try:
        return float(text)
    except ValueError:
        return default


def integer(value: Any, default: int | None = None) -> int | None:
    """Parse a provider integer without silently turning blanks into zero."""
    parsed = number(value)
    return default if parsed is None else int(parsed)


def player_id(conn, name: str, source: str, source_ref: Any = None, role: str | None = None) -> int:
    """Create or resolve a player and retain a source-specific identity alias."""
    source_ref_text = None if source_ref is None else str(source_ref).strip()
    if source_ref_text and source_ref_text.lower() in {"nan", "none", "null", "<na>"}:
        source_ref_text = None
    sid = source_id(conn, source)
    normalized = normalize_name(name)
    row = None
    if source_ref_text:
        row = conn.execute(
            """SELECT player_id FROM player_aliases
               WHERE source_id = ? AND source_ref = ?""",
            (sid, source_ref_text),
        ).fetchone()
    if row is None:
        row = conn.execute(
            "SELECT id FROM players WHERE normalized_name = ? ORDER BY id LIMIT 1",
            (normalized,),
        ).fetchone()
    if row is not None:
        pid = int(row["player_id"] if "player_id" in row.keys() else row["id"])
        if role:
            conn.execute("UPDATE players SET role = COALESCE(role, ?) WHERE id = ?", (role, pid))
    else:
        cursor = conn.execute(
            "INSERT INTO players (full_name, normalized_name, role, source_id, source_ref) VALUES (?, ?, ?, ?, ?)",
            (name, normalized, role, sid, source_ref_text),
        )
        pid = int(cursor.lastrowid)
    if source_ref_text:
        conn.execute(
            "INSERT OR IGNORE INTO player_aliases (player_id, source_id, source_ref, label) VALUES (?, ?, ?, ?)",
            (pid, sid, source_ref_text, name),
        )
    return pid


def club_id(conn, name: str, source: str, source_ref: Any = None) -> int:
    """Create or resolve a canonical club and preserve the raw alias."""
    canonical = TEAM_ALIAS_MAP.get(str(name).strip(), str(name).strip())
    sid = source_id(conn, source)
    cid = get_or_create_club(conn, canonical, source_id=sid, source_ref=source_ref)
    conn.execute(
        "INSERT OR IGNORE INTO team_aliases (club_id, alias, source_id) VALUES (?, ?, ?)",
        (cid, str(name).strip(), sid),
    )
    return cid


def source_match_ref(season: str, date: str, home: str, away: str) -> str:
    """Build a stable short source key for files without provider match ids."""
    raw = "|".join((season, date, home, away)).encode("utf-8")
    return hashlib.sha1(raw).hexdigest()


def start_run(conn, slug: str) -> tuple[int, str]:
    """Create an ingestion audit row."""
    started = utc_now()
    cursor = conn.execute(
        "INSERT INTO ingestion_runs (source_id, started_at) VALUES (?, ?)",
        (source_id(conn, slug), started),
    )
    return int(cursor.lastrowid), started


def finish_run(conn, run_id: int, status: str, rows: int, detail: str | None = None) -> None:
    """Finish an ingestion audit row."""
    conn.execute(
        """UPDATE ingestion_runs
           SET finished_at = ?, status = ?, rows_loaded = ?, detail = ?
           WHERE id = ?""",
        (utc_now(), status, rows, detail, run_id),
    )
