-- =============================================================================
-- Fantacalcio Research DB - Normalized relational schema
-- -----------------------------------------------------------------------------
-- Conventions
--   * Surrogate integer primary keys on every table.
--   * soft-delete free: rows are inserted-or-ignored / upserted by natural key.
--   * Every row that came from an external provider references `sources`.
--   * `updated_at` is maintained by triggers defined at the bottom.
--   * Raw data snapshots are documented in the `sources` table and kept
--     versioned alongside the schema.
-- =============================================================================

PRAGMA foreign_keys = ON;

-- -----------------------------------------------------------------------------
-- Provenance
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sources (
    id            INTEGER PRIMARY KEY,
    slug          TEXT NOT NULL UNIQUE,          -- e.g. 'understat', 'football-data.co.uk'
    name          TEXT NOT NULL,                 -- human readable
    homepage_url  TEXT,
    licence       TEXT,                          -- known licence / ToS note
    notes         TEXT
);

CREATE TABLE IF NOT EXISTS ingestion_runs (
    id                 INTEGER PRIMARY KEY,
    source_id          INTEGER NOT NULL REFERENCES sources(id),
    started_at         TEXT NOT NULL,            -- ISO 8601 UTC
    finished_at        TEXT,
    status             TEXT NOT NULL DEFAULT 'running'
                       CHECK (status IN ('running', 'ok', 'error')),
    rows_expected      INTEGER,
    rows_loaded        INTEGER,
    detail             TEXT,                     -- free form JSON / message
    UNIQUE (source_id, started_at)
);
CREATE INDEX IF NOT EXISTS ix_ingestion_runs_source ON ingestion_runs (source_id);

