"""Metrics for chronological fantasy-score prediction evaluation."""

from __future__ import annotations

import math

import pandas as pd


def score_predictions(predictions: pd.DataFrame) -> dict[str, float | int]:
    """Score observed targets against point and interval predictions.

    The input must contain observed ``target_*`` columns and the predictor's
    point estimates plus q10/q50/q90 fantasy-score columns.
    """
    required = {
        "target_vote", "target_fantavoto", "predicted_vote", "predicted_fantavoto",
        "floor_q10", "median_q50", "ceiling_q90",
    }
    missing = required - set(predictions.columns)
    if missing:
        raise ValueError(f"Predictions are missing columns: {', '.join(sorted(missing))}")
    frame = predictions[list(required)].apply(pd.to_numeric, errors="coerce").dropna()
    if frame.empty:
        raise ValueError("No numeric observed targets and predictions are available")
    if (frame["floor_q10"] > frame["median_q50"]).any() or (
        frame["median_q50"] > frame["ceiling_q90"]
    ).any():
        raise ValueError("Fantasy-score quantiles must be ordered q10 <= q50 <= q90")

    actual = frame["target_fantavoto"]
    point = frame["predicted_fantavoto"]
    lower = frame["floor_q10"]
    upper = frame["ceiling_q90"]
    return {
        "n": int(len(frame)),
        "vote_mae": float((frame["target_vote"] - frame["predicted_vote"]).abs().mean()),
        "fantavoto_mae": float((actual - point).abs().mean()),
        "fantavoto_rmse": float(math.sqrt(((actual - point) ** 2).mean())),
        "fantavoto_q10_coverage": float((actual >= lower).mean()),
        "fantavoto_q50_coverage": float((actual <= frame["median_q50"]).mean()),
        "fantavoto_q90_coverage": float((actual <= upper).mean()),
        "fantavoto_interval_coverage": float(((actual >= lower) & (actual <= upper)).mean()),
        "fantavoto_interval_width": float((upper - lower).mean()),
    }
