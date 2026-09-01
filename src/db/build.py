"""Manifest-driven resolution and orchestration for warehouse source loading.

Centralizes the path conventions that ``scripts/build_database.py`` used to
apply through ad hoc globs into one place, and layers per-source
checksum-skip and error isolation on top of the existing ingestors without
changing their row-upsert logic. See ``docs/ingestion_and_fixing_strategy.md``
(Strategy B) for the design this implements.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from config.settings import config
from src.db.ingestors import coaches, fbref, football_data, prices, rosters, understat, votes
from src.db.ingestors.common import season_label

MANIFEST_FILE = Path(__file__).resolve().parents[2] / "config" / "data_sources.json"

# Each declared "kind" maps to the existing per-source ingestor entry point.
# `takes_season` controls whether the resolved compact season code is passed
# through as the loader's `season` argument; the ingestors' own row-upsert
# and start_run/finish_run bookkeeping are untouched, only wrapped.
_LOADERS: dict[str, tuple[Callable[..., int], bool]] = {
    "roster": (rosters.load, True),
    "player-season": (understat.load, False),
    "understat-matches": (understat.load_matches, False),
    "votes": (votes.load, True),
    "match-results-tree": (football_data.load, False),
    "prices": (prices.load, True),
    "coaches": (coaches.load, False),
    "fbref-manual": (fbref.load, True),
}


@dataclass(frozen=True)
class IngestSource:
    """One resolved, on-disk manifest entry ready to hand to an ingestor."""

    key: str  # unique per resolved entry, e.g. "votes:1516"
    slug: str  # manifest entry slug shared across seasons, e.g. "votes"
    kind: str
    path: Path
    season: str | None  # compact season code, or None for season-agnostic sources

    def checksum(self) -> str:
        """SHA-256 over the file, or over every file's path+size+hash in a directory."""
        digest = hashlib.sha256()
        if self.path.is_dir():
            for file_path in sorted(self.path.rglob("*")):
                if not file_path.is_file():
                    continue
                digest.update(file_path.relative_to(self.path).as_posix().encode("utf-8"))
                digest.update(str(file_path.stat().st_size).encode("utf-8"))
                digest.update(_file_sha256(file_path).encode("utf-8"))
        else:
            digest.update(_file_sha256(self.path).encode("utf-8"))
        return digest.hexdigest()


@dataclass(frozen=True)
class SourceResult:
    key: str
    status: str  # "ok" | "error" | "skipped"
    rows: int
    detail: str | None = None


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest(manifest_file: str | Path | None = None) -> list[dict]:
    """Return the declared source entries from ``config/data_sources.json``."""
    path = Path(manifest_file) if manifest_file else MANIFEST_FILE
    manifest = json.loads(path.read_text(encoding="utf-8"))
    return manifest["sources"]


def resolve_sources(
    target_season: str,
    manifest_file: str | Path | None = None,
    data_dir: str | Path | None = None,
) -> list[IngestSource]:
    """Expand every manifest entry into concrete sources that exist on disk."""
    data_dir = Path(data_dir) if data_dir else config.DATA_DIR
    target_season = _compact(target_season)
    resolved: list[IngestSource] = []
    for entry in load_manifest(manifest_file):
        for season_code in _season_codes(entry["seasons"], target_season, data_dir):
            candidate = _expand_path(entry, season_code, data_dir)
            if not candidate.exists():
                continue
            key = entry["slug"] if season_code is None else f"{entry['slug']}:{season_code}"
            resolved.append(
                IngestSource(
                    key=key, slug=entry["slug"], kind=entry["kind"],
                    path=candidate, season=season_code,
                )
            )
    return resolved


def _season_codes(
    directive: list[str | None], target_season: str, data_dir: Path
) -> list[str | None]:
    if directive == ["*"]:
        return _discover_seasons(data_dir)
    if directive == ["$target"]:
        return [target_season]
    if directive == [None]:
        return [None]
    return [_compact(code) for code in directive]


