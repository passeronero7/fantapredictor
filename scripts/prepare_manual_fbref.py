#!/usr/bin/env python3
"""Prepare manually copied FBref CSVs for local warehouse ingestion."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config.settings import config
from src.data_processing.fbref_manual import EXPORTS, normalize_fbref_export


def prepare(source_dir: str | Path, output_dir: str | Path, season: str) -> dict[str, int]:
    """Normalize every non-empty expected FBref CSV in ``source_dir``."""
    source_dir = Path(source_dir)
    output_dir = Path(output_dir)
    prepared: dict[str, int] = {}
    for category, pattern in EXPORTS.items():
        source = source_dir / pattern.format(season=season)
        if not source.exists() or not source.stat().st_size:
            continue
        destination = output_dir / source.name
        prepared[category] = normalize_fbref_export(source, destination)
    return prepared


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--season", default="2627")
    args = parser.parse_args()
    output_dir = args.output_dir or config.get_season_dir(args.season) / "manual"
    prepared = prepare(args.source_dir, output_dir, args.season)
    if not prepared:
        print(f"No non-empty FBref CSVs found in {args.source_dir}")
        return
    for category, rows in prepared.items():
        print(f"{category}: {rows} rows")
    print(f"output: {output_dir}")


if __name__ == "__main__":
    main()
