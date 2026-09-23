#!/usr/bin/env python3
"""Build a complete 25-player auction roster from simulated forecasts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.models.auction_optimizer import (
    AuctionOptimizationConfig,
    alternative_rosters,
    selection_robustness,
)


VOTE_PRIOR_WEIGHT = 6.0  # matchdays of prior evidence, as in the archetype blend


def expected_vote(dossier: pd.DataFrame) -> pd.Series:
    """Shrunk expected match vote for the defence-modifier premium.

    Current-season mean vote, shrunk towards last season's mean (or the
    role's current mean when last season is thin) with VOTE_PRIOR_WEIGHT
    matchdays of prior weight: four matchdays alone are too noisy.
    """
    def column(name: str) -> pd.Series:
        return pd.to_numeric(dossier.get(name, pd.Series(np.nan, index=dossier.index)),
                             errors="coerce")

    current = column("media_voto")
    n = column("presenze_voto").fillna(0)
    last = column("mv_2526")
    last_n = column("presenze_2526").fillna(0)
    role_mean = (current.groupby(dossier["role"]).transform("mean")
                 if "role" in dossier else pd.Series(current.mean(), index=dossier.index))
    prior = last.where(last_n >= 5, role_mean).fillna(role_mean)
    return ((current.fillna(0) * n + prior * VOTE_PRIOR_WEIGHT) / (n + VOTE_PRIOR_WEIGHT)).round(3)


def build_pool(
    forecast_path: Path, dossier_path: Path, defence_modifier: bool,
    quotation_floor: float = 0.0,
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

    dossier["expected_vote"] = expected_vote(dossier)
    detail_columns = [
        "player_normalized", "source_ref", cost_column, "quotazione", "soglia_prudente", "soglia_estesa",
        "rischio_disponibilita", "kind", "note", "expected_vote",
    ]
    costs = dossier[[column for column in detail_columns if column in dossier]]
    pool = forecast.merge(costs, on="player_normalized", how="outer", indicator=True)
    unmatched_forecast = sorted(pool.loc[pool["_merge"].eq("left_only"), "player_normalized"])
    unmatched_dossier = sorted(pool.loc[pool["_merge"].eq("right_only"), "player_normalized"])
    pool = pool[pool["_merge"].eq("both")].drop(columns="_merge").copy()

    reference = pd.to_numeric(pool[cost_column], errors="coerce").round().clip(lower=1)
    # The FVM reference prices only the top managers x slots players per role
    # and puts everyone else at 1, so a quotation-8 player just outside that
    # pool looks eight times cheaper than one just inside it. The public
    # quotation is visible to every manager; at the pool boundary the
    # reference is ~0.9-1.4x quotation, so floor = quotation_floor x quotation.
    quotation = pd.to_numeric(
        pool.get("quotazione", pd.Series(np.nan, index=pool.index)), errors="coerce")
    floor = (quotation_floor * quotation).round()
    pool["auction_cost"] = np.maximum(reference, floor.fillna(1)).clip(lower=1)
    pool["cost_floor_applied"] = pool["auction_cost"] > reference
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


def calibrate_modifier(db_path: Path, season: str) -> dict[str, float]:
    from src.db import database, repository
    from src.models.defence_modifier import calibrate, lineup_averages

    conn = database.get_connection(db_path)
    try:
        votes = repository.load_votes(conn, season=season)
    finally:
        conn.close()
    result = calibrate(lineup_averages(votes)).as_dict()
    result["season"] = season
    return result


def role_budget_deviation(spend: dict[str, int], dossier_path: Path, scenario: str) -> dict | None:
    """Compare optimizer spend with the dossier's planned role budgets."""
    settings_path = dossier_path.parent / "impostazioni_e_limiti.json"
    if not settings_path.exists():
        return None
    budgets = json.loads(settings_path.read_text()).get("role_budgets", {}).get(scenario)
    if not budgets:
        return None
    return {
        role: {"planned": budgets[role], "optimizer": spend.get(role, 0),
               "difference": spend.get(role, 0) - budgets[role]}
        for role in budgets
    }


