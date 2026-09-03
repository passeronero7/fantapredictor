#!/usr/bin/env python3
"""Promote roster watchlist rows to confirmed using the official quotations.

The Fantacalcio quotation list is the fantasy platform's official identity,
role, and price record. A roster ``watchlist`` row that matches a quotation
row of the same club therefore has evidenced club membership *and* fantasy
role, which is exactly the promotion standard in ``AGENTS.md``.

Matching is conservative (exact name, surname+initial, or a surname unique
within the club) and ambiguous cases are reported, never guessed. Run
without ``--apply`` to preview; with ``--apply`` the roster CSV is updated
in place (promoted rows adopt the quotation spelling so warehouse identity
merging can join roster and price rows).
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config.settings import config
from src.data_processing.prices_processor import (
    FANTACALCIO_TEAM_CODES,
    _surname_tail,
    match_prices_to_roster,
)
from src.utils.name_matching import normalize_name

QUOTATIONS_URL = "https://www.fantacalcio.it/quotazioni-fantacalcio"


def _name_core(name: str) -> tuple[list[str], str]:
    """Return ``(core_tokens, first_name_initial)`` for a normalized name.

    Trailing one/two-letter tokens are initials; the first of them carries
    the player's first-name initial when the source abbreviates it.
    """
    tokens = normalize_name(name).split()
    initial = ""
    while len(tokens) > 1 and len(tokens[-1]) <= 2:
        initial = initial or tokens[-1]
        tokens.pop()
    return tokens, initial


def _namesake(price_name: str, roster_name: str) -> bool:
    """True when two same-surname names are provably different players."""
    price_core, price_initial = _name_core(price_name)
    roster_core, roster_initial = _name_core(roster_name)
    if price_initial and roster_initial and price_initial != roster_initial:
        return True
    if len(price_core) >= 2 and len(roster_core) >= 2 and price_core[0] != roster_core[0]:
        return True
    return False


def promote(
    roster_path: str | Path,
    prices_path: str | Path,
    apply: bool = False,
    adopt_unmatched: bool = False,
) -> dict[str, object]:
    """Match quotations to watchlist rows; promote when ``apply`` is set.

    With ``adopt_unmatched``, priced players with no roster row (or only a
    stale watchlist row at another club) are adopted as confirmed directly
    from the quotation evidence, which is the official fantasy identity, role,
    and price list.
    """
    roster = pd.read_csv(roster_path)
    prices = pd.read_csv(prices_path)
    required = {"player", "club", "role", "status", "source_url", "checked_at"}
    missing = required - set(roster.columns)
    if missing:
        raise ValueError(f"Roster is missing required columns: {', '.join(sorted(missing))}")
    club_column = "club_2026_27" if "club_2026_27" in roster.columns else "club"

    matches = match_prices_to_roster(roster, prices)
    matched = matches[matches["roster_index"] >= 0]
    promotable = matched[matched["roster_status"] == "watchlist"]
    already = matched[matched["roster_status"] == "confirmed"]

    report = {
        "prices": int(len(prices)),
        "matched": int(len(matched)),
        "promotable_watchlist": int(len(promotable)),
        "already_confirmed": int(len(already)),
        "unmatched_prices": int((matches["roster_index"] < 0).sum()),
        "adopted": 0,
        "excluded_stale": 0,
        "adopt_conflicts": 0,
        "per_club": {},
    }

    if promotable.empty and not adopt_unmatched:
        return report

    if not promotable.empty:
        per_club = roster.loc[promotable["roster_index"], club_column].value_counts()
        report["per_club"] = {str(club): int(n) for club, n in per_club.items()}

    if apply and not promotable.empty:
        checked_at = datetime.now(UTC).isoformat()
        for price_index, roster_index in zip(promotable["price_index"], promotable["roster_index"]):
            price_row = prices.loc[price_index]
            roster.at[roster_index, "player"] = str(price_row["player"])
            roster.at[roster_index, "role"] = str(price_row.get("role_classic", "") or "").upper()
            roster.at[roster_index, "status"] = "confirmed"
            roster.at[roster_index, "source_url"] = QUOTATIONS_URL
            roster.at[roster_index, "checked_at"] = checked_at

    if adopt_unmatched:
        unmatched = matches.loc[matches["roster_index"] < 0, "price_index"]
        roster_norm = roster["player"].astype(str).map(normalize_name)
        roster_tails = roster["player"].astype(str).map(_surname_tail)
        checked_at = datetime.now(UTC).isoformat()
        new_rows: list[dict] = []
        adopted_clubs: dict[str, int] = {}
        for price_index in unmatched:
            price_row = prices.loc[price_index]
            club = FANTACALCIO_TEAM_CODES.get(str(price_row.get("team", "")).strip().upper())
            if club is None:
                continue
            name = str(price_row["player"])
            role = str(price_row.get("role_classic", "") or "").upper()
            tail = _surname_tail(name)
            core_tokens = [
                token for token in normalize_name(name).split() if token
            ]
            while len(core_tokens) > 1 and len(core_tokens[-1]) <= 2:
                core_tokens.pop()
            surname_only = len(core_tokens) == 1
            other_club = roster_tails.eq(tail) & roster[club_column].astype(str).ne(club)
            # A surname-only quotation for a player confirmed at another club
            # with the same role is a missed transfer: move the assertion.
            same_player = (
                other_club & roster["status"].eq("confirmed")
                & surname_only
                & roster["role"].astype(str).str.upper().eq(role)
            )
            # Namesakes (initial or first-name mismatch) are different people.
            namesake = other_club & roster["status"].eq("confirmed") & roster["player"].map(
                lambda other: _namesake(name, str(other))
            )
            # Otherwise a same-tail confirmed row at another club is just a
            # namesake; adopt without touching it.
            conflict = (
                other_club & roster["status"].eq("confirmed")
                & ~same_player & ~namesake
            )
            stale = other_club & roster["status"].eq("watchlist")
            if conflict.any():
                report["adopt_conflicts"] += int(conflict.sum())
                continue
            exact_here = roster.index[
                (roster_norm == normalize_name(name)) & roster[club_column].astype(str).eq(club)
            ]
            if exact_here.any():
                continue
            row = {column: "" for column in roster.columns}
            row.update({
                "player": name,
                "club": club,
                club_column: club,
                "role": role,
                "status": "confirmed",
                "source_url": QUOTATIONS_URL,
                "checked_at": checked_at,
            })
            new_rows.append(row)
            moved = int(len(roster.index[same_player | stale]))
            report["excluded_stale"] += moved
            if apply:
                roster.loc[roster.index[same_player | stale], ["status", "source_url", "checked_at"]] = [
                    "excluded", QUOTATIONS_URL, checked_at,
                ]
            adopted_clubs[club] = adopted_clubs.get(club, 0) + 1
        report["adopted"] = len(new_rows)
        if apply and new_rows:
            roster = pd.concat([roster, pd.DataFrame(new_rows)], ignore_index=True)
        for club, count in adopted_clubs.items():
            report["per_club"][club] = report["per_club"].get(club, 0) + count

    if apply:
        roster.to_csv(roster_path, index=False)
        report["applied"] = True
        report["checked_at"] = checked_at
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", default="2627")
    parser.add_argument("--roster", type=Path)
    parser.add_argument("--prices", type=Path)
    parser.add_argument("--apply", action="store_true", help="Write promotions to the roster CSV")
    parser.add_argument(
        "--adopt-unmatched", action="store_true",
        help="Also adopt priced players with no roster row as confirmed (quotation evidence)",
    )
    args = parser.parse_args()
    season_dir = config.get_season_dir(args.season)
    suffix = season_dir.name.removeprefix("season_")
    roster_path = args.roster or season_dir / "rosters" / f"virgilio_rosters_{suffix}.csv"
    prices_path = args.prices or season_dir / "fantacalcio" / "prices.csv"
    report = promote(roster_path, prices_path, apply=args.apply, adopt_unmatched=args.adopt_unmatched)
    print(f"\nRoster: {roster_path}")
    print(f"Prices: {prices_path}")
    for key, value in report.items():
        if key != "per_club":
            print(f"{key}: {value}")
    if report["per_club"]:
        print("per_club:")
        for club, count in report["per_club"].items():
            print(f"  {club}: {count}")
    if not args.apply:
        print("\nDry run only. Re-run with --apply to write the promotions.")


if __name__ == "__main__":
    main()
