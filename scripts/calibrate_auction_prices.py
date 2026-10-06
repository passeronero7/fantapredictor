#!/usr/bin/env python3
"""Calibrate empirical fantasy auction prices from observed league transactions.

Phase 3.4 of the Masterplan: Learns the empirical mapping between provider FVM/quotations
and realized auction clearing prices in the 8-manager, 500-credit league.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config.settings import config
from src.utils.name_matching import normalize_name

logger = logging.getLogger(__name__)


def load_auction_data(
    auction_log_path: Path,
    prices_path: Path,
    rose_complete_path: Path | None = None,
) -> pd.DataFrame:
    """Load and merge auction sales with provider price attributes."""
    if not auction_log_path.exists():
        raise FileNotFoundError(f"Auction log not found: {auction_log_path}")
    if not prices_path.exists():
        raise FileNotFoundError(f"Prices CSV not found: {prices_path}")

    sales = pd.read_csv(auction_log_path)
    prices = pd.read_csv(prices_path)

    sales["player_norm"] = sales["giocatore"].apply(normalize_name)
    prices["player_norm"] = prices["player"].apply(normalize_name)

    # Use rose_complete if available to disambiguate homonyms (e.g. Esposito)
    if rose_complete_path and rose_complete_path.exists():
        rose = pd.read_csv(rose_complete_path)
        col = "player_normalized" if "player_normalized" in rose.columns else ("player" if "player" in rose.columns else "giocatore")
        rose["player_norm"] = rose[col].apply(normalize_name)
        if "source_ref" in rose.columns and "source_ref" in prices.columns:
            ref_map = rose.set_index("player_norm")["source_ref"].to_dict()
            sales["source_ref"] = sales["player_norm"].map(ref_map)

    # Primary merge on normalized name
    merged = sales.merge(
        prices[["player_norm", "player", "team", "role_classic", "fvm", "price_current"]],
        on="player_norm",
        how="left",
    )

    # Fallback for ambiguous names: try prefix matching
    missing = merged[merged["role_classic"].isna()]
    for idx, row in missing.iterrows():
        pname = row["player_norm"]
        matches = prices[prices["player_norm"].str.startswith(pname)]
        if len(matches) == 1:
            for col in ["player", "team", "role_classic", "fvm", "price_current"]:
                merged.at[idx, col] = matches.iloc[0][col]

    merged = merged.dropna(subset=["role_classic", "prezzo"])
    merged["prezzo"] = pd.to_numeric(merged["prezzo"], errors="coerce")
    merged["fvm"] = pd.to_numeric(merged["fvm"], errors="coerce").fillna(1.0)
    merged["price_current"] = pd.to_numeric(merged["price_current"], errors="coerce").fillna(1.0)
    return merged


def fit_price_calibration(df: pd.DataFrame) -> dict:
    """Fit empirical regression models and role-tier multipliers on auction sales."""
    results = {
        "sample_size": len(df),
        "total_spend": float(df["prezzo"].sum()),
        "roles": {},
        "tiers": {},
        "spend_share_by_role": {},
    }

    total_spend = df["prezzo"].sum()

    for role, group in df.groupby("role_classic"):
        role_spend = float(group["prezzo"].sum())
        results["spend_share_by_role"][role] = {
            "total_spend": role_spend,
            "share_of_league_budget": round(role_spend / total_spend, 4) if total_spend else 0.0,
            "mean_price": round(float(group["prezzo"].mean()), 2),
            "median_price": round(float(group["prezzo"].median()), 2),
            "max_price": float(group["prezzo"].max()),
            "min_price": float(group["prezzo"].min()),
        }

        # Linear regression: Price ~ alpha * FVM + beta
        x = group["fvm"].to_numpy()
        y = group["prezzo"].to_numpy()

        if len(x) > 1 and np.std(x) > 0:
            slope, intercept = np.polyfit(x, y, 1)
            y_pred = slope * x + intercept
            ss_res = np.sum((y - y_pred) ** 2)
            ss_tot = np.sum((y - np.mean(y)) ** 2)
            r2 = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 0.0
            mae = float(np.mean(np.abs(y - y_pred)))
        else:
            slope, intercept, r2, mae = 1.0, 0.0, 0.0, 0.0

        # Ratio multiplier: mean(Price / FVM)
        ratios = group["prezzo"] / group["fvm"].clip(lower=1.0)

        results["roles"][role] = {
            "count": len(group),
            "fvm_slope": round(float(slope), 4),
            "fvm_intercept": round(float(intercept), 4),
            "r_squared": round(float(r2), 4),
            "mae": round(float(mae), 2),
            "mean_ratio_price_to_fvm": round(float(ratios.mean()), 3),
            "median_ratio_price_to_fvm": round(float(ratios.median()), 3),
        }

    # Tiered multipliers (Top tier: FVM >= 30, Mid tier: 10 <= FVM < 30, Low: FVM < 10)
    for tier_name, mask in [
        ("top_fvm_ge_30", df["fvm"] >= 30),
        ("mid_fvm_10_to_30", (df["fvm"] >= 10) & (df["fvm"] < 30)),
        ("low_fvm_lt_10", df["fvm"] < 10),
    ]:
        sub = df[mask]
        if not sub.empty:
            ratios = sub["prezzo"] / sub["fvm"].clip(lower=1.0)
            results["tiers"][tier_name] = {
                "count": len(sub),
                "mean_fvm": round(float(sub["fvm"].mean()), 1),
                "mean_price": round(float(sub["prezzo"].mean()), 1),
                "mean_price_fvm_ratio": round(float(ratios.mean()), 3),
            }

    return results


def predict_clearing_price(fvm: float, role: str, calibration: dict) -> float:
    """Predict clearing price from FVM using calibrated model with non-negative lower bound."""
    role_info = calibration.get("roles", {}).get(role.upper())
    if not role_info:
        return max(1.0, float(fvm))
    pred = role_info["fvm_slope"] * fvm + role_info["fvm_intercept"]
    return max(1.0, round(float(pred), 1))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--auction-log",
        type=Path,
        help="Path to stato_asta.csv (default: auto-detected in workspace/asta)",
    )
    parser.add_argument(
        "--prices",
        type=Path,
        help="Path to prices.csv (default: auto-detected in season data dir)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output path for JSON calibration report",
    )
    args = parser.parse_args()

    # Auto-detection
    data_dir = config.DATA_DIR
    season_dir = data_dir / "season_2026_27"
    auction_log = args.auction_log or data_dir.parent / "asta" / "stato_asta.csv"
    if not auction_log.exists():
        auction_log = Path("asta/stato_asta.csv")

    prices_path = args.prices or season_dir / "fantacalcio" / "prices.csv"
    rose_path = data_dir.parent / "asta" / "rose_complete_2026_09_27.csv"

    out_file = args.output or season_dir / "reports" / "price_calibration_2026_27.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)

    print(f"=== FantaPredictor 2026/27: Calibrating Real Auction Prices ===")
    print(f"Auction log: {auction_log}")
    print(f"Prices CSV:  {prices_path}")

    df = load_auction_data(auction_log, prices_path, rose_path if rose_path.exists() else None)
    calibration = fit_price_calibration(df)

    out_file.write_text(json.dumps(calibration, indent=2, ensure_ascii=False) + "\n")
    print(f"✓ Calibration report saved to: {out_file}\n")

    print(f"Total sales analyzed: {calibration['sample_size']} (Total spend: {calibration['total_spend']:.0f} credits)")
    print("\n--- Spending Share by Role ---")
    for role, stat in calibration["spend_share_by_role"].items():
        print(f"Role {role}: {stat['share_of_league_budget'] * 100:.1f}% of league budget | Avg: {stat['mean_price']} cr (Max: {stat['max_price']} cr)")

    print("\n--- Linear Calibration (Price = slope * FVM + intercept) ---")
    for role, stat in calibration["roles"].items():
        print(f"Role {role} (N={stat['count']}): Price = {stat['fvm_slope']:.3f} * FVM + ({stat['fvm_intercept']:.1f}) | R² = {stat['r_squared']:.3f}, MAE = {stat['mae']} cr")

    print("\n--- Tier Multipliers ---")
    for tier, stat in calibration["tiers"].items():
        print(f"{tier} (N={stat['count']}): Avg FVM={stat['mean_fvm']} -> Avg Price={stat['mean_price']} (ratio: {stat['mean_price_fvm_ratio']:.2f}x)")


if __name__ == "__main__":
    main()
