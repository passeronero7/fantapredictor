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


def fetch_league_data(session: requests.Session, league: str, season: int) -> tuple[dict, str]:
    """Fetch and minimally validate the league snapshot displayed by Understat."""
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
    dates = payload.get("dates")
    if not isinstance(dates, list) or not dates:
        raise ValueError("Understat response has no match rows")
    return payload, response.url


def fetch_players(session: requests.Session, league: str, season: int) -> tuple[list[dict], str]:
    """Fetch players while preserving the original public helper contract."""
    payload, source_url = fetch_league_data(session, league, season)
    return payload["players"], source_url


def build_frame(players: list[dict], season: int, checked_at: str) -> pd.DataFrame:
    """Add warehouse provenance columns without changing provider values."""
    frame = pd.DataFrame.from_records(players)
    frame["league"] = "Serie_A"
    frame["year"] = season
    frame["season"] = f"{season}/{(season + 1) % 100:02d}"
    frame["primary_position"] = frame.get("position", "")
    frame["scrape_timestamp"] = checked_at
    return frame


def build_match_frame(dates: list[dict], season: int, checked_at: str) -> pd.DataFrame:
    """Normalize completed league fixtures with scores, xG, and matchdays."""
    club_ids = {
        str(side.get("id"))
        for match in dates
        for side in (match.get("h", {}), match.get("a", {}))
        if side.get("id") is not None
    }
    matches_per_round = len(club_ids) // 2
    if matches_per_round <= 0:
        raise ValueError("Understat match rows contain no league clubs")

    records = []
    for index, match in enumerate(dates):
        if not match.get("isResult"):
            continue
        home = match.get("h", {})
        away = match.get("a", {})
        goals = match.get("goals", {})
        xg = match.get("xG", {})
        records.append({
            "match_id": match.get("id"),
            "matchday": index // matches_per_round + 1,
            "match_date": match.get("datetime"),
            "home_team": home.get("title"),
            "home_team_id": home.get("id"),
            "away_team": away.get("title"),
            "away_team_id": away.get("id"),
            "home_goals": goals.get("h"),
            "away_goals": goals.get("a"),
            "home_xg": xg.get("h"),
            "away_xg": xg.get("a"),
            "league": "Serie_A",
            "year": season,
            "season": f"{season}/{(season + 1) % 100:02d}",
            "scrape_timestamp": checked_at,
        })
    if not records:
        raise ValueError("Understat response has no completed match rows")
    return pd.DataFrame.from_records(records)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, default=2026, help="start year, e.g. 2026")
    parser.add_argument("--league", default="Serie_A")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    checked_at = datetime.now(UTC).isoformat()
    with requests.Session() as session:
        payload, source_url = fetch_league_data(session, args.league, args.season)
    frame = build_frame(payload["players"], args.season, checked_at)
    matches = build_match_frame(payload["dates"], args.season, checked_at)
    output = args.output or (
        config.get_season_dir(f"{args.season % 100:02d}{(args.season + 1) % 100:02d}") /
        "raw" / f"understat_serie_a_{args.season}_season.csv"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output, index=False)
    if output.name.endswith("_season.csv"):
        matches_output = output.with_name(output.name.replace("_season.csv", "_matches.csv"))
    else:
        matches_output = output.with_name(f"{output.stem}_matches.csv")
    matches.to_csv(matches_output, index=False)
    print(f"players: {len(frame)}")
    print(f"completed_matches: {len(matches)}")
    print(f"source: {source_url}")
    print(f"checked_at: {checked_at}")
    print(f"output: {output}")
    print(f"matches_output: {matches_output}")


if __name__ == "__main__":
    main()
