"""Offline loader for the public Understat aggregate CSV."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.db.ingestors.common import (
    club_id,
    finish_run,
    integer,
    number,
    player_id,
    season_label,
    source_id,
    start_run,
)


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
            pid = player_id(conn, name, "understat", row.get("id"), row.get("primary_position"))
            cid = _stats_club_id(conn, str(row.get("team_title", "Unknown")), pid, season_id)
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
                "xg_chain": row.get("xGChain"),
                "xg_buildup": row.get("xGBuildup"),
                "shots": row.get("shots"),
                "key_passes": row.get("key_passes"),
                "yellow_cards": row.get("yellow_cards"),
                "red_cards": row.get("red_cards"),
            }
            source_ref = str(row.get("id", ""))
            existing = conn.execute(
                """SELECT id FROM player_season_stats
                   WHERE player_id = ? AND season_id = ? AND club_id IS ?
                     AND source_id = ? AND source_ref = ?""",
                (pid, season_id, cid, sid, source_ref),
            ).fetchone()
            columns = list(values)
            if existing:
                assignments = ", ".join(f"{column} = ?" for column in columns)
                conn.execute(
                    f"UPDATE player_season_stats SET {assignments}, updated_at=datetime('now') WHERE id = ?",
                    (*[values[key] for key in columns], int(existing["id"])),
                )
            else:
                conn.execute(
                    """INSERT INTO player_season_stats
                       (player_id, club_id, season_id, games, minutes, goals, assists,
                        goals_pens, xg, xa, npxg, xg_plus_xa, xg_chain, xg_buildup,
                        shots, key_passes, yellow_cards, red_cards, source_id, source_ref)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (pid, cid, season_id, *[values[key] for key in columns], sid, source_ref),
                )
            loaded += 1
        finish_run(conn, run_id, "ok", loaded)
        conn.commit()
        return loaded
    except Exception as exc:
        finish_run(conn, run_id, "error", loaded, str(exc))
        conn.rollback()
        raise


def _stats_club_id(conn, team_title: str, pid: int, season_id: int) -> int | None:
    """Resolve single-club rows and official destinations for multi-club aggregates."""
    teams = [team.strip() for team in team_title.split(",") if team.strip()]
    if not teams:
        return club_id(conn, "Unknown", "understat")
    candidate_ids = [club_id(conn, team, "understat") for team in teams]
    if len(candidate_ids) == 1:
        return candidate_ids[0]
    placeholders = ", ".join("?" for _ in candidate_ids)
    membership = conn.execute(
        f"""SELECT club_id FROM roster_memberships
            WHERE player_id = ? AND season_id = ? AND club_id IN ({placeholders})
              AND status != 'excluded'
            ORDER BY CASE status WHEN 'confirmed' THEN 0 ELSE 1 END
            LIMIT 1""",
        (pid, season_id, *candidate_ids),
    ).fetchone()
    # Historical aggregate values span every listed club and must not be
    # attributed to an arbitrary one when no roster evidence is available.
    return int(membership["club_id"]) if membership else None


def load_matches(conn, path: str | Path, league: str = "Serie_A") -> int:
    """Load a completed Understat match snapshot with score and xG values."""
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
            home = str(row.get("home_team", "")).strip()
            away = str(row.get("away_team", "")).strip()
            source_ref = str(row.get("match_id", "")).strip()
            match_date = str(row.get("match_date", "")).strip()
            if not home or not away or not source_ref or not match_date:
                continue
            season_id = _season_id(conn, season_label(row["year"]))
            home_id = club_id(conn, home, "understat", row.get("home_team_id"))
            away_id = club_id(conn, away, "understat", row.get("away_team_id"))
            conn.execute(
                """INSERT INTO matches
                   (season_id, matchday, match_date, home_club_id, away_club_id,
                    home_goals, away_goals, home_xg, away_xg, source_id, source_match_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(source_id, source_match_id)
                   DO UPDATE SET season_id=excluded.season_id,
                     matchday=excluded.matchday, match_date=excluded.match_date,
                     home_club_id=excluded.home_club_id, away_club_id=excluded.away_club_id,
                     home_goals=excluded.home_goals, away_goals=excluded.away_goals,
                     home_xg=excluded.home_xg, away_xg=excluded.away_xg,
                     updated_at=datetime('now')""",
                (
                    season_id,
                    integer(row.get("matchday")),
                    match_date,
                    home_id,
                    away_id,
                    integer(row.get("home_goals")),
                    integer(row.get("away_goals")),
                    number(row.get("home_xg")),
                    number(row.get("away_xg")),
                    sid,
                    source_ref,
                ),
            )
            match_id = int(conn.execute(
                "SELECT id FROM matches WHERE source_id = ? AND source_match_id = ?",
                (sid, source_ref),
            ).fetchone()["id"])
            for cid, side, xg in (
                (home_id, "home", number(row.get("home_xg"))),
                (away_id, "away", number(row.get("away_xg"))),
            ):
                conn.execute(
                    """INSERT INTO match_team_stats (match_id, club_id, side, xg)
                       VALUES (?, ?, ?, ?)
                       ON CONFLICT(match_id, side) DO UPDATE SET
                         club_id=excluded.club_id, xg=excluded.xg""",
                    (match_id, cid, side, xg),
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
