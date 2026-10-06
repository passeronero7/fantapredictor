#!/usr/bin/env python3
"""Weekly Lineup Advisory Engine for Fantacalcio.

Phase 3.2 & In-Season Operations:
Recommends optimal 11 starters, bench order, and formation for a specific matchday
using fresh probable lineups, injury reports, and defence modifier probabilities.
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config.settings import config
from src.utils.name_matching import normalize_name

logger = logging.getLogger(__name__)

LEGAL_FORMATIONS = [
    (3, 4, 3),
    (3, 5, 2),
    (4, 3, 3),
    (4, 4, 2),
    (4, 5, 1),
    (5, 3, 2),
    (5, 4, 1),
]


def load_user_roster(roster_path: Path) -> pd.DataFrame:
    """Load user's 25-man roster."""
    if not roster_path.exists():
        raise FileNotFoundError(f"Roster file not found: {roster_path}")
    df = pd.read_csv(roster_path)
    # Normalize column names
    col_map = {
        "giocatore": "player",
        "ruolo": "role",
        "squadra": "team",
        "prezzo": "price",
    }
    df = df.rename(columns=col_map)
    df["player_normalized"] = df["player"].apply(normalize_name)
    df["role"] = df["role"].astype(str).str.upper().str.strip()
    return df


def load_matchday_context(
    data_dir: Path,
    matchday: int,
    db_path: Path | None = None,
) -> tuple[dict[str, bool], dict[str, str], dict[str, dict]]:
    """Load titular status, availability notes, and opponent for each team.

    Returns:
        is_probable_starter: dict mapping player_normalized to bool
        availability_notes: dict mapping player_normalized to note string
        matchups: dict mapping team to {opponent, is_home}
    """
    season_dir = data_dir / "season_2026_27"
    is_probable_starter = {}
    availability_notes = {}
    matchups = {}

    # 1. Probable formations
    formations_file = season_dir / "coaches" / "probable_formations_2026_27.csv"
    if formations_file.exists():
        fdf = pd.read_csv(formations_file)
        for _, row in fdf.iterrows():
            titolars = str(row.get("titulars", "")).split(";")
            for t in titolars:
                norm = normalize_name(t.strip())
                if norm:
                    is_probable_starter[norm] = True

    # 2. Availability notes
    injuries_file = season_dir / "coaches" / "availability_current.csv"
    if not injuries_file.exists():
        injuries_file = season_dir / "coaches" / "injuries_2026_27.csv"
    if injuries_file.exists():
        idf = pd.read_csv(injuries_file)
        for _, row in idf.iterrows():
            norm = normalize_name(str(row.get("player", "")))
            kind = str(row.get("kind", ""))
            note = str(row.get("note", ""))
            exp = str(row.get("expected_return", ""))
            availability_notes[norm] = f"{kind}: {note} (rientro: {exp})"

    # 3. Matchups from SQLite
    real_db = db_path or (data_dir / "fantapredictor.db")
    if real_db.exists():
        try:
            with sqlite3.connect(f"file:{real_db}?mode=ro", uri=True) as conn:
                fixtures = pd.read_sql_query(
                    """
                    SELECT h.name AS home_team, a.name AS away_team
                    FROM matches m
                    JOIN seasons s ON s.id = m.season_id
                    JOIN clubs h ON h.id = m.home_club_id
                    JOIN clubs a ON a.id = m.away_club_id
                    WHERE s.name = '2026/27' AND m.matchday = ?
                    """,
                    conn,
                    params=(matchday,),
                )
                for _, fix in fixtures.iterrows():
                    h, a = fix["home_team"], fix["away_team"]
                    matchups[h] = {"opponent": a, "is_home": True}
                    matchups[a] = {"opponent": h, "is_home": False}
        except Exception as e:
            logger.warning(f"Could not load matches from DB: {e}")

    return is_probable_starter, availability_notes, matchups


