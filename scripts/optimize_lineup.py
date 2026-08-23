#!/usr/bin/env python3
"""Optimize a legal Fantacalcio lineup from a prediction artifact."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config.settings import config
from src.models.lineup_optimizer import LineupOptimizer


def optimize(
    predictions_path: str | Path,
    budget: float = 500.0,
    formation: str = "3-4-3",
    strategy: str = "expected_value",
    simulations: int = 1000,
) -> dict[str, object]:
    """Return a JSON-serializable optimized lineup result."""
    predictions_path = Path(predictions_path)
    if predictions_path.suffix.lower() in {".xlsx", ".xls"}:
        predictions = pd.read_excel(predictions_path, index_col=0)
    else:
        predictions = pd.read_csv(predictions_path)
    result = LineupOptimizer(
        predictions,
        budget=budget,
        formation=formation,
        simulations=simulations,
    ).get_optimal_lineup(strategy=strategy)
    result["starters"] = result["starters"].to_dict("records")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", default="2627")
    parser.add_argument("--matchday", type=int, required=True)
    parser.add_argument("--predictions", type=Path)
    parser.add_argument("--budget", type=float, default=config.DEFAULT_BUDGET)
    parser.add_argument("--formation", default=config.DEFAULT_FORMATION)
    parser.add_argument(
        "--strategy", choices=("expected_value", "ceiling", "floor"), default="expected_value"
    )
    parser.add_argument("--simulations", type=int, default=1000)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    predictions = args.predictions or (
        config.get_season_dir(args.season) / "outputs" / f"pred_matchday_{args.matchday}.xlsx"
    )
    result = optimize(
        predictions,
        budget=args.budget,
        formation=args.formation,
        strategy=args.strategy,
        simulations=args.simulations,
    )
    output = args.output or (
        config.get_season_dir(args.season) / "outputs" / f"lineup_matchday_{args.matchday}.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"Saved lineup to {output}")


if __name__ == "__main__":
    main()
