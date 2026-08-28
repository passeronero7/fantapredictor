"""Read model inputs from the normalized SQLite research warehouse."""

from __future__ import annotations

import sqlite3

import pandas as pd

from src.db.ingestors.common import season_label


def load_rosters(conn: sqlite3.Connection, season: str) -> pd.DataFrame:
    """Load roster assertions, including status and provenance metadata."""
    return pd.read_sql_query(
        """
        SELECT p.full_name AS player, p.normalized_name AS player_normalized,
               c.name AS club_2026_27, rm.role, rm.status, rm.source_url,
               rm.checked_at
        FROM roster_memberships AS rm
        JOIN players AS p ON p.id = rm.player_id
        JOIN clubs AS c ON c.id = rm.club_id
        JOIN seasons AS s ON s.id = rm.season_id
        WHERE s.name = ?
        ORDER BY p.full_name
        """,
        conn,
        params=(season_label(season),),
    )


def load_player_history(conn: sqlite3.Connection, league: str = "Serie_A") -> pd.DataFrame:
    """Load player-season statistics in the shape expected by processors."""
    frame = pd.read_sql_query(
        """
        SELECT ps.id, p.full_name AS player_name,
               p.normalized_name AS player_normalized,
               p.role AS primary_position, c.name AS team_title,
               s.start_year AS year, ps.games, ps.minutes AS time,
               ps.goals, ps.assists, ps.goals_pens AS npg,
               ps.npxg AS npxG, ps.xg AS xG, ps.xa AS xA, ps.shots,
               ps.xg_chain AS xGChain, ps.xg_buildup AS xGBuildup,
               ps.key_passes, ps.yellow_cards, ps.red_cards
        FROM player_season_stats AS ps
        JOIN players AS p ON p.id = ps.player_id
        LEFT JOIN clubs AS c ON c.id = ps.club_id
        JOIN seasons AS s ON s.id = ps.season_id
        JOIN sources AS src ON src.id = ps.source_id
        WHERE src.slug = 'understat'
        ORDER BY p.full_name, s.start_year
        """,
        conn,
    )
    frame["league"] = league
    return frame


def load_votes(conn: sqlite3.Connection) -> pd.DataFrame:
    """Load official player-match ratings from the warehouse."""
    return pd.read_sql_query(
        """
        SELECT p.full_name AS player, p.normalized_name AS player_normalized,
               p.role, c.name AS team, r.matchday, r.vote, r.fantavoto,
               r.vote_statistical, r.fantavoto_statistical, r.vote_italy,
               r.fantavoto_italy, r.goals, r.goals_conceded, r.assists,
               r.yellow_cards, r.red_cards, r.penalties_saved,
               r.penalties_missed, r.penalties_scored, r.own_goals,
               s.name AS season
        FROM player_match_ratings AS r
        JOIN players AS p ON p.id = r.player_id
        LEFT JOIN clubs AS c ON c.id = r.club_id
        JOIN seasons AS s ON s.id = r.season_id
        ORDER BY s.start_year, r.matchday, p.full_name
        """,
        conn,
    )


def load_prices(conn: sqlite3.Connection, season: str) -> pd.DataFrame:
    """Load the current quotation snapshot from the warehouse."""
    return pd.read_sql_query(
        """
        SELECT s.name AS season, p.full_name AS player,
               p.normalized_name AS player_normalized, pp.source_ref,
               c.name AS team, pp.role_classic, pp.role_mantra,
               pp.price_initial, pp.price_current, pp.fvm
        FROM player_prices AS pp
        JOIN players AS p ON p.id = pp.player_id
        LEFT JOIN clubs AS c ON c.id = pp.club_id
        JOIN seasons AS s ON s.id = pp.season_id
        WHERE s.name = ?
        ORDER BY pp.price_current DESC, p.full_name
        """,
        conn,
        params=(season_label(season),),
    )


def load_player_skill_stats(conn: sqlite3.Connection, season: str) -> pd.DataFrame:
    """Return manually imported FBref metrics as one row per player.

    Columns are prefixed with ``fbref_`` so downstream code cannot mistake
    these provider-specific measurements for Fantacalcio targets.  Only data
    placed in local manual exports is returned; this function never accesses
    FBref or another remote service.
    """
    frame = pd.read_sql_query(
        """
        SELECT p.normalized_name AS player_normalized,
               v.category || '_' || v.metric AS metric_key,
               v.value
        FROM player_season_stat_values AS v
        JOIN players AS p ON p.id = v.player_id
        JOIN seasons AS s ON s.id = v.season_id
        JOIN sources AS src ON src.id = v.source_id
        WHERE s.name = ? AND src.slug = 'fbref'
        ORDER BY v.source_file, v.id
        """,
        conn,
        params=(season_label(season),),
    )
    if frame.empty:
        return pd.DataFrame(columns=["player_normalized"])
    wide = frame.pivot_table(
        index="player_normalized", columns="metric_key", values="value", aggfunc="last"
    ).reset_index()
    wide.columns = [
        column if column == "player_normalized" else f"fbref_{column}"
        for column in wide.columns
    ]
    return wide