def attach_player_forecasts(
    roster: pd.DataFrame,
    forecast_path: Path | None,
    is_starter_map: dict[str, bool],
    injuries_map: dict[str, str],
) -> pd.DataFrame:
    """Enrich roster players with expected votes, appearance probabilities, and risk."""
    df = roster.copy()

    # Load forecast if available
    forecast_df = None
    if forecast_path and forecast_path.exists():
        forecast_df = pd.read_csv(forecast_path)
        forecast_df["player_normalized"] = forecast_df["player_normalized"].apply(normalize_name)

    if forecast_df is not None:
        keep_cols = [c for c in ["player_normalized", "expected_fantavoto", "p_plays", "expected_vote", "horizon_median_vote", "p_good_mark"] if c in forecast_df.columns]
        df = df.merge(forecast_df[keep_cols], on="player_normalized", how="left")
        if "horizon_median_vote" in df.columns:
            if "expected_vote" not in df.columns or df["expected_vote"].isna().all():
                df["expected_vote"] = df["horizon_median_vote"]

    # Defaults if missing
    if "expected_fantavoto" not in df.columns:
        role_default = {"P": 5.0, "D": 5.7, "C": 6.2, "A": 6.8}
        df["expected_fantavoto"] = df["role"].map(role_default).fillna(6.0)
    else:
        role_default = {"P": 5.0, "D": 5.7, "C": 6.2, "A": 6.8}
        df["expected_fantavoto"] = df["expected_fantavoto"].fillna(df["role"].map(role_default))

    if "expected_vote" not in df.columns:
        df["expected_vote"] = 6.0
    else:
        df["expected_vote"] = df["expected_vote"].fillna(6.0)

    if "p_plays" not in df.columns:
        df["p_plays"] = 0.75
    else:
        df["p_plays"] = df["p_plays"].fillna(0.75)

    # Modulate p_plays with matchday-specific starter and injury info
    p_play_adjusted = []
    status_tags = []
    for _, row in df.iterrows():
        pname = row["player_normalized"]
        base_p = float(row["p_plays"])
        is_starter = is_starter_map.get(pname, False)
        injury = injuries_map.get(pname)

        if injury:
            if "squalificat" in injury.lower():
                adj = 0.0
                tag = "Squalificato"
            else:
                adj = 0.05
                tag = "Infortunato / Indisponibile"
        elif is_starter:
            adj = max(base_p, 0.95)
            tag = "Probabile Titolare"
        else:
            adj = min(base_p, 0.50)
            tag = "Ballottaggio / Panchina"

        p_play_adjusted.append(round(adj, 3))
        status_tags.append(tag)

    df["p_play_adjusted"] = p_play_adjusted
    df["status_tag"] = status_tags
    return df


