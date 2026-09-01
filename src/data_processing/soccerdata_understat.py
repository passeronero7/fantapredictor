"""Retrieve Serie A player-season data through :mod:`soccerdata`.

The public warehouse already accepts the historical Understat aggregate CSV
shape.  This adapter deliberately exports that same shape, which lets a fresh
``soccerdata`` snapshot be ingested without adding a second database loader.
"""

from __future__ import annotations

import importlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from src.db.ingestors.common import season_label as _season_label

UNDERSTAT_LEAGUE = "ITA-Serie A"
UNDERSTAT_URL_TEMPLATE = "https://understat.com/league/Serie_A/{start_year}"
ARCHIVE_COLUMNS = [
    "player_name",
    "id",
    "team_title",
    "year",
    "league",
    "primary_position",
    "games",
    "time",
    "goals",
    "assists",
    "npg",
    "npxG",
    "xG",
    "xA",
    "shots",
    "key_passes",
    "yellow_cards",
    "red_cards",
    "xGChain",
    "xGBuildup",
]


def season_start_year(season: str | int) -> int:
    """Return the start year from compact or human-readable season input."""
    text = str(season).strip().replace("_", "-").replace("/", "-")
    if len(text) == 4 and text.isdigit():
        # Delegate compact-code disambiguation to the canonical parser used by
        # the warehouse ingestors: a heuristic keyed on the leading two digits
        # (e.g. "not 19 or 20") misreads compact codes like "1920" (2019/20)
        # or "2021" (2020/21) as literal years, mislabeling the season.
        return int(_season_label(text).split("/")[0])
    if len(text) == 7 and text[4] == "-" and text[:4].isdigit() and text[5:].isdigit():
        start_year, end_year = int(text[:4]), int(text[5:])
        if end_year != (start_year + 1) % 100:
            raise ValueError(f"Invalid season range: {season!r}")
        return start_year
    raise ValueError(f"Unsupported season value: {season!r}")


def compact_season(season: str | int) -> str:
    """Return a compact ``YYZZ`` code for a season input."""
    start_year = season_start_year(season)
    return f"{start_year % 100:02d}{(start_year + 1) % 100:02d}"


def to_understat_archive(frame: pd.DataFrame, start_year: int) -> pd.DataFrame:
    """Convert soccerdata's player-season frame to the warehouse CSV contract."""
    flattened = frame.reset_index()
    required = {
        "player", "player_id", "team", "position", "matches", "minutes", "goals",
        "assists", "np_goals", "np_xg", "xg", "xa", "shots", "key_passes",
        "yellow_cards", "red_cards", "xg_chain", "xg_buildup",
    }
    missing = sorted(required.difference(flattened.columns))
    if missing:
        raise ValueError(f"soccerdata Understat response is missing columns: {', '.join(missing)}")

    archive = pd.DataFrame({
        "player_name": flattened["player"],
        "id": flattened["player_id"],
        "team_title": flattened["team"],
        "year": start_year,
        "league": "Serie_A",
        "primary_position": flattened["position"],
        "games": flattened["matches"],
        "time": flattened["minutes"],
        "goals": flattened["goals"],
        "assists": flattened["assists"],
        "npg": flattened["np_goals"],
        "npxG": flattened["np_xg"],
        "xG": flattened["xg"],
        "xA": flattened["xa"],
        "shots": flattened["shots"],
        "key_passes": flattened["key_passes"],
        "yellow_cards": flattened["yellow_cards"],
        "red_cards": flattened["red_cards"],
        "xGChain": flattened["xg_chain"],
        "xGBuildup": flattened["xg_buildup"],
    })
    return archive.loc[:, ARCHIVE_COLUMNS].sort_values(["team_title", "player_name"]).reset_index(drop=True)


def download_player_season_stats(
    season: str | int,
    output_dir: str | Path,
    *,
    overwrite: bool = False,
    reader_factory: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Download, normalize, and record one Serie A Understat season.

    ``reader_factory`` is injectable to keep unit tests entirely offline.
    """
    start_year = season_start_year(season)
    season_code = compact_season(season)
    output_dir = Path(output_dir)
    csv_path = output_dir / f"understat_soccerdata_player_season_{season_code}.csv"
    manifest_path = output_dir / f"understat_soccerdata_player_season_{season_code}.json"
    if not overwrite and (csv_path.exists() or manifest_path.exists()):
        raise FileExistsError(
            f"Snapshot already exists for {season_code}; use --overwrite to refresh it: {csv_path}"
        )

    if reader_factory is None:
        soccerdata = importlib.import_module("soccerdata")
        reader_factory = soccerdata.Understat

    cache_dir = output_dir / "cache"
    reader = reader_factory(
        leagues=UNDERSTAT_LEAGUE,
        seasons=start_year,
        data_dir=cache_dir,
    )
    archive = to_understat_archive(reader.read_player_season_stats(), start_year)

    output_dir.mkdir(parents=True, exist_ok=True)
    archive.to_csv(csv_path, index=False)
    retrieved_at = datetime.now(UTC).isoformat()
    report = {
        "provider": "Understat",
        "client": "soccerdata",
        "league": UNDERSTAT_LEAGUE,
        "season": f"{start_year}/{(start_year + 1) % 100:02d}",
        "retrieved_at": retrieved_at,
        "source_url": UNDERSTAT_URL_TEMPLATE.format(start_year=start_year),
        "rows": len(archive),
        "columns": ARCHIVE_COLUMNS,
        "data_file": csv_path.name,
    }
    manifest_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return {**report, "data_path": str(csv_path), "manifest_path": str(manifest_path)}
