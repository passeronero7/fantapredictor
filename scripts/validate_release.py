#!/usr/bin/env python3
"""Validate roster provenance and model-release prerequisites."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config.settings import config

VALID_STATUSES = {"confirmed", "watchlist", "excluded"}
REQUIRED_COLUMNS = {"player", "role", "status", "source_url", "checked_at"}


def validate_roster(path: str | Path, require_confirmed: bool = False) -> dict[str, int]:
    """Validate a roster CSV and return status counts."""
    path = Path(path)
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        columns = set(reader.fieldnames or [])
        missing = REQUIRED_COLUMNS - columns
        if missing:
            raise ValueError(f"Roster is missing required columns: {', '.join(sorted(missing))}")
        if not {"club", "club_2026_27"}.intersection(columns):
            raise ValueError("Roster is missing required column: club")

        counts = {status: 0 for status in sorted(VALID_STATUSES)}
        for line_number, row in enumerate(reader, start=2):
            status = (row.get("status") or "").strip().lower()
            if status not in VALID_STATUSES:
                raise ValueError(f"Invalid roster status on line {line_number}: {status!r}")
            for column in ("player", "source_url", "checked_at"):
                if not (row.get(column) or "").strip():
                    raise ValueError(f"Missing {column} on roster line {line_number}")
            if status == "confirmed" and not (row.get("role") or "").strip():
                raise ValueError(f"Confirmed roster line {line_number} has no role")
            counts[status] += 1

    if require_confirmed and counts["confirmed"] == 0:
        raise ValueError("No confirmed roster records are available")
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", default="2627")
    parser.add_argument("--roster", type=Path)
    parser.add_argument("--require-confirmed", action="store_true")
    args = parser.parse_args()
    roster = args.roster or (
        config.get_season_dir(args.season) / "rosters" /
        f"virgilio_rosters_{config.get_season_dir(args.season).name.removeprefix('season_')}.csv"
    )
    counts = validate_roster(roster, require_confirmed=args.require_confirmed)
    print(f"Roster: {roster}")
    print(f"Status counts: {counts}")


if __name__ == "__main__":
    main()
