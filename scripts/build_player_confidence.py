#!/usr/bin/env python3
"""Build pre-season Fantacalcio confidence scorecards from bootstrap data."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config.settings import config
from src.models.confidence_model import build_confidence_scores, load_rules


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", default="2627")
    parser.add_argument(
        "--rules", type=Path,
        default=Path("config/fantacalcio_rules.example.json"),
        help="JSON file containing your league scoring rules",
    )
    parser.add_argument("--as-of-year", type=int, default=2026)
    args = parser.parse_args()

    season_dir = config.get_season_dir(args.season)
    history_path = season_dir / "historical" / "understat_open_league_history_for_roster.csv"
    output_dir = season_dir / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    rules = load_rules(args.rules)
    import pandas as pd

    scores = build_confidence_scores(pd.read_csv(history_path), rules, args.as_of_year)
    output = output_dir / "player_confidence_baseline.csv"
    scores.to_csv(output, index=False)
    print(f"Wrote {len(scores)} scorecards to {output}")
    print(f"Rules: {rules['league_name']} v{rules['version']}; generated {datetime.now(UTC).isoformat()}")


if __name__ == "__main__":
    main()