def write_live_plan(pool: pd.DataFrame, config: AuctionOptimizationConfig,
                    args: argparse.Namespace) -> None:
    """Residual plan and maximum bids for the current auction state."""
    from src.models.live_auction import LivePlanner, read_state

    planner = LivePlanner(pool, config, me=args.me, managers=args.managers,
                          market_scaling=not args.no_market_scaling)
    state = read_state(args.state)
    plan = planner.plan(state)
    bids = planner.plan_bids(state)
    scenario = "con_modificatore" if args.defence_modifier else "senza_modificatore"
    args.output_dir.mkdir(parents=True, exist_ok=True)
    roster = plan.roster.merge(
        bids[["player", "offerta_max", "motivo", "se_lo_perdi"]] if not bids.empty
        else pd.DataFrame(columns=["player", "offerta_max", "motivo", "se_lo_perdi"]),
        on="player", how="left")
    roster.to_csv(args.output_dir / f"piano_live_{scenario}.csv", index=False)
    plan.managers.to_csv(args.output_dir / "partecipanti.csv", index=False)
    summary = {
        "scenario": scenario, "state": str(args.state), "sales": int(len(state)),
        "me": args.me, "my_budget_left": plan.my_budget_left, "my_max_bid": plan.my_max_bid,
        "objective": round(plan.objective, 4), "credit_value": round(plan.credit_value, 5),
        "market_factor": round(plan.market_factor, 3),
        "pool_after_pruning": plan.pool_size,
        "bid_rule": ("price at which buying the player leaves the plan as good as the best "
                     "plan without him, at reference prices for everyone else; capped by "
                     "remaining credits minus one per other open slot"),
    }
    (args.output_dir / f"piano_live_{scenario}.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    print(roster.to_string(index=False))
    print(json.dumps(summary, indent=2, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--forecast", type=Path, required=True)
    parser.add_argument("--dossier-players", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--budget", type=int, default=500)
    parser.add_argument("--reserve", type=int, default=0,
                         help="Credits to keep unspent (e.g. 1 per still-open slot)")
    parser.add_argument("--defence-modifier", action="store_true")
    parser.add_argument("--quotation-floor", type=float, default=0.5,
                         help="Minimum cost as a multiple of the public quotation (0 disables)")
    parser.add_argument("--db", type=Path,
                         help="Warehouse used to calibrate the defence-modifier premium")
    parser.add_argument("--modifier-season", default="2025/26")
    parser.add_argument("--alternatives", type=int, default=5)
    parser.add_argument("--min-changes", type=int, default=3,
                         help="Players each alternative must change versus every earlier one")
    parser.add_argument("--robustness-draws", type=int, default=100, help="0 skips the analysis")
    parser.add_argument("--seed", type=int, default=20260923)
    parser.add_argument("--state", type=Path,
                        help="Live auction log (giocatore,acquirente,prezzo): re-plan the open "
                             "slots and write maximum bids instead of the pre-auction analysis")
    parser.add_argument("--me", default="io", help="Your buyer name in --state")
    parser.add_argument("--managers", type=int, default=8)
    parser.add_argument("--no-market-scaling", action="store_true",
                        help="With --state: keep dossier reference prices for unsold players")
    args = parser.parse_args()

    pool, match_report = build_pool(
        args.forecast, args.dossier_players, args.defence_modifier, args.quotation_floor
    )
    if match_report["unmatched_forecast"] or match_report["unmatched_dossier"]:
        print(
            f"identity join: {match_report['matched']} matched, "
            f"{len(match_report['unmatched_forecast'])} forecast-only, "
            f"{len(match_report['unmatched_dossier'])} dossier-only "
            "(see match_report in the summary JSON)"
        )
    calibration = None
    config = AuctionOptimizationConfig(
        budget=args.budget, reserve=args.reserve, defence_modifier=args.defence_modifier,
    )
    if args.defence_modifier and args.db:
        calibration = calibrate_modifier(args.db, args.modifier_season)
        config = AuctionOptimizationConfig(
            budget=args.budget, reserve=args.reserve, defence_modifier=True,
            modifier_marginal=calibration["marginal_points_per_vote_point_per_player"],
        )

    if args.state:
        write_live_plan(pool, config, args)
        return

    results = alternative_rosters(pool, config, count=max(1, args.alternatives),
                                  min_changes=args.min_changes)
    result = results[0]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    scenario = "con_modificatore" if args.defence_modifier else "senza_modificatore"
    roster_path = args.output_dir / f"rosa_ideale_{scenario}.csv"
    result["roster"].to_csv(roster_path, index=False)
    if len(results) > 1:
        pd.concat(
            [r["roster"].assign(alternativa=rank, obiettivo=r["objective"], costo=r["total_cost"])
             for rank, r in enumerate(results, start=1)],
            ignore_index=True,
        ).to_csv(args.output_dir / f"alternative_{scenario}.csv", index=False)
    robustness_summary = None
    if args.robustness_draws > 0:
        report = selection_robustness(pool, config, draws=args.robustness_draws, seed=args.seed)
        report.to_csv(args.output_dir / f"robustezza_{scenario}.csv", index=False)
        robustness_summary = {
            "draws": args.robustness_draws, "cost_sigma": 0.25, "utility_sigma": 0.05,
            "seed": args.seed,
            "pilastri": report.loc[report.tier.eq("pilastro"), "player"].tolist(),
            "base_roster_mean_selection_rate": round(float(
                report.set_index("player").selection_rate.reindex(result["roster"].player).fillna(0).mean()
            ), 3),
        }

    summary = {key: value for key, value in result.items() if key != "roster"}
    summary.update({
        "scenario": scenario,
        "players": int(len(result["roster"])),
        "role_counts": result["roster"].groupby("role").size().to_dict(),
        "forecast": str(args.forecast),
        "dossier_players": str(args.dossier_players),
        "cost_model": (
            "rounded FVM role-market reference, floored at "
            f"{args.quotation_floor} x public quotation; not a clearing-price forecast"
        ),
        "cost_floor_applied_in_roster": result["roster"].loc[
            result["roster"].cost_floor_applied, "player"].tolist(),
        "availability_policy": (
            "structured expected-return discount from the forecast where available; "
            "otherwise 0.75 for a current notice, 0.35 for explicit long-stop language"
        ),
        "role_budget_deviation": role_budget_deviation(
            result["spend_by_role"], args.dossier_players, scenario),
        "alternatives": [
            {"rank": rank, "objective": round(r["objective"], 3), "total_cost": r["total_cost"],
             "changes_vs_best": sorted(set(r["roster"].player) - set(result["roster"].player))}
            for rank, r in enumerate(results, start=1)
        ],
        "robustness": robustness_summary,
        "match_report": match_report,
    })
    if args.defence_modifier:
        summary["defence_modifier_rule"] = {
            "average_of": "goalkeeper + best 3 defenders",
            "strict_thresholds": {">6.5": 1, ">7.0": 3},
            "premium": (
                "marginal x (expected vote - role median of regular starters) x p_plays "
                "on P1 and D1-D3 (D4 x0.3)"
            ),
            "calibration": calibration or {
                "marginal_points_per_vote_point_per_player": config.modifier_marginal,
                "source": "defaults (pass --db to recalibrate)",
            },
        }
    summary_path = args.output_dir / f"rosa_ideale_{scenario}.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str) + "\n")
    print(json.dumps(summary, indent=2, ensure_ascii=False, default=str))
    print(roster_path)


if __name__ == "__main__":
    main()
