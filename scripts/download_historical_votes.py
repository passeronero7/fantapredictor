#!/usr/bin/env python3
"""Download and archive official Fantacalcio.it matchday votes and ratings."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
from config.settings import config
from src.data_processing.votes_processor import VotesProcessor


def download_season_votes(
    season_slug: str = "2024-25",
    start_matchday: int = 1,
    end_matchday: int = 38,
    delay_sec: float = 1.0,
) -> Path:
    """Download and archive weekly votes for a season."""
    processor = VotesProcessor()
    season_code = season_slug.replace("-", "")[-4:]
    season_dir = config.get_season_dir(season_code)
    output_dir = season_dir / "fantacalcio" / config.VOTES_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    all_frames = []
    print(f"=== Downloading Fantacalcio.it official votes for Season {season_slug} (Matchdays {start_matchday}..{end_matchday}) ===")

    for md in range(start_matchday, end_matchday + 1):
        try:
            df_md = processor.fetch_online_matchday_votes(season_slug=season_slug, matchday=md)
            if df_md.empty:
                print(f"Matchday {md:02d}: No data found or season not reached.")
                break

            # Save individual matchday CSV
            file_name = f"Voti_Fantacalcio_Stagione_{season_slug}_Giornata_{md:02d}.csv"
            out_file = output_dir / file_name
            df_md.to_csv(out_file, index=False)
            all_frames.append(df_md)
            print(f"✓ Matchday {md:02d}: {len(df_md)} player records saved to {file_name}")

            time.sleep(delay_sec)
        except Exception as e:
            print(f"✗ Matchday {md:02d} error: {e}")
            break

    if all_frames:
        combined = pd.concat(all_frames, ignore_index=True)
        summary_file = output_dir / f"Voti_Fantacalcio_Stagione_{season_slug}_Full.csv"
        combined.to_csv(summary_file, index=False)
        print(f"\n✓ Successfully archived {len(combined)} total player-match instances to {summary_file}")
        return summary_file
    else:
        print("No votes retrieved.")
        return output_dir


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", default="2024-25", help="Season slug, e.g. 2024-25, 2023-24, 2022-23")
    parser.add_argument("--start", type=int, default=1, help="Start matchday (default: 1)")
    parser.add_argument("--end", type=int, default=38, help="End matchday (default: 38)")
    parser.add_argument("--delay", type=float, default=1.0, help="Delay in seconds between requests")
    args = parser.parse_args()

    download_season_votes(
        season_slug=args.season,
        start_matchday=args.start,
        end_matchday=args.end,
        delay_sec=args.delay,
    )


if __name__ == "__main__":
    main()
