#!/usr/bin/env python3
"""Download Serie A match results and odds from Football-Data.co.uk."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


BASE_URL = "https://www.football-data.co.uk/mmz4281/{season}/I1.csv"


def season_codes(start_year: int, end_year: int) -> list[str]:
    """Return compact season codes from start_year through end_year."""
    return [f"{year % 100:02d}{(year + 1) % 100:02d}" for year in range(start_year, end_year + 1)]


def download(
    output_dir: str | Path,
    start_year: int = 1993,
    end_year: int = 2025,
    delay: float = 1.0,
) -> int:
    """Download available I1 files and return the number of files written."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": "FantaPredictorResearch/0.2 (personal research)"}
    written = 0
    for code in season_codes(start_year, end_year):
        destination = output_dir / code / "I1.csv"
        if destination.exists():
            written += 1
            continue
        response = requests.get(BASE_URL.format(season=code), headers=headers, timeout=30)
        if response.status_code != 200 or not response.content.strip():
            print(f"skip {code}: HTTP {response.status_code}")
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(response.content)
        written += 1
        print(f"saved {code}: {destination}")
        time.sleep(delay)
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "raw" / "football-data.co.uk")
    parser.add_argument("--start-year", type=int, default=1993)
    parser.add_argument("--end-year", type=int, default=2025)
    parser.add_argument("--delay", type=float, default=1.0)
    args = parser.parse_args()
    print(f"Downloaded {download(args.output, args.start_year, args.end_year, args.delay)} files.")


if __name__ == "__main__":
    main()
