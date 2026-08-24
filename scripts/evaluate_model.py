#!/usr/bin/env python3
"""Evaluate the probabilistic model on a chronological held-out matchday range."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config.settings import config
from src.data_processing.match_data_builder import MatchDataBuilder
from src.models.evaluation import score_predictions
from src.models.neural_network import FantacalcioPredictor


def evaluate(season: str, cutoff_matchday: int, epochs: int = 25) -> dict[str, object]:
    """Train before ``cutoff_matchday`` and score the remaining matchdays."""
    datasets = MatchDataBuilder(season=season).build_complete_dataset()
    train_outfield = datasets["outfield"].query("matchday < @cutoff_matchday")
    test_outfield = datasets["outfield"].query("matchday >= @cutoff_matchday")
    train_goalkeepers = datasets["goalkeepers"].query("matchday < @cutoff_matchday")
    test_goalkeepers = datasets["goalkeepers"].query("matchday >= @cutoff_matchday")
    if test_outfield.empty and test_goalkeepers.empty:
        raise ValueError("The cutoff leaves no held-out matchdays")

    predictor = FantacalcioPredictor(season=season)
    predictor.train(train_outfield, train_goalkeepers, epochs=epochs)
    predictions = []
    if not test_outfield.empty:
        predictions.append(predictor.predict_matchday(cutoff_matchday, train_test_frame(test_outfield, False)))
    if not test_goalkeepers.empty:
        predictions.append(predictor.predict_matchday(cutoff_matchday, train_test_frame(test_goalkeepers, True)))
    prediction_frame = pd.concat(predictions, ignore_index=True)
    train_frame = pd.concat([train_outfield, train_goalkeepers], ignore_index=True)
    baseline = prediction_frame.copy()
    vote_median = train_frame["target_vote"].median()
    fantasy_median = train_frame["target_fantavoto"].median()
    baseline["predicted_vote"] = vote_median
    baseline["predicted_fantavoto"] = fantasy_median
    baseline["floor_q10"] = train_frame["target_fantavoto"].quantile(0.10)
    baseline["median_q50"] = fantasy_median
    baseline["ceiling_q90"] = train_frame["target_fantavoto"].quantile(0.90)
    prior_baseline = prediction_frame.copy()
    prior_vote = pd.to_numeric(prior_baseline.get("mean_vote"), errors="coerce").fillna(vote_median)
    prior_fantasy = pd.to_numeric(
        prior_baseline.get("mean_fantavoto"), errors="coerce"
    ).fillna(fantasy_median)
    train_prior = pd.to_numeric(train_frame.get("mean_fantavoto"), errors="coerce")
    train_prior = train_prior.fillna(fantasy_median)
    residuals = train_frame["target_fantavoto"] - train_prior
    prior_baseline["predicted_vote"] = prior_vote
    prior_baseline["predicted_fantavoto"] = prior_fantasy
    prior_baseline["floor_q10"] = prior_fantasy + residuals.quantile(0.10)
    prior_baseline["median_q50"] = prior_fantasy + residuals.quantile(0.50)
    prior_baseline["ceiling_q90"] = prior_fantasy + residuals.quantile(0.90)
    result: dict[str, object] = {
        "season": season,
        "cutoff_matchday": cutoff_matchday,
        "train_rows": int(len(train_outfield) + len(train_goalkeepers)),
        "test_rows": int(len(prediction_frame)),
        "overall": score_predictions(prediction_frame),
        "baseline": score_predictions(baseline),
        "expanding_prior_baseline": score_predictions(prior_baseline),
    }
    if "role" in prediction_frame.columns:
        result["by_role"] = {
            str(role): score_predictions(frame)
            for role, frame in prediction_frame.groupby("role")
            if len(frame) > 0
        }
    return result


def train_test_frame(frame, goalkeeper: bool):
    """Return a prediction frame with the role expected by the model."""
    result = frame.copy()
    if "role" not in result.columns:
        result["role"] = "P" if goalkeeper else "C"
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", default="2425")
    parser.add_argument("--cutoff-matchday", type=int, default=20)
    parser.add_argument("--epochs", type=int, default=25)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = evaluate(args.season, args.cutoff_matchday, args.epochs)
    output = args.output or config.get_season_dir(args.season) / "reports" / "model_evaluation.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    print(f"Saved evaluation to {output}")


if __name__ == "__main__":
    main()
