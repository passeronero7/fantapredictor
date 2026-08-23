"""Offline loader for Football-Data.co.uk Italian match CSV files."""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from src.db.ingestors.common import (
    club_id,
    finish_run,
    integer,
    number,
    season_label,
    source_id,
    source_match_ref,
    start_run,
)


def load(conn, directory: str | Path, default_season: str | None = None) -> int:
    """Load every ``I1.csv`` file in a directory tree."""
    files = sorted(Path(directory).glob("**/I1.csv"))
    run_id, _ = start_run(conn, "football-data.co.uk")
    loaded = 0
    try:
        for path in files:
            season_code = path.parent.name if path.parent.name != "" else default_season
            if not season_code:
                continue
            loaded += _load_file(conn, path, season_code)
        finish_run(conn, run_id, "ok", loaded)
        conn.commit()
        return loaded
    except Exception as exc:
        finish_run(conn, run_id, "error", loaded, str(exc))
        conn.rollback()
        raise


def _load_file(conn, path: Path, season_code: str) -> int:
    label = season_label(season_code)
    season_id = _season_id(conn, label)
    sid = source_id(conn, "football-data.co.uk")
    loaded = 0
    with path.open("r", encoding="latin-1", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            home = (row.get("HomeTeam") or "").strip()
            away = (row.get("AwayTeam") or "").strip()
            raw_date = (row.get("Date") or "").strip()
            if not home or not away or not raw_date:
                continue
            match_date = _date(raw_date)
            source_ref = source_match_ref(season_code, match_date, home, away)
            home_id = club_id(conn, home, "football-data.co.uk")
            away_id = club_id(conn, away, "football-data.co.uk")
            conn.execute(
                """INSERT INTO matches
                   (season_id, match_date, home_club_id, away_club_id,
                    home_goals, away_goals, home_goals_half, away_goals_half,
                    source_id, source_match_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(source_id, source_match_id)
                   DO UPDATE SET home_goals=excluded.home_goals,
                     away_goals=excluded.away_goals, updated_at=datetime('now')""",
                (season_id, match_date, home_id, away_id, integer(row.get("FTHG")),
                 integer(row.get("FTAG")), integer(row.get("HTHG")), integer(row.get("HTAG")),
                 sid, source_ref),
            )
            match = conn.execute(
                "SELECT id FROM matches WHERE source_id = ? AND source_match_id = ?",
                (sid, source_ref),
            ).fetchone()
            match_id = int(match["id"])
            _upsert_team_stats(conn, match_id, home_id, "home", row)
            _upsert_team_stats(conn, match_id, away_id, "away", row)
            _upsert_odds(conn, match_id, row)
            loaded += 1
    return loaded


def _upsert_team_stats(conn, match_id: int, club: int, side: str, row: dict) -> None:
    prefix = "H" if side == "home" else "A"
    conn.execute(
        """INSERT INTO match_team_stats
           (match_id, club_id, side, shots, shots_on_target, corners, fouls,
            yellow_cards, red_cards)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(match_id, side) DO UPDATE SET shots=excluded.shots,
             shots_on_target=excluded.shots_on_target, corners=excluded.corners,
             fouls=excluded.fouls, yellow_cards=excluded.yellow_cards,
             red_cards=excluded.red_cards""",
        (match_id, club, side, integer(row.get(f"{prefix}S")), integer(row.get(f"{prefix}ST")),
         integer(row.get(f"{prefix}C")), integer(row.get(f"{prefix}F")),
         integer(row.get(f"{prefix}Y")), integer(row.get(f"{prefix}R"))),
    )


def _upsert_odds(conn, match_id: int, row: dict) -> None:
    for provider, home, draw, away in (
        ("B365", "B365H", "B365D", "B365A"),
        ("BW", "BWH", "BWD", "BWA"),
        ("IW", "IWH", "IWD", "IWA"),
        ("PS", "PSH", "PSD", "PSA"),
        ("WH", "WHH", "WHD", "WHA"),
        ("VC", "VCH", "VCD", "VCA"),
    ):
        values = [number(row.get(column)) for column in (home, draw, away)]
        if any(value is not None for value in values):
            conn.execute(
                """INSERT INTO match_odds (match_id, provider, home, draw, away)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(match_id, provider) DO UPDATE SET home=excluded.home,
                     draw=excluded.draw, away=excluded.away""",
                (match_id, provider, *values),
            )


def _date(value: str) -> str:
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%d/%m/%Y %H:%M"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"Unsupported Football-Data date: {value!r}")


def _season_id(conn, label: str) -> int:
    row = conn.execute("SELECT id FROM seasons WHERE name = ?", (label,)).fetchone()
    if row:
        return int(row["id"])
    cursor = conn.execute("INSERT INTO seasons (name, start_year) VALUES (?, ?)", (label, int(label[:4])))
    return int(cursor.lastrowid)
