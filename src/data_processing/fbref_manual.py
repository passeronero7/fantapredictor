"""Load FBref tables exported manually from a browser.

FBref is intentionally not accessed by this project. The caller supplies CSV
exports from the season's ``manual`` directory, and this module only validates
and loads those local files.
"""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd

EXPORTS = {
    "scouting": "fbref_scouting_{season}.csv",
    "standard": "fbref_standard_{season}.csv",
    "shooting": "fbref_shooting_{season}.csv",
    "passing": "fbref_passing_{season}.csv",
    "pass_types": "fbref_pass_types_{season}.csv",
    "goal_shot_creation": "fbref_goal_shot_creation_{season}.csv",
    "defense": "fbref_defense_{season}.csv",
    "possession": "fbref_possession_{season}.csv",
    "playing_time": "fbref_playing_time_{season}.csv",
    "misc": "fbref_misc_{season}.csv",
    "keeper": "fbref_keeper_{season}.csv",
    "advanced_keeper": "fbref_advanced_keeper_{season}.csv",
}


def normalize_fbref_export(
    source_path: str | Path,
    destination_path: str | Path,
) -> int:
    """Normalize a raw browser-copied FBref CSV into an import-ready CSV.

    FBref's CSV dialog prepends citation lines and a group-header row before the
    actual column header. It also repeats labels such as ``Gls`` for totals and
    per-90 values. This offline helper removes only the preamble, retains data
    rows, and gives repeated labels their table-group prefix.
    """
    source = Path(source_path)
    destination = Path(destination_path)
    with source.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))

    header_index = next(
        (
            index for index, row in enumerate(rows)
            if len(row) >= 2 and row[0].strip().lower() == "rk"
            and row[1].strip().lower() == "player"
        ),
        None,
    )
    if header_index is None:
        raise ValueError(f"FBref CSV has no Rk,Player header: {source}")

    header = rows[header_index]
    group_header = rows[header_index - 1] if header_index else []
    columns = _normalized_columns(header, group_header)
    data_rows = [
        row for row in rows[header_index + 1:]
        if row and row[0].strip().isdigit()
    ]
    malformed = [row for row in data_rows if len(row) != len(header)]
    if malformed:
        raise ValueError(f"FBref CSV has malformed data rows: {source}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        writer.writerows(data_rows)
    return len(data_rows)


def _normalized_columns(header: list[str], group_header: list[str]) -> list[str]:
    """Return stable, unique headers while preserving FBref table semantics."""
    cleaned = [_base_column_name(column) for column in header]
    counts = Counter(cleaned)
    columns: list[str] = []
    for index, column in enumerate(cleaned):
        if counts[column] > 1:
            group = group_header[index].strip() if index < len(group_header) else ""
            column = f"{group or 'Metric'} {column}"
        columns.append(column)
    if len(set(columns)) != len(columns):
        raise ValueError("FBref CSV still has ambiguous columns after normalization")
    return columns


def _base_column_name(column: str) -> str:
    """Map non-statistical FBref export labels to explicit identifier names."""
    value = column.strip()
    if value.lower() == "rk":
        return "rank"
    if value == "-9999":
        return "fbref_player_id"
    return value


def load_manual_exports(manual_dir: str | Path, season: str) -> dict[str, pd.DataFrame]:
    """Load available local FBref CSV exports for ``season``.

    Missing exports are allowed so that the rest of the offline pipeline can
    run without FBref data. Present exports must contain a player identifier.
    """
    import pandas as pd

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
