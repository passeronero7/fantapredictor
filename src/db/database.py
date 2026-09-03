"""SQLite database connection and schema management for the research warehouse.

Only the Python standard library is required at runtime (SQLite is part of the
standard library).  Any member of this package may import `pandas` and
`requests` lazily inside functions so that pure-DB operations stay lightweight.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Callable

SCHEMA_FILE = Path(__file__).parent / "schema.sql"

# The integer stamped into `PRAGMA user_version` once schema.sql plus every
# migration below has been applied. Bump this whenever a new migration is
# appended; `schema.sql` itself always reflects the fully-migrated shape, so a
# freshly created database goes straight to the current version.
CURRENT_SCHEMA_VERSION = 2

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
        "slug": "fantacalcio",
        "name": "Fantacalcio.it official ratings",
        "homepage_url": "https://www.fantacalcio.it/voti-fantacalcio-serie-a",
        "licence": "See provider terms. Keep source files private unless permitted.",
        "notes": "Official matchday votes, fantavoti and bonus/malus events.",
    },
    {
        "slug": "fbref",
        "name": "FBref",
        "homepage_url": "https://fbref.com",
        "licence": "See FBref ToS. Do not scrape; use manual browser export only.",
        "notes": ("Import of manually exported FBref CSVs into provider-specific "
                  "player metrics. Not automated because FBref blocks requests."),
    },
]

# Teams whose "display name" differs from the common one across sources.
# {alias_in_source: canonical_name}
TEAM_ALIAS_MAP = {
    "Milan": "Milan",
    "AC Milan": "Milan",
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
    "Parma Calcio 1913": "Parma",
    "Udinese": "Udinese",
    "Monza": "Monza",
    "Venezia": "Venezia",
    "Frosinone": "Frosinone",
    "Sassuolo": "Sassuolo",
}


def wipe_database_file(db_path: str | Path) -> None:
    """Delete a SQLite database and its WAL/SHM sidecar files, if present.

    Used by ``--rebuild`` to guarantee a from-scratch schema; callers are
    responsible for gating this behind an explicit confirmation flag since it
    is not reversible.
    """
    db_path = Path(db_path)
    for suffix in ("", "-wal", "-shm"):
        candidate = db_path.with_name(db_path.name + suffix) if suffix else db_path
        candidate.unlink(missing_ok=True)


def get_connection(db_path: str | Path) -> sqlite3.Connection:
    """Return a configured SQLite connection with the schema loaded."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    _refuse_newer_schema(conn)
    return conn


def _refuse_newer_schema(conn: sqlite3.Connection) -> None:
    """Fail fast when the database was built by a newer core version.

    A database stamped with a schema version greater than this code's
    ``CURRENT_SCHEMA_VERSION`` may contain tables and columns this code does
    not know about; reading from it or ingesting into it is unsafe. Repository
    readers call :func:`get_connection` without ``init_schema``, so the check
    must live on the connection path too.
    """
    on_disk_version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    if on_disk_version > CURRENT_SCHEMA_VERSION:
        raise RuntimeError(
            f"Database schema version {on_disk_version} is newer than this "
            f"fantapredictor_core supports ({CURRENT_SCHEMA_VERSION}). "
            "Upgrade the core submodule before opening this database."
        )


def init_schema(conn: sqlite3.Connection, schema_file: str | Path | None = None) -> None:
    """Create all tables and indexes defined in the schema if they don't exist.

    Refuses to open a database stamped with a schema version newer than this
    core version knows about -- that means the database was built by a newer
    core and downgrading silently could misread or corrupt its rows.
    """
    _refuse_newer_schema(conn)
    on_disk_version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    schema_file = Path(schema_file) if schema_file else SCHEMA_FILE
    conn.executescript(schema_file.read_text(encoding="utf-8"))
    _migrate_schema(conn, on_disk_version)
    conn.execute(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION}")
    _seed_sources(conn)
    conn.commit()


def _add_roster_role_column(conn: sqlite3.Connection) -> None:
    roster_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(roster_memberships)")
    }
    if "role" not in roster_columns:
        conn.execute("ALTER TABLE roster_memberships ADD COLUMN role TEXT")


def _add_player_stats_xg_columns(conn: sqlite3.Connection) -> None:
    player_stats_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(player_season_stats)")
    }
    for column in ("xg_chain", "xg_buildup"):
        if column not in player_stats_columns:
            conn.execute(f"ALTER TABLE player_season_stats ADD COLUMN {column} REAL")


def _add_coach_style_columns(conn: sqlite3.Connection) -> None:
    """Coach preferred module and style tags (added in schema v2)."""
    coach_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(coaches)")
    }
    for column in ("preferred_module", "style_tags"):
        if column not in coach_columns:
            conn.execute(f"ALTER TABLE coaches ADD COLUMN {column} TEXT")


# Ordered, additive migrations keyed by the target `user_version` they bring a
# database up to. `schema.sql` already reflects every migration's end state
# (each callable is also idempotent), so these only matter for a database
# created by an older core version whose `user_version` hasn't reached the
# target yet -- including every pre-existing database, since `user_version`
# was never stamped before this version-tracking was added.
MIGRATIONS: list[tuple[int, Callable[[sqlite3.Connection], None]]] = [
    (1, _add_roster_role_column),
    (1, _add_player_stats_xg_columns),
    (2, _add_coach_style_columns),
]


def _migrate_schema(conn: sqlite3.Connection, on_disk_version: int) -> None:
    """Apply every migration whose target version is newer than the database."""
    for target_version, migration in MIGRATIONS:
        if on_disk_version < target_version:
            migration(conn)


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
