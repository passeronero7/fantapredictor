#!/usr/bin/env python3
"""Rank current classic defenders by recent production and auction value."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.utils.name_matching import normalize_name


def _surname_initial(name: str) -> tuple[str, str]:
    tokens = re.findall(r"[a-z]+", normalize_name(name))
    return (tokens[-1], tokens[0][0]) if tokens else ("", "")


def _match_stats(price_name: str, stats: pd.DataFrame) -> pd.Series | None:
    normalized = normalize_name(price_name)
    exact = stats[stats["normalized_name"] == normalized]
    if len(exact) == 1:
        return exact.iloc[0]
    surname, initial = _surname_initial(price_name)
    candidates = stats[stats["normalized_name"].map(lambda value: _surname_initial(value)[0] == surname)]
    initial_candidates = candidates[
        candidates["normalized_name"].map(lambda value: _surname_initial(value)[1] == initial)
    ]
    if len(initial_candidates) == 1:
        return initial_candidates.iloc[0]
    if len(candidates) == 1:
        return candidates.iloc[0]
    return None


def analyze(prices_path: str | Path, understat_path: str | Path, recent_seasons: int = 3) -> pd.DataFrame:
    """Return a reproducible defender value table."""
    prices = pd.read_csv(prices_path)
    prices = prices[prices["role_classic"].eq("D")].copy()
    history = pd.read_csv(understat_path)
    history = history[history["league"].eq("Serie_A")].copy()
    history["year"] = pd.to_numeric(history["year"], errors="coerce")
    latest_year = int(history["year"].max())
    history = history[history["year"] >= latest_year - recent_seasons + 1]
    history = history[history["primary_position"].eq("D")].copy()
    for column in ("time", "xG", "xA", "goals", "assists", "games"):
        history[column] = pd.to_numeric(history[column], errors="coerce").fillna(0.0)
    history["normalized_name"] = history["player_name"].map(normalize_name)
    stats = history.groupby("normalized_name", as_index=False).agg(
        matched_name=("player_name", "first"),
        minutes=("time", "sum"),
        games=("games", "sum"),
        xg=("xG", "sum"),
        xa=("xA", "sum"),
        goals=("goals", "sum"),
        assists=("assists", "sum"),
        seasons=("year", "nunique"),
    )
    stats["xgi_per90"] = 90 * (stats["xg"] + stats["xa"]) / (stats["minutes"] + 450)
    stats["goal_involvement_per90"] = 90 * (stats["goals"] + stats["assists"]) / (stats["minutes"] + 450)
    stats["availability"] = (stats["minutes"] / (latest_year - (latest_year - recent_seasons + 1) + 1) / 900).clip(upper=1)

    records = []
    for row in prices.to_dict("records"):
        matched = _match_stats(row["player"], stats)
        if matched is None:
            continue
        record = row.copy()
        record.update(matched.to_dict())
        records.append(record)
    result = pd.DataFrame(records)
    if result.empty:
        return result
    for column in ("xgi_per90", "goal_involvement_per90", "availability"):
        result[f"{column}_percentile"] = result[column].rank(pct=True) * 100
    result["production_score"] = (
        0.55 * result["xgi_per90_percentile"]
        + 0.25 * result["goal_involvement_per90_percentile"]
        + 0.20 * result["availability_percentile"]
    )
    result["value_score"] = result["production_score"] / result["price_current"].clip(lower=1)
    production_cutoff = result["production_score"].quantile(0.75)
    result["value_label"] = "fair_or_premium"
    # A value label requires both a non-premium price and strong production:
    # cheap players with weak evidence are not automatically bargains.
    result.loc[
        (result["price_current"] <= 8) & (result["production_score"] >= production_cutoff),
        "value_label",
    ] = "undervalued"
    return result.sort_values(["production_score", "value_score"], ascending=False).reset_index(drop=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prices", type=Path, default=ROOT / "data/season_2026_27/fantacalcio/prices.csv")
    parser.add_argument("--understat", type=Path, default=ROOT / "data/season_2026_27/raw/understat_players_aggregated_2014_td.csv")
    parser.add_argument("--output", type=Path, default=ROOT / "data/season_2026_27/outputs/defender_auction_analysis.csv")
    args = parser.parse_args()
    result = analyze(args.prices, args.understat)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(args.output, index=False)
    columns = ["player", "team", "price_current", "matched_name", "minutes", "goals", "assists", "xg", "xa", "production_score", "value_score", "value_label"]
    print(result[columns].head(10).to_string(index=False))
    print(f"Saved {len(result)} evidenced defenders to {args.output}")


if __name__ == "__main__":
    main()
