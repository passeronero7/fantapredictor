"""Offline loader for normalized official Fantacalcio vote files."""

from __future__ import annotations

from pathlib import Path

from src.data_processing.votes_processor import VotesProcessor
from src.db.ingestors.common import club_id, finish_run, player_id, season_label, source_id, start_run


def load(conn, directory: str | Path, season: str) -> int:
    """Load one row per player/matchday, ignoring aggregate ``Full`` files."""
    directory = Path(directory)
    processor = VotesProcessor(season=season)
    processor.votes_dir = directory
    frame = processor.process_all_matchdays()
    if frame.empty:
        return 0
    run_id, _ = start_run(conn, "fantacalcio")
    season_id = _season_id(conn, season_label(season))
    sid = source_id(conn, "fantacalcio")
    loaded = 0
    try:
        for row in frame.to_dict("records"):
            name = str(row.get("player", "")).strip()
            team = str(row.get("team", "")).strip()
            matchday = int(row.get("matchday", 0))
            if not name or not team or not matchday:
                continue
            pid = player_id(conn, name, "fantacalcio", row.get("id"), row.get("role"))
            cid = club_id(conn, team, "fantacalcio")
            conn.execute(
                """INSERT INTO player_match_ratings
                   (season_id, matchday, player_id, club_id, vote, fantavoto,
                    vote_statistical, fantavoto_statistical, vote_italy,
                    fantavoto_italy, goals, goals_conceded, assists, yellow_cards,
                    red_cards, penalties_saved, penalties_missed, penalties_scored,
                    own_goals, source_id, source_ref, source_file)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(season_id, matchday, player_id, club_id, source_id)
                   DO UPDATE SET vote=excluded.vote, fantavoto=excluded.fantavoto,
                     vote_statistical=excluded.vote_statistical,
                     fantavoto_statistical=excluded.fantavoto_statistical,
                     vote_italy=excluded.vote_italy, fantavoto_italy=excluded.fantavoto_italy,
                     goals=excluded.goals, assists=excluded.assists, updated_at=datetime('now')""",
                (season_id, matchday, pid, cid, row.get("vote"), row.get("fantavoto"),
                 row.get("vote_statistical"), row.get("fantavoto_statistical"),
                 row.get("vote_italy"), row.get("fantavoto_italy"), row.get("goals", 0),
                 row.get("goals_conceded", 0), row.get("assists", 0), row.get("yellow_cards", 0),
                 row.get("red_cards", 0), row.get("penalties_saved", 0), row.get("penalties_missed", 0),
                 row.get("penalties_scored", 0), row.get("own_goals", 0), sid,
                 f"{season}:{matchday}:{row.get('id', name)}", str(directory)),
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
