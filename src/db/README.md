# FantaPredictor DB layer

Normalized SQLite research warehouse underlying the FantaPredictor project.

## What this is

Every script in `src/`, `scripts/` and the model notebooks consumes data
sourced from free third-party providers (Understat, football-data.co.uk,
StatsBomb, Virgilio...). This package is the single relational home for that
data: a self-describing, schema-versioned SQLite database built from raw
provider files without any live network dependency at runtime.

## Status

The schema (`schema.sql`), bootstrap helpers (`database.py`), offline provider
ingestors, and the CLI builder are implemented and unit-tested. The build is
deliberately offline: download source snapshots first, then load them without
network access.

```bash
python scripts/download_match_results.py --start-year 1993 --end-year 2025
python scripts/build_database.py --db data/fantapredictor.db --season 2627
```

## Schema

The current relational model is defined in `schema.sql` (single source of
truth) and covers:

- **Provenance** — `sources`, `ingestion_runs`
- **Entities** — `clubs`, `players` (+ aliases), `coaches`, `seasons`
- **Roster** — `roster_memberships` (confirmed roster for the active season)
- **Results** — `matches`, `match_team_stats`, `match_odds`,
  `match_coaches`, `coach_club_seasons`, `coach_season_stats`
- **Performance** — `player_season_stats`, `player_match_ratings`, `player_prices` (provider + source tagged)

To inspect or load the schema interactively:

```python
from src.db import database as db

conn = db.get_connection("data/fantapredictor.db")
db.init_schema(conn)
```

## Manual data sources

Some providers block programmatic access. Their data must be exported by hand
from a browser under `data/season_<season>/manual/` (gitignored). The
`src/data_processing/fbref_manual.py` adapter only validates and loads those
local exports; it never contacts FBref.

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
└── ingestors/          # offline provider loaders
    ├── common.py
    ├── football_data.py
    ├── rosters.py
    ├── understat.py
    ├── votes.py
    └── coaches.py
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
