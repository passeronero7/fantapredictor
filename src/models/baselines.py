"""Baseline predictions: the honest fallback while the SHASH model fails its gate.

The walk-forward evaluation record shows the global-median and expanding-prior
baselines beating the neural model on every aggregate metric. Until a model
wins on disjoint held-out windows, production predictions come from these
transparent statistics: a player's own observed fantavoto distribution when
there is enough history, otherwise the role-level distribution.
"""

from __future__ import annotations

import sqlite3

import pandas as pd

from src.db import repository
from src.db.ingestors.common import season_label
from src.utils.name_matching import normalize_name

PREDICTION_SOURCE = "global_median_baseline"
MIN_PLAYER_OBSERVATIONS = 3
QUANTILE_LEVELS = [0.10, 0.50, 0.90]
QUANTILE_COLUMNS = ["floor_q10", "median_q50", "ceiling_q90"]


def prior_ratings(
    ratings: pd.DataFrame,
    season: str,
    matchday: int,
) -> pd.DataFrame:
    """Ratings observable before ``matchday`` of ``season``.

    Only ratings from seasons strictly before ``season`` and from the current
    season's matchdays strictly below ``matchday`` are kept, so the target
    matchday can never leak into its own prediction.
    """
    observed = ratings.dropna(subset=["fantavoto"]).copy()
    current = observed["season"].astype(str).eq(season)
    matchdays = pd.to_numeric(observed["matchday"], errors="coerce")
    return observed[~current | (current & (matchdays < matchday))]


def role_quantiles(ratings: pd.DataFrame) -> pd.DataFrame:
    """Return per-role fantavoto q10/q50/q90 from observed ratings."""
    observed = ratings.dropna(subset=["fantavoto"])
    if observed.empty:
        raise ValueError("No observed fantavoto ratings are available for baselines")
    quantiles = observed.groupby("role")["fantavoto"].quantile(QUANTILE_LEVELS).unstack()
    quantiles.columns = QUANTILE_COLUMNS
    return quantiles


def compute_baseline_predictions(
    ratings: pd.DataFrame,
    roster: pd.DataFrame,
    season: str,
    matchday: int,
) -> pd.DataFrame:
    """Build baseline q10/q50/q90 predictions for the confirmed roster.

    Players with at least ``MIN_PLAYER_OBSERVATIONS`` observable fantavoto
    values get their own quantiles; everyone else falls back to the role
    distribution.
    """
    if "status" not in roster.columns:
        raise ValueError("Roster frame must carry a status column")
    roster = roster[roster["status"].astype(str).str.strip().eq("confirmed")].copy()
    if "player_normalized" not in roster.columns:
        roster["player_normalized"] = roster["player"].map(normalize_name)

    prior = prior_ratings(ratings, season, matchday)
    quantiles = role_quantiles(prior)
    prior_quantiles = prior.groupby("player_normalized")["fantavoto"].quantile(
        QUANTILE_LEVELS
    ).unstack()
    prior_counts = prior.groupby("player_normalized")["fantavoto"].size()

    output = roster[["player", "player_normalized", "club_2026_27", "role"]].copy()
    output = output.rename(columns={"club_2026_27": "team"})
    values: dict[str, list[float]] = {column: [] for column in QUANTILE_COLUMNS}
    sources: list[str] = []
    for _, row in output.iterrows():
        key = str(row["player_normalized"])
        role = str(row["role"]).strip().upper()
        if prior_counts.get(key, 0) >= MIN_PLAYER_OBSERVATIONS and key in prior_quantiles.index:
            q = prior_quantiles.loc[key, QUANTILE_LEVELS].to_numpy(dtype=float)
            sources.append("expanding_prior_baseline")
        else:
            if role not in quantiles.index:
                raise ValueError(f"No observed fantavoto ratings for role {role!r}")
            q = quantiles.loc[role, QUANTILE_COLUMNS].to_numpy(dtype=float)
            sources.append(PREDICTION_SOURCE)
        values["floor_q10"].append(q[0])
        values["median_q50"].append(q[1])
        values["ceiling_q90"].append(q[2])
    for column, column_values in values.items():
        output[column] = column_values
    output["prediction_source"] = sources
    return output.round(3)


def build_baseline_predictions(
    conn: sqlite3.Connection,
    season: str,
    matchday: int,
) -> pd.DataFrame:
    """Load warehouse data and return baseline predictions for ``matchday``."""
    votes = repository.load_votes(conn, through_season=season)
    roster = repository.load_rosters(conn, season)
    return compute_baseline_predictions(
        votes, roster, season_label(season), matchday
    )
