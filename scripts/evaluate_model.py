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


def evaluate(
    season: str,
    cutoff_matchday: int,
    epochs: int = 25,
    end_matchday: int | None = None,
    datasets: dict[str, pd.DataFrame] | None = None,
    return_frames: bool = False,
) -> dict[str, object] | tuple[dict[str, object], dict[str, pd.DataFrame]]:
    """Train before a cutoff and score one non-overlapping matchday window."""
    datasets = datasets or MatchDataBuilder(season=season).build_complete_dataset()
    train_outfield = datasets["outfield"].query("matchday < @cutoff_matchday")
    test_outfield = datasets["outfield"].query("matchday >= @cutoff_matchday")
    train_goalkeepers = datasets["goalkeepers"].query("matchday < @cutoff_matchday")
    test_goalkeepers = datasets["goalkeepers"].query("matchday >= @cutoff_matchday")
    if end_matchday is not None:
        test_outfield = test_outfield.query("matchday < @end_matchday")
        test_goalkeepers = test_goalkeepers.query("matchday < @end_matchday")
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
        "end_matchday_exclusive": end_matchday,
        "train_rows": int(len(train_outfield) + len(train_goalkeepers)),
        "test_rows": int(len(prediction_frame)),
        "overall": score_predictions(prediction_frame),
        "baseline": score_predictions(baseline),
        "expanding_prior_baseline": score_predictions(prior_baseline),
    }
    result.update(breakdowns(prediction_frame))
    if return_frames:
        return result, {
            "model": prediction_frame,
            "baseline": baseline,
            "expanding_prior_baseline": prior_baseline,
        }
    return result


def breakdowns(predictions: pd.DataFrame) -> dict[str, object]:
    """Score useful diagnostic cohorts without changing the overall sample."""
    result: dict[str, object] = {}
    if "role" in predictions.columns:
        result["by_role"] = score_groups(predictions, "role")
    if "team" in predictions.columns:
        result["by_club"] = score_groups(predictions, "team")
    if "hist_minutes" in predictions.columns:
        with_buckets = predictions.copy()
        minutes = pd.to_numeric(with_buckets["hist_minutes"], errors="coerce").fillna(0)
        with_buckets["minutes_bucket"] = pd.cut(
            minutes,
            bins=[-1, 0, 900, 2700, float("inf")],
            labels=["none", "low_1_900", "medium_901_2700", "high_2701_plus"],
        )
        result["by_historical_minutes"] = score_groups(
            with_buckets, "minutes_bucket"
        )
    return result


def score_groups(frame: pd.DataFrame, column: str) -> dict[str, object]:
    """Score every non-empty value of a grouping column."""
    return {
        str(value): score_predictions(group)
        for value, group in frame.dropna(subset=[column]).groupby(column, observed=True)
        if not group.empty
    }


def evaluate_walk_forward(
    season: str,
    cutoffs: list[int],
    epochs: int = 25,
) -> dict[str, object]:
    """Evaluate expanding training windows on disjoint future windows."""
    cutoffs = sorted(set(cutoffs))
    if not cutoffs or cutoffs[0] < 2:
        raise ValueError("Walk-forward cutoffs must contain matchdays >= 2")
    datasets = MatchDataBuilder(season=season).build_complete_dataset()
    all_rows = pd.concat(datasets.values(), ignore_index=True)
    final_end = int(all_rows["matchday"].max()) + 1
    windows = []
    frames: dict[str, list[pd.DataFrame]] = {
        "model": [], "baseline": [], "expanding_prior_baseline": []
    }
    for index, cutoff in enumerate(cutoffs):
        end = cutoffs[index + 1] if index + 1 < len(cutoffs) else final_end
        if cutoff >= final_end or cutoff >= end:
            raise ValueError(f"Invalid walk-forward window: {cutoff}..{end}")
        split, split_frames = evaluate(
            season,
            cutoff,
            epochs=epochs,
            end_matchday=end,
            datasets=datasets,
            return_frames=True,
        )
        windows.append(split)
        for key in frames:
            frames[key].append(split_frames[key])

    combined = {
        key: pd.concat(parts, ignore_index=True) for key, parts in frames.items()
    }
    result: dict[str, object] = {
        "season": season,
        "method": "expanding_walk_forward",
        "cutoffs": cutoffs,
        "epochs": epochs,
        "test_rows": int(len(combined["model"])),
        "overall": score_predictions(combined["model"]),
        "baseline": score_predictions(combined["baseline"]),
        "expanding_prior_baseline": score_predictions(
            combined["expanding_prior_baseline"]
        ),
        "windows": windows,
    }
    result.update(breakdowns(combined["model"]))
    return result


def parse_cutoffs(value: str) -> list[int]:
    """Parse and validate a comma-separated cutoff list."""
    try:
        cutoffs = [int(part.strip()) for part in value.split(",") if part.strip()]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Cutoffs must be comma-separated integers") from exc
    if not cutoffs:
        raise argparse.ArgumentTypeError("At least one cutoff is required")
    return cutoffs


def train_test_frame(frame, goalkeeper: bool):
    """Return a prediction frame with the role expected by the model."""
    result = frame.copy()
    if "role" not in result.columns:
        result["role"] = "P" if goalkeeper else "C"
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", default="2425")
    parser.add_argument("--cutoff-matchday", type=int)
    parser.add_argument(
        "--cutoffs",
        type=parse_cutoffs,
        default=parse_cutoffs("10,20,30"),
        help="Comma-separated expanding walk-forward cutoffs (default: 10,20,30)",
    )
    parser.add_argument("--epochs", type=int, default=25)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.cutoff_matchday is not None:
        result = evaluate(args.season, args.cutoff_matchday, args.epochs)
        default_name = "model_evaluation.json"
    else:
        result = evaluate_walk_forward(args.season, args.cutoffs, args.epochs)
        default_name = "model_walk_forward_evaluation.json"
    output = args.output or config.get_season_dir(args.season) / "reports" / default_name
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    print(f"Saved evaluation to {output}")


if __name__ == "__main__":
    main()
