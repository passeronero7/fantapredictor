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


def validate_roster(
    path: str | Path,
    require_confirmed: bool = False,
    require_lineup: bool = False,
    require_priced: bool = False,
    prices_path: str | Path | None = None,
) -> dict[str, int]:
    """Validate a roster CSV and return status counts.

    With ``require_priced``, every default-formation slot must be fillable
    with *priced* confirmed players -- warm bodies without a quotation are
    not auction-eligible, so they do not satisfy the gate.
    """
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
        role_counts: dict[str, int] = {}
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
            if status == "confirmed":
                role = (row.get("role") or "").strip().upper()
                role_counts[role] = role_counts.get(role, 0) + 1

    if require_confirmed and counts["confirmed"] == 0:
        raise ValueError("No confirmed roster records are available")
    required_roles = {"P": 1, "D": 3, "C": 4, "A": 3}
    if require_lineup:
        missing_roles = {
            role: minimum - role_counts.get(role, 0)
            for role, minimum in required_roles.items()
            if role_counts.get(role, 0) < minimum
        }
        if missing_roles:
            raise ValueError(
                "Confirmed roster cannot form the default 3-4-3 lineup: "
                + ", ".join(f"{role} needs {count} more" for role, count in missing_roles.items())
            )
    if require_priced:
        priced_counts = priced_confirmed_role_counts(path, prices_path)
        missing_roles = {
            role: minimum - priced_counts.get(role, 0)
            for role, minimum in required_roles.items()
            if priced_counts.get(role, 0) < minimum
        }
        if missing_roles:
            raise ValueError(
                "Priced confirmed roster cannot form the default 3-4-3 lineup: "
                + ", ".join(f"{role} needs {count} more" for role, count in missing_roles.items())
            )
        counts["priced_confirmed"] = sum(priced_counts.values())
    return counts


def priced_confirmed_role_counts(
    roster_path: str | Path,
    prices_path: str | Path | None,
) -> dict[str, int]:
    """Count confirmed roster roles that are also present in the quotations."""
    if prices_path is None:
        raise ValueError("The priced gate needs a quotations CSV path")
    import pandas as pd

    from src.data_processing.prices_processor import match_prices_to_roster

    roster = pd.read_csv(roster_path)
    prices = pd.read_csv(prices_path)
    matches = match_prices_to_roster(roster, prices)
    confirmed_indexes = set(roster.index[roster["status"].astype(str).str.strip().eq("confirmed")])
    priced_indexes = {
        int(index)
        for index in matches.loc[matches["roster_index"] >= 0, "roster_index"]
        if int(index) in confirmed_indexes
    }
    priced_roles = (
        roster.loc[sorted(priced_indexes), "role"]
        .astype(str).str.strip().str.upper()
        .value_counts()
    )
    return {str(role): int(count) for role, count in priced_roles.items()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", default="2627")
    parser.add_argument("--roster", type=Path)
    parser.add_argument("--require-confirmed", action="store_true")
    parser.add_argument("--require-lineup", action="store_true")
    parser.add_argument(
        "--require-priced", action="store_true",
        help="Require the default formation to be fillable with priced confirmed players",
    )
    parser.add_argument("--prices", type=Path, help="Quotations CSV for the priced gate")
    args = parser.parse_args()
    season_dir = config.get_season_dir(args.season)
    suffix = season_dir.name.removeprefix("season_")
    roster = args.roster or (
        season_dir / "rosters" /
        f"virgilio_rosters_{suffix}.csv"
    )
    prices = args.prices or (season_dir / "fantacalcio" / "prices.csv")
    counts = validate_roster(
        roster,
        require_confirmed=args.require_confirmed,
        require_lineup=args.require_lineup,
        require_priced=args.require_priced,
        prices_path=prices if args.require_priced else None,
    )
    print(f"Roster: {roster}")
    print(f"Status counts: {counts}")


if __name__ == "__main__":
    main()
