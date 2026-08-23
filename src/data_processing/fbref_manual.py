"""Load FBref tables exported manually from a browser.

FBref is intentionally not accessed by this project. The caller supplies CSV
exports from the season's ``manual`` directory, and this module only validates
and loads those local files.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


EXPORTS = {
    "scouting": "fbref_scouting_{season}.csv",
    "passing": "fbref_passing_{season}.csv",
}


def load_manual_exports(manual_dir: str | Path, season: str) -> dict[str, pd.DataFrame]:
    """Load available local FBref CSV exports for ``season``.

    Missing exports are allowed so that the rest of the offline pipeline can
    run without FBref data. Present exports must contain a player identifier.
    """
    manual_dir = Path(manual_dir)
    loaded: dict[str, pd.DataFrame] = {}
    for category, pattern in EXPORTS.items():
        path = manual_dir / pattern.format(season=season)
        if not path.exists():
            continue
        frame = pd.read_csv(path)
        frame.columns = [str(column).strip() for column in frame.columns]
        player_column = next(
            (column for column in frame.columns if column.lower() in {"player", "player_name"}),
            None,
        )
        if player_column is None:
            raise ValueError(f"FBref {category} export has no player column: {path}")
        if player_column != "player":
            frame = frame.rename(columns={player_column: "player"})
        frame["source_file"] = path.name
        loaded[category] = frame
    return loaded
