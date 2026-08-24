#!/usr/bin/env python3
"""Create a dated Serie A watchlist snapshot and open-data player histories.

The roster source is a public, current-season listing and may change while the
transfer window is open. Historical rows come from a public Understat-derived
dataset covering six leagues from 2014/15 onward. Neither source supplies
Fantacalcio roles or votes, so those must be reconciled separately.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup

# Allow direct execution with `python scripts/download_baseline_data.py`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config.settings import config
from src.utils.name_matching import normalize_name

ROSTER_URL = "https://sport.virgilio.it/calcio/giocatori/"
HISTORY_URL = (
    "https://raw.githubusercontent.com/vibedatascience/"
    "understat_players_aggregated/main/understat_players_aggregated_2014_td.csv"
)
CLUBS = {
    "Atalanta", "Bologna", "Cagliari", "Como", "Fiorentina", "Frosinone",
    "Genoa", "Inter", "Juventus", "Lazio", "Lecce", "Milan", "Monza",
    "Napoli", "Parma", "Roma", "Sassuolo", "Torino", "Udinese", "Venezia",
}
HEADERS = {"User-Agent": "FantacalcioResearch/0.1 (personal research)"}


def parse_rosters(html: str, checked_at: str) -> pd.DataFrame:
    """Extract club/player records from the roster page without network access."""
    soup = BeautifulSoup(html, "lxml")
    records: list[dict[str, str]] = []
    for heading in soup.find_all("h3"):
        club = heading.get_text(" ", strip=True)
        if club not in CLUBS:
            continue
        player_list = heading.find_next("ul")
        if player_list is None:
            continue
        for item in player_list.find_all("li", recursive=False):
            player = item.get_text(" ", strip=True)
            if player:
                records.append({
                    "club_2026_27": club,
                    "club": club,
                    "player": player,
                    "player_normalized": normalize_name(player),
                    "role": "",
                    "source_url": ROSTER_URL,
                    "checked_at": checked_at,
                    # A public roster listing is not proof of registration or a
                    # confirmed transfer. Manual reconciliation must promote it.
                    "status": "watchlist",
                })
    roster = pd.DataFrame.from_records(records)
    if roster.empty or roster["club_2026_27"].nunique() != len(CLUBS):
        raise ValueError("Roster source did not contain all 20 expected Serie A clubs")
    return roster.drop_duplicates(["club_2026_27", "player"]).sort_values(
        ["club_2026_27", "player"]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", default="2627")
    args = parser.parse_args()

    season_dir = config.get_season_dir(args.season)
    raw_dir = season_dir / "raw"
    roster_dir = season_dir / "rosters"
    history_dir = season_dir / "historical"
    report_dir = season_dir / "reports"
    for directory in (raw_dir, roster_dir, history_dir, report_dir):
        directory.mkdir(parents=True, exist_ok=True)

    checked_at = datetime.now(UTC).isoformat()
    response = requests.get(ROSTER_URL, headers=HEADERS, timeout=30)
    response.raise_for_status()
    roster = parse_rosters(response.text, checked_at)
    roster_path = roster_dir / "virgilio_rosters_2026_27.csv"
    roster.to_csv(roster_path, index=False)

    raw_path = raw_dir / "understat_players_aggregated_2014_td.csv"
    history_response = requests.get(HISTORY_URL, headers=HEADERS, timeout=90)
    history_response.raise_for_status()
    raw_path.write_bytes(history_response.content)

    history = pd.read_csv(raw_path)
    history["player_normalized"] = history["player_name"].map(normalize_name)
    roster_ids = roster[["club_2026_27", "player", "player_normalized"]]
    matched_history = history.merge(roster_ids, on="player_normalized", how="inner")
    matched_history = matched_history.drop(columns=["player_normalized"])
    matched_history = matched_history.sort_values(
        ["club_2026_27", "player", "year", "league", "team_title"]
    )
    history_path = history_dir / "understat_open_league_history_for_roster.csv"
    matched_history.to_csv(history_path, index=False)

    matched_players = set(matched_history["player"].unique())
    report = {
        "season": args.season,
        "checked_at": checked_at,
        "roster_source": ROSTER_URL,
        "history_source": HISTORY_URL,
        "clubs": int(roster["club_2026_27"].nunique()),
        "roster_players": int(len(roster)),
        "players_with_open_history": int(len(matched_players)),
        "players_without_open_history": int(len(roster) - len(matched_players)),
        "historical_rows": int(len(matched_history)),
        "history_seasons": sorted(matched_history["season"].dropna().unique().tolist()),
        "note": (
            "Name matching is provisional. Review unmatched players and duplicate names "
            "before modelling; Understat IDs are retained in the history export."
        ),
    }
    (report_dir / "baseline_download_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
