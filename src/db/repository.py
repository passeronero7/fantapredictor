"""Read model inputs from the normalized SQLite research warehouse."""

from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd

from src.db.ingestors.common import season_label
from src.utils.name_matching import normalize_team_name


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


def load_player_history(
    conn: sqlite3.Connection,
    league: str = "Serie_A",
    before_season: str | int | None = None,
) -> pd.DataFrame:
    """Load player-season statistics known before ``before_season``.

    Season aggregates are only safe predictive features for a later season.
    Passing a cutoff therefore excludes the cutoff season itself as well as
    every later season.
    """
    params: tuple[object, ...] = ()
    season_filter = ""
    if before_season is not None:
        cutoff_year = int(season_label(before_season).split("/", 1)[0])
        season_filter = " AND s.start_year < ?"
        params = (cutoff_year,)
    frame = pd.read_sql_query(
        f"""
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
        WHERE src.slug = 'understat'{season_filter}
        ORDER BY p.full_name, s.start_year
        """,
        conn,
        params=params,
    )
    frame["league"] = league
    return frame


def load_votes(
    conn: sqlite3.Connection,
    season: str | int | None = None,
    through_season: str | int | None = None,
) -> pd.DataFrame:
    """Load official ratings, optionally for one season or through a season."""
    if season is not None and through_season is not None:
        raise ValueError("Use either season or through_season, not both")
    where = ""
    params: tuple[object, ...] = ()
    if season is not None:
        where = "WHERE s.name = ?"
        params = (season_label(season),)
    elif through_season is not None:
        cutoff_year = int(season_label(through_season).split("/", 1)[0])
        where = "WHERE s.start_year <= ?"
        params = (cutoff_year,)
    return pd.read_sql_query(
        f"""
        SELECT p.full_name AS player, p.normalized_name AS player_normalized,
               COALESCE(rm.role, p.role) AS role, c.name AS team, r.matchday,
               r.vote, r.fantavoto,
               r.vote_statistical, r.fantavoto_statistical, r.vote_italy,
               r.fantavoto_italy, r.goals, r.goals_conceded, r.assists,
               r.yellow_cards, r.red_cards, r.penalties_saved,
               r.penalties_missed, r.penalties_scored, r.own_goals,
               s.name AS season
        FROM player_match_ratings AS r
        JOIN players AS p ON p.id = r.player_id
        LEFT JOIN clubs AS c ON c.id = r.club_id
        JOIN seasons AS s ON s.id = r.season_id
        LEFT JOIN roster_memberships AS rm
          ON rm.player_id = r.player_id AND rm.club_id = r.club_id
         AND rm.season_id = r.season_id
        {where}
        ORDER BY s.start_year, r.matchday, p.full_name
        """,
        conn,
        params=params,
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


def load_match_context(
    conn: sqlite3.Connection,
    through_season: str | int | None = None,
    window: int = 5,
) -> pd.DataFrame:
    """Return fixture and rolling prior form for each team-match row.

    The fixture identity and home/away flag are known pre-match. Result, xG and
    points values are shifted before rolling, so the target fixture never
    contributes to its own features.
    """
    if window < 1:
        raise ValueError("Rolling match-context window must be positive")
    where = "WHERE m.matchday IS NOT NULL"
    params: tuple[object, ...] = ()
    if through_season is not None:
        cutoff_year = int(season_label(through_season).split("/", 1)[0])
        where += " AND s.start_year <= ?"
        params = (cutoff_year,)
    matches = pd.read_sql_query(
        f"""
        SELECT m.id AS match_id, s.name AS season, s.start_year,
               m.matchday, m.match_date, home.name AS home_team,
               away.name AS away_team, m.home_goals, m.away_goals,
               m.home_xg, m.away_xg, src.slug AS source
        FROM matches AS m
        JOIN seasons AS s ON s.id = m.season_id
        JOIN clubs AS home ON home.id = m.home_club_id
        JOIN clubs AS away ON away.id = m.away_club_id
        LEFT JOIN sources AS src ON src.id = m.source_id
        {where}
        ORDER BY s.start_year, m.match_date, m.id
        """,
        conn,
        params=params,
    )
    output_columns = [
        "season", "matchday", "team", "team_normalized", "opponent",
        "opponent_normalized", "is_home", "context_available",
        "team_xg_for_last5", "team_xg_against_last5", "team_points_last5",
        "opponent_xg_for_last5", "opponent_xg_against_last5",
        "opponent_points_last5",
    ]
    if matches.empty:
        return pd.DataFrame(columns=output_columns)

    # Prefer the richest row if two providers describe the same fixture.
    matches["xg_available"] = matches[["home_xg", "away_xg"]].notna().sum(axis=1)
    matches["source_priority"] = matches["source"].eq("understat").astype(int)
    matches = matches.sort_values(
        ["season", "matchday", "home_team", "away_team", "xg_available", "source_priority"],
        ascending=[True, True, True, True, False, False],
    ).drop_duplicates(["season", "matchday", "home_team", "away_team"], keep="first")

    home = pd.DataFrame({
        "match_id": matches["match_id"], "season": matches["season"],
        "start_year": matches["start_year"], "matchday": matches["matchday"],
        "match_date": matches["match_date"], "team": matches["home_team"],
        "opponent": matches["away_team"], "is_home": 1.0,
        "xg_for": matches["home_xg"], "xg_against": matches["away_xg"],
        "goals_for": matches["home_goals"], "goals_against": matches["away_goals"],
    })
    away = pd.DataFrame({
        "match_id": matches["match_id"], "season": matches["season"],
        "start_year": matches["start_year"], "matchday": matches["matchday"],
        "match_date": matches["match_date"], "team": matches["away_team"],
        "opponent": matches["home_team"], "is_home": 0.0,
        "xg_for": matches["away_xg"], "xg_against": matches["home_xg"],
        "goals_for": matches["away_goals"], "goals_against": matches["home_goals"],
    })
    context = pd.concat([home, away], ignore_index=True)
    context["team_normalized"] = context["team"].map(normalize_team_name)
    context["opponent_normalized"] = context["opponent"].map(normalize_team_name)
    goals_for = pd.to_numeric(context["goals_for"], errors="coerce")
    goals_against = pd.to_numeric(context["goals_against"], errors="coerce")
    context["points"] = np.select(
        [goals_for > goals_against, goals_for == goals_against],
        [3.0, 1.0],
        default=0.0,
    )
    context.loc[goals_for.isna() | goals_against.isna(), "points"] = np.nan
    context = context.sort_values(
        ["start_year", "team_normalized", "match_date", "matchday", "match_id"]
    ).reset_index(drop=True)

    groups = context.groupby(["season", "team_normalized"], sort=False)
    for source_column, feature_column in (
        ("xg_for", "team_xg_for_last5"),
        ("xg_against", "team_xg_against_last5"),
        ("points", "team_points_last5"),
    ):
        context[feature_column] = groups[source_column].transform(
            lambda values: values.shift(1).rolling(window, min_periods=1).mean()
        )

    opponent_form = context[
        [
            "match_id", "team_normalized", "team_xg_for_last5",
            "team_xg_against_last5", "team_points_last5",
        ]
    ].rename(columns={
        "team_normalized": "opponent_normalized",
        "team_xg_for_last5": "opponent_xg_for_last5",
        "team_xg_against_last5": "opponent_xg_against_last5",
        "team_points_last5": "opponent_points_last5",
    })
    context = context.merge(
        opponent_form, on=["match_id", "opponent_normalized"], how="left"
    )
    context["context_available"] = 1
    return context[output_columns].sort_values(
        ["season", "matchday", "team_normalized"]
    ).reset_index(drop=True)