def _discover_seasons(data_dir: Path) -> list[str]:
    """Return every compact season code with an on-disk ``season_YYYY_YY`` dir."""
    codes = []
    for season_dir in sorted(data_dir.glob("season_*")):
        parts = season_dir.name.removeprefix("season_").split("_")
        if len(parts) != 2 or not all(part.isdigit() for part in parts):
            continue
        codes.append(f"{parts[0][-2:]}{parts[1]}")
    return codes


def _compact(season: str) -> str:
    return str(season).strip().replace("/", "").replace("-", "").replace("_", "")


def _season_dir(data_dir: Path, season_code: str) -> Path:
    """Match ``config.Config.get_season_dir``'s naming, parameterized on ``data_dir``."""
    start, end = season_label(season_code).split("/")
    return data_dir / f"season_{start}_{end}"


def _expand_path(entry: dict, season_code: str | None, data_dir: Path) -> Path:
    pattern = entry["pattern"]
    if season_code is not None:
        label = season_label(season_code)
        start_year = label.split("/", 1)[0]
        pattern = pattern.format(
            season_compact=season_code,
            season_underscore=label.replace("/", "_"),
            start_year=start_year,
        )
    root = data_dir if entry["root"] == "data_dir" else _season_dir(data_dir, season_code)
    return root / pattern


def load_source(conn: sqlite3.Connection, source: IngestSource) -> int:
    """Call the ingestor for one resolved source (no skip/error handling)."""
    loader, takes_season = _LOADERS[source.kind]
    if takes_season:
        return loader(conn, source.path, source.season)
    return loader(conn, source.path)


def load_one_source(
    conn: sqlite3.Connection, source: IngestSource, force: bool = False
) -> SourceResult:
    """Load one resolved source with checksum-skip and per-source error isolation.

    Unchanged sources (matching checksum, previously ``ok``) are skipped
    unless ``force``. A failing source is rolled back and recorded but never
    raises -- callers see the failure in the returned ``SourceResult`` and
    can continue with the remaining sources.
    """
    checksum = source.checksum()
    if not force and _already_loaded(conn, source.key, checksum):
        return SourceResult(source.key, "skipped", 0)
    try:
        rows = load_source(conn, source)
        conn.commit()
        _record_checksum(conn, source.key, checksum, "ok", rows, None)
        return SourceResult(source.key, "ok", rows)
    except Exception as exc:
        conn.rollback()
        detail = f"{exc}\n{traceback.format_exc()}"
        _record_checksum(conn, source.key, checksum, "error", 0, detail)
        return SourceResult(source.key, "error", 0, str(exc))


def run_manifest(
    conn: sqlite3.Connection,
    target_season: str,
    manifest_file: str | Path | None = None,
    data_dir: str | Path | None = None,
    force: bool = False,
) -> list[SourceResult]:
    """Load every resolved manifest source; see :func:`load_one_source`."""
    return [
        load_one_source(conn, source, force=force)
        for source in resolve_sources(target_season, manifest_file, data_dir)
    ]


def _already_loaded(conn: sqlite3.Connection, source_key: str, checksum: str) -> bool:
    row = conn.execute(
        "SELECT status FROM source_checksums WHERE source_key = ? AND checksum = ?",
        (source_key, checksum),
    ).fetchone()
    return row is not None and row["status"] == "ok"


def _record_checksum(
    conn: sqlite3.Connection,
    source_key: str,
    checksum: str,
    status: str,
    rows: int,
    detail: str | None,
) -> None:
    conn.execute(
        """INSERT INTO source_checksums
               (source_key, checksum, status, rows_loaded, detail, updated_at)
           VALUES (?, ?, ?, ?, ?, datetime('now'))
           ON CONFLICT(source_key) DO UPDATE SET
             checksum=excluded.checksum, status=excluded.status,
             rows_loaded=excluded.rows_loaded, detail=excluded.detail,
             updated_at=excluded.updated_at""",
        (source_key, checksum, status, rows, detail),
    )
    conn.commit()
