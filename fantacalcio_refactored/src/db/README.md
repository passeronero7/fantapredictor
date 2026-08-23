# Fantacalcio DB layer

Normalized SQLite research warehouse underlying the Fantacalcio project.

## What this is

Every script in `src/`, `scripts/` and the model notebooks consumes data
sourced from free third-party providers (Understat, football-data.co.uk,
StatsBomb, Virgilio...). This package is the single relational home for that
data: a self-describing, schema-versioned SQLite database built from raw
provider files without any live network dependency at runtime.

## Status

Initial schema (`schema.sql`) and bootstrap helpers (`database.py`) are in
place and unit-tested. The provider ingestors under `ingestors/` and the CLI
builder script are the next increment and do **not** exist yet.

## Schema

The current relational model is defined in `schema.sql` (single source of
truth) and covers:

- **Provenance** — `sources`, `ingestion_runs`
- **Entities** — `clubs`, `players` (+ aliases), `coaches`, `seasons`
- **Roster** — `roster_memberships` (confirmed roster for the active season)
- **Results** — `matches`, `match_team_stats`, `match_odds`,
  `match_coaches`, `coach_club_seasons`, `coach_season_stats`
- **Performance** — `player_season_stats` (provider + source tagged)

To inspect or load the schema interactively:

```python
from src.db import database as db

conn = db.get_connection("data/serie_a.db")
db.init_schema(conn)
```

## Manual data sources

Some providers block programmatic access. Their data must be exported by hand
from a browser under `data/season_<season>/manual/` (gitignored). No ingestor
for these exists yet; the workflow below is the agreed approach once ingestion
is implemented.

| Source | File to place | Imported into | Notes |
|---|---|---|---|
| FBref (scouting) | `fbref_scouting_<season>.csv` | `player_season_stats` | Export from FBref "Scouting" table |
| FBref (passing) | `fbref_passing_<season>.csv` | `player_season_stats` | Export from FBref "Passing" table |


## Layout

```
src/db/
├── __init__.py         # __version__ (single version)
├── schema.sql          # DDL - the whole relational model
├── database.py         # connection handling, schema bootstrap, source seeding
└── ingestors/          # one module per provider; each exposes load(conn, path)
    └── README.md
```

## Releasing a new version

1. Bump `__version__` in `src/db/__init__.py` **and** the `version` field in
   `pyproject.toml` in the same commit and keep them equal.
2. Add an entry to the root [`CHANGELOG.md`](../../../CHANGELOG.md) under the
   `[Unreleased]` / new version section.
3. If the schema changed, bump the major (breaking) or minor (additive) version
   accordingly - the Studio/notebooks rely on it.
4. Update this README if you added a source.

## Tests

```bash
python -m pytest src/db -v
```
