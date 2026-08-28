#!/usr/bin/env python3
"""Download one public Understat league-season snapshot for local research.

The endpoint is the same read-only data request made by Understat's league
page. It is intentionally one request per invocation; do not use this script
to evade access controls, bulk-harvest, or bypass a provider's terms.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config.settings import config

UNDERSTAT_URL = "https://understat.com/getLeagueData/{league}/{season}"
HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://understat.com/league/Serie_A/{season}",
    "User-Agent": "FantaPredictor/0.5 (personal research; contact repository owner)",
    "X-Requested-With": "XMLHttpRequest",
}


def fetch_players(session: requests.Session, league: str, season: int) -> tuple[list[dict], str]:
    """Fetch and minimally validate the player table displayed by Understat."""
    response = session.get(
        UNDERSTAT_URL.format(league=league.replace("_", " "), season=season),
        headers={key: value.format(season=season) for key, value in HEADERS.items()},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    players = payload.get("players")
    if not isinstance(players, list) or not players:
        raise ValueError("Understat response has no player rows")
    required = {"id", "player_name", "team_title", "time", "xG", "xA", "xGChain", "xGBuildup"}
    missing = required - set(players[0])
    if missing:
        raise ValueError(f"Understat response is missing columns: {', '.join(sorted(missing))}")
    return players, response.url


def build_frame(players: list[dict], season: int, checked_at: str) -> pd.DataFrame:
    """Add warehouse provenance columns without changing provider values."""
    frame = pd.DataFrame.from_records(players)
    frame["league"] = "Serie_A"
    frame["year"] = season
    frame["season"] = f"{season}/{(season + 1) % 100:02d}"
    frame["primary_position"] = frame.get("position", "")
    frame["scrape_timestamp"] = checked_at
    return frame


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, default=2026, help="start year, e.g. 2026")
    parser.add_argument("--league", default="Serie_A")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    checked_at = datetime.now(UTC).isoformat()
    with requests.Session() as session:
        players, source_url = fetch_players(session, args.league, args.season)
    frame = build_frame(players, args.season, checked_at)
    output = args.output or (
        config.get_season_dir(f"{args.season % 100:02d}{(args.season + 1) % 100:02d}") /
        "raw" / f"understat_serie_a_{args.season}_season.csv"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output, index=False)
    print(f"players: {len(frame)}")
    print(f"source: {source_url}")
    print(f"checked_at: {checked_at}")
    print(f"output: {output}")


if __name__ == "__main__":
    main()