def optimize_lineup_for_matchday(
    players_df: pd.DataFrame,
    enable_defence_modifier: bool = True,
    max_subs: int = 5,
) -> dict:
    """Evaluate all legal formations and determine optimal starters, bench and formation."""
    best_result = None
    best_score = -1e9

    for form in LEGAL_FORMATIONS:
        d_count, c_count, a_count = form
        starters = []
        bench = []

        # Role by role: sort by adjusted expected score
        for role, count in [("P", 1), ("D", d_count), ("C", c_count), ("A", a_count)]:
            role_players = players_df[players_df["role"] == role].copy()
            # Selection priority: expected fantavoto penalized by absence risk
            role_players["score_metric"] = role_players["expected_fantavoto"] * role_players["p_play_adjusted"]
            # Extra weight for defenders if modifier enabled
            if role == "D" and enable_defence_modifier and d_count >= 4:
                role_players["score_metric"] += 0.25 * (role_players["expected_vote"] - 6.0)

            sorted_players = role_players.sort_values("score_metric", ascending=False)
            starters_role = sorted_players.head(count)
            bench_role = sorted_players.iloc[count:]

            starters.append(starters_role)
            bench.append(bench_role)

        starters_df = pd.concat(starters, ignore_index=True)
        bench_df = pd.concat(bench, ignore_index=True)

        # Expected score computation with substitution recovery
        # 1. Base expected fantavoto of starters
        base_score = starters_df["expected_fantavoto"].sum()

        # 2. Appearance probability adjustment and sub recovery
        # Starter expected points = P(plays) * FV + (1 - P(plays)) * Bench_Recovery
        exp_score = 0.0
        for _, s in starters_df.iterrows():
            r = s["role"]
            fv = s["expected_fantavoto"]
            p = s["p_play_adjusted"]
            # bench replacement of same role
            bench_role = bench_df[bench_df["role"] == r]
            bench_fv = bench_role["expected_fantavoto"].iloc[0] if not bench_role.empty else 0.0
            bench_p = bench_role["p_play_adjusted"].iloc[0] if not bench_role.empty else 0.0
            effective = p * fv + (1.0 - p) * (bench_p * bench_fv)
            exp_score += effective

        # 3. Defence modifier bonus estimate
        mod_bonus = 0.0
        if enable_defence_modifier and d_count >= 4:
            gk = starters_df[starters_df["role"] == "P"]
            defenders = starters_df[starters_df["role"] == "D"].sort_values("expected_vote", ascending=False)
            if not gk.empty and len(defenders) >= 3:
                gk_vote = gk["expected_vote"].iloc[0]
                best3_votes = defenders["expected_vote"].head(3).mean()
                avg_def = (gk_vote + 3 * best3_votes) / 4.0
                if avg_def > 7.0:
                    mod_bonus = 3.0
                elif avg_def > 6.5:
                    mod_bonus = 1.0
                elif avg_def > 6.25:
                    # probabilistic expectation of crossing 6.5
                    mod_bonus = round((avg_def - 6.25) / 0.25 * 0.7, 2)

        total_score = exp_score + mod_bonus

        if total_score > best_score:
            best_score = total_score
            best_result = {
                "formation": f"{d_count}-{c_count}-{a_count}",
                "formation_tuple": form,
                "expected_total_score": round(float(total_score), 2),
                "expected_base_score": round(float(exp_score), 2),
                "expected_modifier_bonus": round(float(mod_bonus), 2),
                "starters": starters_df,
                "bench": bench_df,
            }

    # Format sorted bench: 1 GK, then defenders, midfielders, attackers ordered by score_metric
    sorted_bench_list = []
    # 1. Reserve Goalkeepers
    for _, p in best_result["bench"][best_result["bench"]["role"] == "P"].iterrows():
        sorted_bench_list.append(p)
    # 2. Reserve Outfielders ordered by score_metric
    outfield_bench = best_result["bench"][best_result["bench"]["role"] != "P"].sort_values("score_metric", ascending=False)
    for _, p in outfield_bench.iterrows():
        sorted_bench_list.append(p)

    best_result["bench_ordered"] = pd.DataFrame(sorted_bench_list)
    return best_result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--roster", type=Path, help="Path to user roster CSV")
    parser.add_argument("--matchday", type=int, default=6, help="Target matchday (default: 6)")
    parser.add_argument("--forecast", type=Path, help="Explicit propensity forecast CSV path")
    parser.add_argument("--defence-modifier", action="store_true", default=True, help="Include defence modifier bonus")
    parser.add_argument("--no-defence-modifier", action="store_false", dest="defence_modifier")
    parser.add_argument("--output", type=Path, help="Optional output JSON report path")
    args = parser.parse_args()

    data_dir = config.DATA_DIR
    season_dir = data_dir / "season_2026_27"

    roster_path = args.roster
    if not roster_path:
        roster_path = data_dir.parent / "asta" / "rosa_finale_2026_09_27.csv"
        if not roster_path.exists():
            roster_path = Path("asta/rosa_finale_2026_09_27.csv")

    # Forecast file auto-detection (find latest by modification time)
    if args.forecast:
        forecast_path = args.forecast
    else:
        forecast_candidates = sorted(season_dir.glob("outputs/auction_propensity_*.csv"), key=lambda p: p.stat().st_mtime)
        forecast_path = forecast_candidates[-1] if forecast_candidates else None

    print(f"=== FantaPredictor: Formazione Consigliata Giornata {args.matchday} ===")
    print(f"Rosa: {roster_path}")
    print(f"Modificatore difesa: {'Attivo (+1 >6.5, +3 >7.0)' if args.defence_modifier else 'Disattivato'}")

    roster = load_user_roster(roster_path)
    is_starter_map, injuries_map, matchups = load_matchday_context(data_dir, args.matchday)
    enriched = attach_player_forecasts(roster, forecast_path, is_starter_map, injuries_map)

    result = optimize_lineup_for_matchday(enriched, enable_defence_modifier=args.defence_modifier)

    print(f"\n=================================================================")
    print(f"🏆 MODULO CONSIGLIATO: {result['formation']}")
    print(f"Punteggio Totale Atteso: {result['expected_total_score']} pt")
    print(f"(Base: {result['expected_base_score']} pt | Bonus Modificatore Difesa: +{result['expected_modifier_bonus']} pt)")
    print(f"=================================================================\n")

    print("--- 11 TITOLARI CONSIGLIATI ---")
    headers = f"{'Ruolo':<6} {'Giocatore':<20} {'Squadra':<12} {'Avversario':<18} {'Stato':<26} {'FV Atteso':<10}"
    print(headers)
    print("-" * len(headers))
    for _, p in result["starters"].iterrows():
        team = str(p["team"])
        match_info = matchups.get(team, {})
        opp = match_info.get("opponent", "N/A")
        venue = " (C)" if match_info.get("is_home") else " (T)" if "is_home" in match_info else ""
        opp_str = f"vs {opp}{venue}" if opp != "N/A" else "N/A"
        print(f"{p['role']:<6} {p['player']:<20} {team:<12} {opp_str:<18} {p['status_tag']:<26} {p['expected_fantavoto']:<10.2f}")

    print("\n--- PANCHINA ORDINATA (Ordine di Subentro) ---")
    headers_b = f"{'Pos':<4} {'Ruolo':<6} {'Giocatore':<20} {'Squadra':<12} {'Stato':<26} {'FV Atteso':<10}"
    print(headers_b)
    print("-" * len(headers_b))
    for idx, (_, p) in enumerate(result["bench_ordered"].iterrows(), 1):
        print(f"{idx:<4} {p['role']:<6} {p['player']:<20} {p['team']:<12} {p['status_tag']:<26} {p['expected_fantavoto']:<10.2f}")

    # Indisponibili nella propria rosa
    out_players = enriched[enriched["p_play_adjusted"] < 0.2]
    if not out_players.empty:
        print("\n⚠️ GIOCATORI ASSENTI / IN FORTE DUBBIO:")
        for _, p in out_players.iterrows():
            note = injuries_map.get(p["player_normalized"], p["status_tag"])
            print(f"- {p['player']} ({p['role']}, {p['team']}): {note}")

    if args.output:
        report = {
            "matchday": args.matchday,
            "formation": result["formation"],
            "expected_total_score": result["expected_total_score"],
            "expected_base_score": result["expected_base_score"],
            "expected_modifier_bonus": result["expected_modifier_bonus"],
            "starters": result["starters"][["player", "role", "team", "expected_fantavoto", "p_play_adjusted", "status_tag"]].to_dict(orient="records"),
            "bench": result["bench_ordered"][["player", "role", "team", "expected_fantavoto", "p_play_adjusted", "status_tag"]].to_dict(orient="records"),
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
        print(f"\n✓ Report salvato in: {args.output}")


if __name__ == "__main__":
    main()
