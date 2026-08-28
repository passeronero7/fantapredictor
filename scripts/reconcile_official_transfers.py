#!/usr/bin/env python3
"""Reconcile the current roster with public Lega Serie A transfer registrations.

The source is Lega Serie A's public Calciomercato feed. This script treats a
record as proof of the directed transfer only. It never invents a Fantacalcio
role: rows whose official role is missing remain ``watchlist`` so model and
auction eligibility continues to fail closed.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config.settings import config
from src.utils.name_matching import normalize_name

FEED_URL = "https://dapi.legaseriea.it/v2/content/it-it/playertransfers"
ROLE_MAP = {
    "portiere": "P",
    "difensore": "D",
    "centrocampista": "C",
    "attaccante": "A",
}
CLUB_CODES = {
    "ATA": "Atalanta", "BOL": "Bologna", "CAG": "Cagliari", "COM": "Como",
    "FIO": "Fiorentina", "FRO": "Frosinone", "GEN": "Genoa", "INT": "Inter",
    "JUV": "Juventus", "LAZ": "Lazio", "LEC": "Lecce", "MIL": "Milan",
    "MON": "Monza", "NAP": "Napoli", "PAR": "Parma", "ROM": "Roma",
    "SAS": "Sassuolo", "TOR": "Torino", "UDI": "Udinese", "VEN": "Venezia",
}
HEADERS = {
    "Accept": "application/json",
    "User-Agent": "FantaPredictor/0.5 (personal research; contact repository owner)",
}


def fetch_transfers(session: requests.Session) -> tuple[list[dict], list[dict]]:
    """Follow the official feed's pagination and return all displayed entries."""
    url: str | None = FEED_URL
    items: list[dict] = []
    payloads: list[dict] = []
    while url:
        response = session.get(url, headers=HEADERS, timeout=30)
        response.raise_for_status()
        payload = response.json()
        page_items = payload.get("items")
        if not isinstance(page_items, list):
            raise ValueError("Lega Serie A transfer response has no items list")
        items.extend(page_items)
        payloads.append(payload)
        url = payload.get("pagination", {}).get("nextUrl")
    return items, payloads


def normalize_transfers(items: list[dict]) -> pd.DataFrame:
    """Keep only incoming Serie A moves, preserving original official fields."""
    records: list[dict[str, str]] = []
    for item in items:
        fields = item.get("fields", {})
        club = CLUB_CODES.get(str(fields.get("clubTo3Code", "")).strip().upper())
        surname = str(fields.get("playerSurname", "")).strip()
        given_name = str(fields.get("playerName", "")).strip()
        player = " ".join(part for part in (given_name, surname) if part)
        if not club or not player:
            continue
        role = ROLE_MAP.get(str(fields.get("role", "")).strip().lower(), "")
        records.append({
            "player": player,
            "player_normalized": normalize_name(player),
            "club": club,
            "role": role,
            "official_role": str(fields.get("role", "")).strip(),
            "transfer_type": str(fields.get("transferType", "")).strip(),
            "transfer_date": str(fields.get("transferDate", "")).strip(),
            "source_url": str(item.get("selfUrl", FEED_URL)),
        })
    if not records:
        raise ValueError("No incoming Serie A player transfers were found")
    transfers = pd.DataFrame.from_records(records)
    transfers = transfers.sort_values("transfer_date").drop_duplicates(
        "player_normalized", keep="last"
    )
    return transfers.sort_values(["club", "player"]).reset_index(drop=True)


def reconcile_roster(roster: pd.DataFrame, transfers: pd.DataFrame, checked_at: str) -> tuple[pd.DataFrame, dict[str, int]]:
    """Apply formal incoming moves while retaining unresolved-role safety."""
    required = {"player", "role", "status", "source_url", "checked_at"}
    missing = required - set(roster.columns)
    if missing:
        raise ValueError(f"Roster is missing required columns: {', '.join(sorted(missing))}")
    result = roster.copy()
    club_column = "club_2026_27" if "club_2026_27" in result.columns else "club"
    if "club" not in result.columns:
        result["club"] = result[club_column]
    result["player_normalized"] = result["player"].map(normalize_name)
    counters = {"updated": 0, "created": 0, "excluded_previous": 0, "confirmed": 0, "watchlist": 0}
    for move in transfers.to_dict("records"):
        same_player = result["player_normalized"].eq(move["player_normalized"])
        destination = same_player & result[club_column].astype(str).eq(move["club"])
        status = "confirmed" if move["role"] else "watchlist"
        if destination.any():
            index = result.index[destination][0]
            result.loc[index, ["role", "status", "source_url", "checked_at"]] = [
                move["role"] or result.at[index, "role"], status, move["source_url"], checked_at,
            ]
            counters["updated"] += 1
        else:
            row = {column: "" for column in result.columns}
            row.update({
                "player": move["player"], "player_normalized": move["player_normalized"],
                "club": move["club"], club_column: move["club"], "role": move["role"],
                "status": status, "source_url": move["source_url"], "checked_at": checked_at,
            })
            result = pd.concat([result, pd.DataFrame([row])], ignore_index=True)
            counters["created"] += 1
        old_rows = same_player & ~result[club_column].astype(str).eq(move["club"])
        if old_rows.any():
            result.loc[old_rows, ["status", "source_url", "checked_at"]] = [
                "excluded", move["source_url"], checked_at,
            ]
            counters["excluded_previous"] += int(old_rows.sum())
        counters[status] += 1
    result = result.drop(columns=["player_normalized"]).drop_duplicates(
        ["player", club_column], keep="last"
    ).sort_values([club_column, "player"]).reset_index(drop=True)
    return result, counters


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", default="2627")
    parser.add_argument("--roster", type=Path)
    parser.add_argument("--raw-output", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    season_dir = config.get_season_dir(args.season)
    suffix = season_dir.name.removeprefix("season_")
    roster_path = args.roster or season_dir / "rosters" / f"virgilio_rosters_{suffix}.csv"
    raw_output = args.raw_output or season_dir / "raw" / f"lega_serie_a_transfers_{suffix}.json"
    report_path = args.report or season_dir / "reports" / f"official_transfer_reconciliation_{suffix}.json"
    checked_at = datetime.now(UTC).isoformat()
    with requests.Session() as session:
        items, payloads = fetch_transfers(session)
    transfers = normalize_transfers(items)
    roster = pd.read_csv(roster_path)
    reconciled, counters = reconcile_roster(roster, transfers, checked_at)
    raw_output.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    raw_output.write_text(json.dumps(payloads, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    reconciled.to_csv(roster_path, index=False)
    report = {
        "season": args.season,
        "checked_at": checked_at,
        "feed_url": FEED_URL,
        "source_entries": len(items),
        "latest_unique_incoming_transfers": len(transfers),
        **counters,
        "role_note": "Only official role labels mapped to P/D/C/A are confirmed; blank roles remain watchlist.",
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
