#!/usr/bin/env python3
"""Download a pipeline-ready Serie A Understat player-season snapshot."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config.settings import config
from src.data_processing.soccerdata_understat import download_player_season_stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", default="2627", help="e.g. 2627, 2026, or 2026-27")
    parser.add_argument("--output", type=Path, help="Directory for the snapshot and manifest")
    parser.add_argument("--overwrite", action="store_true", help="Replace an existing season snapshot")
    args = parser.parse_args()

    output = args.output or config.get_season_dir(args.season) / "raw" / "soccerdata"
    report = download_player_season_stats(args.season, output, overwrite=args.overwrite)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
