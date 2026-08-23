"""SQLite database connection and schema management for the research warehouse.

Only the Python standard library is required at runtime (SQLite is part of the
standard library).  Any member of this package may import `pandas` and
`requests` lazily inside functions so that pure-DB operations stay lightweight.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_FILE = Path(__file__).parent / "schema.sql"

# Sources are registered once, keyed by slug. `licence` is a human-readable
# summary of the terms we are relying on; every row lands in the `sources`
# table so the DB is self-describing.
DEFAULT_SOURCES = [
    {
        "slug": "leaf-node-manual",
        "name": "LeafNode Research DB (manual QC)",
        "homepage_url": None,
        "licence": "Internal research; owned by the repository operator",
        "notes": ("Hand-curated rows validated by a human. No automatic "
                  "population yet."),
    },
    {
        "slug": "understat",
        "name": "Understat",
        "homepage_url": "https://understat.com/league/Serie_A",
        "licence": "Unclear; free to view. Data used for personal research only.",
        "notes": "xG/xA/shots player-season data, seasons 2014-2026.",
    },
    {
        "slug": "football-data.co.uk",
        "name": "Football-Data.co.uk",
        "homepage_url": "https://www.football-data.co.uk/italym.php",
        "licence": "Free for personal/research use; see site terms.",
        "notes": "Match results, half-time, shots, corners, cards, odds, per game.",
    },
    {
        "slug": "statsbomb-open-data",
        "name": "StatsBomb Open Data",
        "homepage_url": "https://github.com/statsbomb/open-data",
        "licence": "CC BY-NC-SA 4.0 (non-commercial)",
        "notes": "Fine-grained event and 360 data for selected competitions/season.",
    },
    {
        "slug": "virgilio",
        "name": "Virgilio Sport",
        "homepage_url": "https://sport.virgilio.it/calcio/giocatori/",
        "licence": "Public HTML; author prefers light usage.",
        "notes": "Provisional 2026/27 club/player rosters.",
    },
    {
        "slug": "fbref",
        "name": "FBref",
        "homepage_url": "https://fbref.com",
        "licence": "See FBref ToS. Do not scrape; use manual browser export only.",
        "notes": ("Import of manually exported FBref CSVs. Not automated because "
                  "FBref blocks requests."),
    },
]

# Teams whose "display name" differs from the common one across sources.
# {alias_in_source: canonical_name}
TEAM_ALIAS_MAP = {
    "Milan": "Milan",
    "Inter": "Inter",
    "Roma": "Roma",
    "Napoli": "Napoli",
    "Juventus": "Juventus",
    "Atalanta": "Atalanta",
    "Bologna": "Bologna",
    "Fiorentina": "Fiorentina",
    "Lazio": "Lazio",
    "Torino": "Torino",
    "Genoa": "Genoa",
    "Como": "Como",
    "Cagliari": "Cagliari",
    "Lecce": "Lecce",
    "Parma": "Parma",
    "Udinese": "Udinese",
    "Monza": "Monza",
    "Venezia": "Venezia",
    "Frosinone": "Frosinone",
    "Sassuolo": "Sassuolo",
}


def get_connection(db_path: str | Path) -> sqlite3.Connection:
    """Return a configured SQLite connection with the schema loaded."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def init_schema(conn: sqlite3.Connection, schema_file: str | Path | None = None) -> None:
    """Create all tables and indexes defined in the schema if they don't exist."""
    schema_file = Path(schema_file) if schema_file else SCHEMA_FILE
    conn.executescript(schema_file.read_text(encoding="utf-8"))
    _seed_sources(conn)
    conn.commit()


def _seed_sources(conn: sqlite3.Connection) -> None:
    """Idempotently ensure the standard sources exist in the `sources` table."""
    conn.executemany(
        """
        INSERT OR IGNORE INTO sources (slug, name, homepage_url, licence, notes)
        VALUES (:slug, :name, :homepage_url, :licence, :notes)
        """,
        DEFAULT_SOURCES,
    )
    conn.commit()


def get_or_create_club(
    conn: sqlite3.Connection,
    name: str,
    full_name: str | None = None,
    source_id: int | None = None,
    source_ref: str | None = None,
) -> int:
    """Insert a club if needed and return its primary key.

    `name` should be the canonical short display name (e.g. ``'Inter'``). Pass
    the canonical name, not an alias; aliasing is handled by the ingestors via
    :data:`TEAM_ALIAS_MAP` and the ``team_aliases`` table. If the club already
    exists it is returned as-is.
    """
    cur = conn.execute("SELECT id FROM clubs WHERE name = ?", (name,))
    if row := cur.fetchone():
        return int(row["id"])
    cur = conn.execute(
        "INSERT INTO clubs (name, full_name, source_id, source_ref) "
        "VALUES (?, ?, ?, ?)",
        (name, full_name, source_id, source_ref),
    )
    return int(cur.lastrowid)


def get_or_create_season(conn: sqlite3.Connection, name: str) -> int:
    """Return the season id for a ``'YYYY/YY'`` name, creating it if needed."""
    conn.execute("INSERT OR IGNORE INTO seasons (name, start_year) VALUES (?, ?)",
                 (name, int(name.split("/")[0])))
    cur = conn.execute("SELECT id FROM seasons WHERE name = ?", (name,))
    return int(cur.fetchone()["id"])
