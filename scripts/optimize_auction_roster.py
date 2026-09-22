#!/usr/bin/env python3
"""Build a complete 25-player auction roster from simulated forecasts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.models.auction_optimizer import AuctionOptimizationConfig, optimize_auction_roster
from src.utils.name_matching import normalize_name


def build_pool(forecast_path: Path, dossier_path: Path, defence_modifier: bool) -> pd.DataFrame:
    forecast = pd.read_csv(forecast_path)
    dossier = pd.read_csv(dossier_path)
    forecast["join_key"] = forecast["player"].map(normalize_name)
    dossier["join_key"] = dossier["player"].map(normalize_name)
    cost_column = (
        "riferimento_con_modificatore"
        if defence_modifier else "riferimento_senza_modificatore"
    )
    if cost_column not in dossier:
        raise ValueError(f"Dossier is missing {cost_column}")
    detail_columns = [
        "join_key", cost_column, "soglia_prudente", "soglia_estesa",
        "rischio_disponibilita", "kind", "note",
    ]
    costs = dossier[[column for column in detail_columns if column in dossier]]
    if costs["join_key"].duplicated().any():
        raise ValueError("Dossier contains duplicate normalized player names")
    pool = forecast.merge(costs, on="join_key", how="inner", validate="one_to_one")
    pool["auction_cost"] = pd.to_numeric(pool[cost_column], errors="coerce").round().clip(lower=1)
    risk = pool.get("rischio_disponibilita", pd.Series(False, index=pool.index)).fillna(False)
    notes = pool.get("note", pd.Series("", index=pool.index)).fillna("").astype(str).str.lower()
    severe = notes.str.contains(
        r"lungo stop|operat|novembre|dicembre|gennaio|frattur|crociato|ernia",
        regex=True,
    )
    pool["availability_factor"] = 1.0
    pool.loc[risk, "availability_factor"] = 0.75
    pool.loc[risk & severe, "availability_factor"] = 0.35
    return pool.drop(columns="join_key")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--forecast", type=Path, required=True)
    parser.add_argument("--dossier-players", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--budget", type=int, default=500)
    parser.add_argument("--defence-modifier", action="store_true")
    args = parser.parse_args()

    pool = build_pool(args.forecast, args.dossier_players, args.defence_modifier)
    result = optimize_auction_roster(
        pool,
        AuctionOptimizationConfig(
            budget=args.budget,
            defence_modifier=args.defence_modifier,
        ),
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    scenario = "con_modificatore" if args.defence_modifier else "senza_modificatore"
    roster_path = args.output_dir / f"rosa_ideale_{scenario}.csv"
    result["roster"].to_csv(roster_path, index=False)
    summary = {key: value for key, value in result.items() if key != "roster"}
    summary.update({
        "scenario": scenario,
        "players": int(len(result["roster"])),
        "role_counts": result["roster"].groupby("role").size().to_dict(),
        "forecast": str(args.forecast),
        "dossier_players": str(args.dossier_players),
        "cost_model": "rounded FVM role-market reference; not a clearing-price forecast",
        "availability_policy": "0.75 for a current notice; 0.35 for explicit long-stop language",
    })
    if args.defence_modifier:
        summary["defence_modifier_rule"] = {
            "average_of": "goalkeeper + best 3 defenders",
            "strict_thresholds": {">6.5": 1, ">7.0": 3},
        }
    summary_path = args.output_dir / f"rosa_ideale_{scenario}.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print(roster_path)


if __name__ == "__main__":
    main()
