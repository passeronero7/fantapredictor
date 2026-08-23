"""Explainable pre-season Fantacalcio confidence scores from open player history."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


ROLE_MAP = {"F": "F", "M": "M", "D": "D", "GK": "GK"}


def load_rules(path: Path) -> dict:
    """Load and minimally validate the league-scoring configuration."""
    rules = json.loads(Path(path).read_text(encoding="utf-8"))
    required = {"goal", "assist", "yellow_card", "red_card"}
    missing = required - set(rules.get("event_points", {}))
    if missing:
        raise ValueError(f"Missing event-point rules: {', '.join(sorted(missing))}")
    return rules


def _role(position: object) -> str:
    return ROLE_MAP.get(str(position), "OTHER")


def _weighted_mean(values: pd.Series, weights: pd.Series) -> float:
    valid = values.notna() & weights.notna() & (weights > 0)
    if not valid.any():
        return 0.0
    return float(np.average(values[valid], weights=weights[valid]))


def build_confidence_scores(history: pd.DataFrame, rules: dict, as_of_year: int) -> pd.DataFrame:
    """Return one transparent pre-season scorecard per player.

    The event-points projection uses xG/xA rather than realised goals/assists to
    reduce conversion noise. An empirical-Bayes prior pulls low-minute players
    toward their position's weighted average. `data_confidence` measures support
    in the available source; it is not a probability that a player will score.
    """
    required = {"id", "player", "club_2026_27", "year", "time", "xG", "xA",
                "yellow_cards", "red_cards", "primary_position"}
    missing = required - set(history.columns)
    if missing:
        raise ValueError(f"History is missing required columns: {', '.join(sorted(missing))}")

    params = rules["model"]
    data = history.copy()
    data["role"] = data["primary_position"].map(_role)
    data = data[data["role"] != "OTHER"].copy()
    data["time"] = pd.to_numeric(data["time"], errors="coerce").fillna(0.0)
    for column in ("xG", "xA", "yellow_cards", "red_cards"):
        data[column] = pd.to_numeric(data[column], errors="coerce").fillna(0.0)

    oldest_year = as_of_year - int(params["max_history_seasons"]) + 1
    data = data[data["year"] >= oldest_year].copy()
    data["recency_weight"] = 0.5 ** ((as_of_year - data["year"]) / params["season_half_life_years"])
    points = rules["event_points"]
    data["expected_event_points"] = (
        data["xG"] * points["goal"]
        + data["xA"] * points["assist"]
        + data["yellow_cards"] * points["yellow_card"]
        + data["red_cards"] * points["red_card"]
    )
    data["weighted_minutes"] = data["time"] * data["recency_weight"]
    data["weighted_points"] = data["expected_event_points"] * data["recency_weight"]

    group_columns = ["club_2026_27", "player", "role"]
    player = data.groupby(group_columns, as_index=False).agg(
        history_id_count=("id", "nunique"),
        history_rows=("year", "size"),
        first_history_year=("year", "min"),
        latest_history_year=("year", "max"),
        history_minutes=("time", "sum"),
        weighted_minutes=("weighted_minutes", "sum"),
        weighted_points=("weighted_points", "sum"),
    )
    player["raw_expected_event_points_per90"] = np.where(
        player["weighted_minutes"] > 0,
        90 * player["weighted_points"] / player["weighted_minutes"],
        0.0,
    )

    role_prior = player.groupby("role").apply(
        lambda frame: _weighted_mean(
            frame["raw_expected_event_points_per90"], frame["weighted_minutes"]
        ),
        include_groups=False,
    ).rename("role_prior_points_per90")
    player = player.join(role_prior, on="role")
    player["shrinkage_weight"] = player["weighted_minutes"] / (
        player["weighted_minutes"] + float(params["prior_minutes"])
    )
    player["projected_event_points_per90"] = (
        player["shrinkage_weight"] * player["raw_expected_event_points_per90"]
        + (1 - player["shrinkage_weight"]) * player["role_prior_points_per90"]
    )

    max_year_gap = (as_of_year - player["latest_history_year"]).clip(lower=0)
    recency = 0.5 ** (max_year_gap / params["season_half_life_years"])
    volume = player["weighted_minutes"] / (player["weighted_minutes"] + float(params["prior_minutes"]))
    depth = (player["history_rows"] / 3).clip(upper=1)
    player["data_confidence"] = (100 * (0.60 * volume + 0.25 * recency + 0.15 * depth)).round(1)
    player["identity_status"] = np.where(
        player["history_id_count"] > 1, "manual_review_required", "resolved_by_name"
    )
    player.loc[player["history_id_count"] > 1, "data_confidence"] *= 0.8
    player["data_confidence"] = player["data_confidence"].round(1)
    player["data_confidence_band"] = pd.cut(
        player["data_confidence"], [-1, 35, 60, 80, 100],
        labels=["very_low", "low", "medium", "high"],
    ).astype(str)
    player["role_percentile"] = (
        player.groupby("role")["projected_event_points_per90"].rank(pct=True) * 100
    ).round(1)
    player["selection_score"] = (
        0.65 * player["role_percentile"] + 0.35 * player["data_confidence"]
    ).round(1)
    player["model_scope"] = "event_points_only"
    goalkeeper_rows = player["role"] == "GK"
    player.loc[goalkeeper_rows, [
        "projected_event_points_per90", "role_percentile", "selection_score"
    ]] = np.nan
    player.loc[goalkeeper_rows, "model_scope"] = "insufficient_goalkeeper_event_coverage"
    return player.sort_values(["selection_score", "data_confidence"], ascending=False, na_position="last").reset_index(drop=True)
