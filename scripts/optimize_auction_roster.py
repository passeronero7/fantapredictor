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


def build_pool(
    forecast_path: Path, dossier_path: Path, defence_modifier: bool,
) -> tuple[pd.DataFrame, dict[str, object]]:
    forecast = pd.read_csv(forecast_path)
    dossier = pd.read_csv(dossier_path)
    # Join on the warehouse's own identity key (players.normalized_name via
    # player_id), not a second, independently re-derived normalization of the
    # exported display text: the two CSVs can spell the same player
    # differently (accents, suffixes, homonyms such as "Kamara H.") and a
    # text-only key silently drops or miscollides those rows.
    for name, side in (("forecast", forecast), ("dossier", dossier)):
        if "player_normalized" not in side:
            raise ValueError(f"{name} is missing player_normalized")
    cost_column = (
        "riferimento_con_modificatore"
        if defence_modifier else "riferimento_senza_modificatore"
    )
    if cost_column not in dossier:
        raise ValueError(f"Dossier is missing {cost_column}")
    dup_forecast = forecast["player_normalized"][forecast["player_normalized"].duplicated()]
    if not dup_forecast.empty:
        raise ValueError(f"Forecast has duplicate identities: {sorted(set(dup_forecast))}")
    dup_dossier = dossier["player_normalized"][dossier["player_normalized"].duplicated()]
    if not dup_dossier.empty:
        raise ValueError(f"Dossier has duplicate identities: {sorted(set(dup_dossier))}")

    detail_columns = [
        "player_normalized", cost_column, "soglia_prudente", "soglia_estesa",
        "rischio_disponibilita", "kind", "note",
    ]
    costs = dossier[[column for column in detail_columns if column in dossier]]
    pool = forecast.merge(costs, on="player_normalized", how="outer", indicator=True)
    unmatched_forecast = sorted(pool.loc[pool["_merge"].eq("left_only"), "player_normalized"])
    unmatched_dossier = sorted(pool.loc[pool["_merge"].eq("right_only"), "player_normalized"])
    pool = pool[pool["_merge"].eq("both")].drop(columns="_merge").copy()

    pool["auction_cost"] = pd.to_numeric(pool[cost_column], errors="coerce").round().clip(lower=1)
    risk = pool.get("rischio_disponibilita", pd.Series(False, index=pool.index)).fillna(False)
    # The propensity forecast already discounts p_plays proportionally by
    # expected return date for players with a structured availability row
    # (see simulate_auction_propensity.py). Applying this note-derived factor
    # on top of that for the same player would double-count the same injury.
    structured = pool.get(
        "availability_structured", pd.Series(False, index=pool.index)
    ).fillna(False)
    notes = pool.get("note", pd.Series("", index=pool.index)).fillna("").astype(str).str.lower()
    severe = notes.str.contains(
        r"lungo stop|operat|novembre|dicembre|gennaio|frattur|crociato|ernia",
        regex=True,
    )
    heuristic_risk = risk & ~structured
    pool["availability_factor"] = 1.0
    pool.loc[heuristic_risk, "availability_factor"] = 0.75
    pool.loc[heuristic_risk & severe, "availability_factor"] = 0.35
    match_report = {
        "matched": int(len(pool)),
        "unmatched_forecast": unmatched_forecast,
        "unmatched_dossier": unmatched_dossier,
    }
    return pool, match_report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--forecast", type=Path, required=True)
    parser.add_argument("--dossier-players", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--budget", type=int, default=500)
    parser.add_argument("--reserve", type=int, default=0,
                         help="Credits to keep unspent (e.g. 1 per still-open slot)")
    parser.add_argument("--defence-modifier", action="store_true")
    args = parser.parse_args()

    pool, match_report = build_pool(args.forecast, args.dossier_players, args.defence_modifier)
    if match_report["unmatched_forecast"] or match_report["unmatched_dossier"]:
        print(
            f"identity join: {match_report['matched']} matched, "
            f"{len(match_report['unmatched_forecast'])} forecast-only, "
            f"{len(match_report['unmatched_dossier'])} dossier-only "
            "(see match_report in the summary JSON)"
        )
    result = optimize_auction_roster(
        pool,
        AuctionOptimizationConfig(
            budget=args.budget,
            reserve=args.reserve,
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
        "availability_policy": (
            "structured expected-return discount from the forecast where available; "
            "otherwise 0.75 for a current notice, 0.35 for explicit long-stop language"
        ),
        "match_report": match_report,
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
