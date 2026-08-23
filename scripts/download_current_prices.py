#!/usr/bin/env python3
"""Download the public Fantacalcio quotation snapshot used by the auction model."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config.settings import config
from src.data_processing.prices_processor import fetch_current_prices


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", default="2026-27")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or config.get_season_dir(args.season) / "fantacalcio" / "prices.csv"
    output.parent.mkdir(parents=True, exist_ok=True)
    frame = fetch_current_prices(args.season)
    frame.to_csv(output, index=False)
    print(f"Saved {len(frame)} quotations to {output}")


if __name__ == "__main__":
    main()