-- -----------------------------------------------------------------------------
-- Core entities
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS clubs (
    id               INTEGER PRIMARY KEY,
    name             TEXT NOT NULL UNIQUE,        -- display name, e.g. 'Inter'
    full_name        TEXT,                        -- 'Football Club Internazionale Milano'
    country          TEXT DEFAULT 'Italy',
    source_id        INTEGER REFERENCES sources(id),
    source_ref       TEXT,                        -- id in the source system
    updated_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS coaches (
    id                INTEGER PRIMARY KEY,
    full_name         TEXT NOT NULL,
    date_of_birth     TEXT,
    nationality       TEXT,
    source_id         INTEGER REFERENCES sources(id),
    source_ref        TEXT,
    home_away         TEXT CHECK (home_away IS NULL OR home_away IN ('any','home','away')),
    notes             TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_coaches_name_dob
    ON coaches (full_name, COALESCE(date_of_birth, '')) ;
CREATE INDEX IF NOT EXISTS ix_coaches_name ON coaches (full_name);

-- Players are universal across sources; source-of-truth roster membership is
-- expressed by `roster_memberships` below.
CREATE TABLE IF NOT EXISTS players (
    id                 INTEGER PRIMARY KEY,
    full_name          TEXT NOT NULL,
    normalized_name    TEXT NOT NULL,
    date_of_birth      TEXT,                     -- ISO 8601
    nationality        TEXT,
    role               TEXT,                     -- provider role: P/D/C/A (fantacalcio) or FBref pos
    source_id          INTEGER REFERENCES sources(id),
    source_ref         TEXT,                     -- id in the source system
    updated_at         TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (normalized_name, date_of_birth)
);
CREATE INDEX IF NOT EXISTS ix_players_normalized_name ON players (normalized_name);
CREATE INDEX IF NOT EXISTS ix_players_source ON players (source_id, source_ref);

-- Alias table: link a player to the many external ids of each source.
CREATE TABLE IF NOT EXISTS player_aliases (
    player_id    INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    source_id    INTEGER NOT NULL REFERENCES sources(id),
    source_ref   TEXT NOT NULL,                  -- external id, e.g. understat player id
    label        TEXT,                            -- the raw name in that source
    PRIMARY KEY (player_id, source_id, source_ref)
);

-- e.g. 'Inter' <-> 'Inter Milan', 'Internazionale'
CREATE TABLE IF NOT EXISTS team_aliases (
    club_id   INTEGER NOT NULL REFERENCES clubs(id) ON DELETE CASCADE,
    alias     TEXT NOT NULL UNIQUE,
    source_id INTEGER REFERENCES sources(id),
    PRIMARY KEY (club_id, alias)
);

-- -----------------------------------------------------------------------------
-- Season + roster membership (the 2026/27 roster research)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS seasons (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE,             -- '2026/27'
    start_year INTEGER NOT NULL UNIQUE           -- 2026
);

-- A player plays for a club in a season (all clubs, all historical seasons we know of).
CREATE TABLE IF NOT EXISTS roster_memberships (
    id            INTEGER PRIMARY KEY,
    player_id     INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    club_id       INTEGER NOT NULL REFERENCES clubs(id)   ON DELETE CASCADE,
    season_id     INTEGER NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
    status        TEXT NOT NULL DEFAULT 'confirmed'
                  CHECK (status IN ('confirmed','watchlist','excluded')),
    source_url    TEXT,
    checked_at    TEXT,                          -- last time this row was asserted
    UNIQUE (player_id, club_id, season_id)
);
CREATE INDEX IF NOT EXISTS ix_roster_memberships_club_season
    ON roster_memberships (club_id, season_id);
CREATE INDEX IF NOT EXISTS ix_roster_memberships_season
    ON roster_memberships (season_id);

-- -----------------------------------------------------------------------------
-- Coach history: who coached whom, when
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS coach_club_seasons (
    id          INTEGER PRIMARY KEY,
    coach_id    INTEGER NOT NULL REFERENCES coaches(id) ON DELETE CASCADE,
    club_id     INTEGER NOT NULL REFERENCES clubs(id)   ON DELETE CASCADE,
    season_id   INTEGER REFERENCES seasons(id),         -- NULL = unknown / current spell
    started_at  TEXT,                                   -- ISO 8601 date when available
    ended_at    TEXT,
    source_url  TEXT,
    notes       TEXT,
    UNIQUE (coach_id, club_id, season_id, started_at)
);
CREATE INDEX IF NOT EXISTS ix_coach_club_seasons_club
    ON coach_club_seasons (club_id, season_id);

-- Which coach was in charge of a given match (home/away) - populated from
-- kick-off/final-lineup sources. Modelled for future use.
CREATE TABLE IF NOT EXISTS match_coaches (
    match_id   INTEGER NOT NULL,
    coach_id   INTEGER NOT NULL REFERENCES coaches(id) ON DELETE CASCADE,
    side       TEXT NOT NULL CHECK (side IN ('home','away')),
    PRIMARY KEY (match_id, side)
);

-- -----------------------------------------------------------------------------
-- Matches and results
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS matches (
    id                INTEGER PRIMARY KEY,
    season_id         INTEGER REFERENCES seasons(id),
    competition       TEXT NOT NULL DEFAULT 'Serie A',
    matchday          INTEGER,
    match_date        TEXT NOT NULL,             -- ISO 8601 date or datetime
    home_club_id      INTEGER NOT NULL REFERENCES clubs(id),
    away_club_id      INTEGER NOT NULL REFERENCES clubs(id),
    home_goals        INTEGER,
    away_goals        INTEGER,
    home_goals_half   INTEGER,
    away_goals_half   INTEGER,
    home_xg           REAL,
    away_xg           REAL,
    attendance        INTEGER,
    referee           TEXT,
    source_id         INTEGER REFERENCES sources(id),
    source_match_id   TEXT,                       -- id in the source system
    updated_at        TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (source_id, source_match_id)
);
CREATE INDEX IF NOT EXISTS ix_matches_season_date
    ON matches (season_id, match_date);
CREATE INDEX IF NOT EXISTS ix_matches_home_club
    ON matches (home_club_id);
CREATE INDEX IF NOT EXISTS ix_matches_away_club
    ON matches (away_club_id);

-- Team level stats per match, e.g. shots, possession, corners, xG
CREATE TABLE IF NOT EXISTS match_team_stats (
    match_id     INTEGER NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    club_id      INTEGER NOT NULL REFERENCES clubs(id),
    side         TEXT NOT NULL CHECK (side IN ('home','away')),
    shots        INTEGER,
    shots_on_target INTEGER,
    corners      INTEGER,
    fouls        INTEGER,
    yellow_cards INTEGER,
    red_cards    INTEGER,
    possession   REAL,
    xg           REAL,
    PRIMARY KEY (match_id, side)
);
CREATE INDEX IF NOT EXISTS ix_match_team_stats_club ON match_team_stats (club_id);

-- Match-level betting odds (provider columns from football-data.co.uk)
CREATE TABLE IF NOT EXISTS match_odds (
    match_id     INTEGER NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    provider     TEXT NOT NULL,                   -- 'B365', 'Pinnacle', ...
    home         REAL,
    draw         REAL,
    away         REAL,
    PRIMARY KEY (match_id, provider)
);

-- Official fantasy ratings and bonus/malus events per player and matchday.
-- `vote` and `fantavoto` are the editorial Fantacalcio values; the three
-- source-specific columns preserve the statistical and Voto Italia variants.
CREATE TABLE IF NOT EXISTS player_match_ratings (
    id                    INTEGER PRIMARY KEY,
    season_id             INTEGER NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
    matchday              INTEGER NOT NULL,
    player_id             INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    club_id               INTEGER REFERENCES clubs(id),
    vote                  REAL,
    fantavoto             REAL,
    vote_statistical      REAL,
    fantavoto_statistical REAL,
    vote_italy            REAL,
    fantavoto_italy       REAL,
    goals                INTEGER DEFAULT 0,
    goals_conceded       INTEGER DEFAULT 0,
    assists              INTEGER DEFAULT 0,
    yellow_cards         INTEGER DEFAULT 0,
    red_cards            INTEGER DEFAULT 0,
    penalties_saved      INTEGER DEFAULT 0,
    penalties_missed     INTEGER DEFAULT 0,
    penalties_scored     INTEGER DEFAULT 0,
    own_goals            INTEGER DEFAULT 0,
    source_id             INTEGER NOT NULL REFERENCES sources(id),
    source_ref            TEXT,
    source_file           TEXT,
    updated_at            TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (season_id, matchday, player_id, club_id, source_id)
);
CREATE INDEX IF NOT EXISTS ix_player_match_ratings_player
    ON player_match_ratings (player_id, season_id, matchday);

-- Fantasy-provider quotation snapshot used by the auction optimizer.
CREATE TABLE IF NOT EXISTS player_prices (
    id               INTEGER PRIMARY KEY,
    season_id        INTEGER NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
    player_id        INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    club_id          INTEGER REFERENCES clubs(id),
    role_classic     TEXT,
    role_mantra      TEXT,
    price_initial    REAL,
    price_current   REAL,
    fvm              REAL,
    source_id        INTEGER NOT NULL REFERENCES sources(id),
    source_ref       TEXT,
    updated_at       TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (season_id, player_id, source_id)
);
CREATE INDEX IF NOT EXISTS ix_player_prices_season_role
    ON player_prices (season_id, role_classic, price_current);

-- -----------------------------------------------------------------------------
-- Player performance
-- -----------------------------------------------------------------------------
-- One row per player + season (possibly per source); use `source_id` to keep
-- track of provenance, and `MLS_STATS_TYPE` (shooting / passing / def actions)
-- to allow the multiple FBref tables.
CREATE TABLE IF NOT EXISTS player_season_stats (
    id               INTEGER PRIMARY KEY,
    player_id        INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    club_id          INTEGER REFERENCES clubs(id),
    season_id        INTEGER NOT NULL REFERENCES seasons(id),
    min_age          REAL,                        -- e.g. 24.5 at start of the season
    games            INTEGER,
    games_starts     INTEGER,
    minutes          INTEGER,
    minutes_90s      REAL,
    goals            INTEGER,
    assists          INTEGER,
    goals_pens       INTEGER,                     -- goals minus penalties
    pens_made        INTEGER,
    xg               REAL,
    xa               REAL,
    npxg             REAL,
    xg_plus_xa       REAL,
    shots            INTEGER,
    shots_on_target  INTEGER,
    key_passes       INTEGER,
    yellow_cards     INTEGER,
    red_cards        INTEGER,
    clean_sheets     INTEGER,                     -- GK
    goals_against    INTEGER,                     -- GK
    saves            REAL,                        -- GK
    source_id        INTEGER REFERENCES sources(id),
    source_ref       TEXT,
    updated_at       TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (player_id, season_id, club_id, source_id, source_ref)
);
CREATE INDEX IF NOT EXISTS ix_pss_player ON player_season_stats (player_id);
CREATE INDEX IF NOT EXISTS ix_pss_season_club ON player_season_stats (season_id, club_id);

-- Coach performance per season (club + final position info)
CREATE TABLE IF NOT EXISTS coach_season_stats (
    coach_id      INTEGER NOT NULL REFERENCES coaches(id) ON DELETE CASCADE,
    club_id       INTEGER NOT NULL REFERENCES clubs(id),
    season_id     INTEGER NOT NULL REFERENCES seasons(id),
    matches       INTEGER,
    wins          INTEGER,
    draws         INTEGER,
    losses        INTEGER,
    goals_for     INTEGER,
    goals_against INTEGER,
    final_rank    INTEGER,
    source_id     INTEGER REFERENCES sources(id),
    PRIMARY KEY (coach_id, club_id, season_id)
);
