#!/usr/bin/env python3
"""Simulated time-series forecast of auction propensity to a median good mark.

Forecast mode ranks the priced confirmed roster by the Monte Carlo probability
that a player's median fantavoto over the upcoming matchdays clears a good-mark
threshold, conditioned on his own history and his club's statistical attitude
(attack/defense style from shots and goals). Backtest mode validates the same
estimator walk-forward on a completed season: calibration, Brier score, and
the realised marks of baskets selected by propensity versus naive alternatives.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config.settings import config
from src.db import database, repository
from src.models.propensity import (
    SimulationConfig,
    archetype_estimates,
    backtest_propensity,
    club_style_index,
    coach_role_delta,
    coach_style_adjustments,
    player_propensity,
    simulate_horizon,
)


def load_frames(conn, season: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    votes = repository.load_votes(conn, through_season=season)
    team_stats = repository.load_team_match_stats(conn, through_season=season)
    rosters = repository.load_rosters(conn, season)
    rosters = rosters[rosters["status"].astype(str).str.strip().eq("confirmed")]
    return votes, team_stats, rosters


def attach_prices(
    propensity: pd.DataFrame, prices: pd.DataFrame
) -> pd.DataFrame:
    merged = propensity.merge(
        prices[["player_normalized", "price_current", "fvm"]],
        on="player_normalized", how="left",
    )
    return merged.rename(columns={"price_current": "price"})


def run_forecast(
    conn,
    season: str,
    from_matchday: int,
    matchdays: int,
    simulations: int,
    good_mark: float,
    seed: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    from src.db.ingestors.common import season_label

    votes, team_stats, rosters = load_frames(conn, season)
    season_name = season_label(season)
    style_all = club_style_index(team_stats)
    # The current season may lack team stats (Understat-only snapshot): fall
    # back to each club's latest observed season attitude.
    style = (
        style_all.dropna(subset=["attack_index"])
        .sort_values("season")
        .groupby("team", as_index=False)
        .tail(1)
        .reset_index(drop=True)
    )
    propensity = player_propensity(
        votes, team_stats, season_name, from_matchday, good_vote=6.0
    )

    # Authoritative current club from the confirmed roster, not the last
    # rating (a transferred player's last observation is his former club).
    roster_club = rosters[["player_normalized", "club_2026_27"]].drop_duplicates(
        "player_normalized"
    )
    propensity = propensity.merge(
        roster_club.rename(columns={"club_2026_27": "roster_club"}),
        on="player_normalized", how="left",
    )
    propensity["team"] = propensity["roster_club"].fillna(propensity["team"])
    propensity = propensity.drop(columns=["roster_club"])

    # Never-observed new signings enter at the role prior instead of being
    # silently excluded from the auction basket.
    prior_marks = votes.dropna(subset=["vote"])
    prior_marks = prior_marks[
        ~prior_marks["season"].astype(str).eq(season_name)
        | (
            prior_marks["season"].astype(str).eq(season_name)
            & pd.to_numeric(prior_marks["matchday"], errors="coerce") < from_matchday
        )
    ]
    role_prior = prior_marks.groupby("role").apply(
        lambda v: float((v["vote"] >= 6.0).mean()), include_groups=False
    )
    # Unobserved signings get a conservative, documented appearance prior;
    # the historical obs-count ratio is not a probability.
    UNOBSERVED_P_PLAYS = 0.35
    observed_keys = set(propensity["player_normalized"])
    missing = roster_club[~roster_club["player_normalized"].isin(observed_keys)]
    if not missing.empty:
        role_of = rosters.drop_duplicates("player_normalized").set_index(
            "player_normalized"
        )["role"]
        rows = []
        for _, row in missing.iterrows():
            key = row["player_normalized"]
            role = str(role_of.get(key, "C"))
            rows.append({
                "player_normalized": key,
                "player": key,
                "role": role,
                "team": row["club_2026_27"],
                "appearances": 0,
                "vote_median": np.nan,
                "fantavoto_median": np.nan,
                "good_marks": 0.0,
                "bonus_rate": np.nan,
                "mean_bonus_when_bonus": np.nan,
                "good_rate_raw": np.nan,
                "appearance_rate_raw": np.nan,
                "p_good_mark": float(role_prior.get(role, 0.5)),
                "p_plays": UNOBSERVED_P_PLAYS,
            })
        propensity = pd.concat([propensity, pd.DataFrame(rows)], ignore_index=True)

    # Coach conditioning: module and style-tag deltas per role.
    conditioning = coach_style_adjustments(conn, season_name)
    print(f"Coach conditioning active for {len(conditioning)} clubs")
    propensity["coach_delta"] = [
        coach_role_delta(conditioning.get(team), role)
        for team, role in zip(propensity["team"], propensity["role"])
    ]
    propensity["p_good_mark"] = (
        (propensity["p_good_mark"] + propensity["coach_delta"]).clip(0.0, 1.0)
    )

    # Similar-player archetype blend: nearest same-role historical
    # player-seasons by per-90 technique signature.
    archetypes = archetype_estimates(conn, season, from_matchday)
    if not archetypes.empty:
        propensity = propensity.merge(archetypes, on="player_normalized", how="left")
        own = propensity["p_good_mark"]
        arch = propensity["archetype_p"]
        n = propensity["appearances"].fillna(0)
        own_weight = (n / (n + 6.0)).clip(0.35, 0.85)
        blended = own_weight * own + (1 - own_weight) * arch
        propensity["p_good_mark"] = blended.fillna(own).clip(0.0, 1.0)
        blended_rows = int(propensity["archetype_p"].notna().sum())
        print(f"Archetype blend applied to {blended_rows} players")

    prices_frame = repository.load_prices(conn, season)
    prices_frame = prices_frame[prices_frame["fuori_lista"].fillna(0).eq(0)].copy()
    priced = attach_prices(propensity, prices_frame)
    confirmed_keys = set(rosters["player_normalized"])
    priced = priced[priced["player_normalized"].isin(confirmed_keys)].copy()
    priced = priced[priced["price"].notna()].copy()
    if priced.empty:
        raise ValueError("No priced confirmed players available for the forecast")
    config = SimulationConfig(
        from_matchday=from_matchday,
        matchdays=matchdays,
        simulations=simulations,
        good_mark=good_mark,
        seed=seed,
    )
    clubs = sorted(rosters["club_2026_27"].dropna().unique())
    strays = int((~priced["team"].isin(clubs)).sum())
    if strays:
        print(f"note: excluded {strays} priced players outside the 2026/27 club population "
              "(legacy identity spellings pending reconciliation)")
        priced = priced[priced["team"].isin(clubs)].copy()
    if len(clubs) % 2 != 0:
        raise ValueError(f"Club pairing needs an even club list, got {len(clubs)}")
    result = simulate_horizon(priced, votes, style, clubs, config)
    result = result.merge(
        priced[["player_normalized", "price", "fvm"]], on="player_normalized", how="left"
    )
    result["expected_good_marks"] = (
        result["p_plays"].fillna(0.0) * result["simulated_mark_rate"]
    )
    result["value_per_credit"] = result["expected_good_marks"] / result["price"].clip(lower=1)
    return result.sort_values("p_horizon_median_good", ascending=False), style


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=config.DATA_DIR / "fantapredictor.db")
    parser.add_argument("--mode", choices=("forecast", "backtest"), default="forecast")
    parser.add_argument("--season", default="2627", help="Forecast season (2627) or backtest season (2025-26)")
    parser.add_argument("--from-matchday", type=int, default=3)
    parser.add_argument("--matchdays", type=int, default=8)
    parser.add_argument("--simulations", type=int, default=1000)
    parser.add_argument("--good-mark", type=float, default=6.0)
    parser.add_argument("--cutoffs", default="10,20,30", help="Backtest cutoffs")
    parser.add_argument("--window", type=int, default=10, help="Backtest evaluation window")
    parser.add_argument("--seed", type=int, default=20260903)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    conn = database.get_connection(args.db)
    try:
        if args.mode == "backtest":
            from src.db.ingestors.common import season_label

            votes = repository.load_votes(conn, through_season=args.season)
            team_stats = repository.load_team_match_stats(conn, through_season=args.season)
            report = backtest_propensity(
                votes,
                team_stats,
                season_label(args.season),
                [int(c) for c in args.cutoffs.split(",")],
                window=args.window,
                good_vote=args.good_mark,
            )
            print(json.dumps(report, indent=2, ensure_ascii=False))
            return

        result, style = run_forecast(
            conn, args.season, args.from_matchday, args.matchdays,
            args.simulations, args.good_mark, args.seed,
        )
    finally:
        conn.close()

    output = args.output or (
        config.get_season_dir(args.season) / "outputs" /
        f"auction_propensity_{args.season}_md{args.from_matchday}.csv"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output, index=False)

    print(f"Latest-observed club style index (attack / defense):")
    print(style[style["team"].isin(sorted(result["team"].dropna().unique()))].to_string(index=False))
    print(f"\nTop 25 by P(horizon median >= {args.good_mark}) — {args.matchdays} matchdays, "
          f"{args.simulations} simulations:")
    columns = ["player", "team", "role", "price", "p_plays", "p_good_mark",
               "simulated_mark_rate", "expected_fantavoto", "horizon_median_vote", "p_horizon_median_good",
               "value_per_credit"]
    print(result[columns].head(25).to_string(index=False))
    print(f"\nTop 15 by propensity per credit:")
    print(result.sort_values("value_per_credit", ascending=False)[columns].head(15).to_string(index=False))
    print(f"\nSaved: {output}")


if __name__ == "__main__":
    main()
