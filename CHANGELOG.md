# Changelog

## [Unreleased]

### Added

- Auction propensity forecast (`src/models/propensity.py`,
  `scripts/simulate_auction_propensity.py`): Monte Carlo time-series of each
  priced confirmed player's propensity to hold a median good mark
  (vote >= 6.0) over a horizon, conditioned on his own vote/bonus
  distributions, an empirical-Bayes appearance rate, and the club's
  statistical attitude (attack/defense style indices from shots and goals).
  A walk-forward backtest mode scores calibration and Brier on completed
  seasons; the 2025/26 study shows a monotone ranking signal with a
  documented overconfidence bias in the upper bins. See
  `docs/auction_propensity_forecast.md`.
- `repository.load_team_match_stats`: one row per club appearance with
  goals for/against and source-provided team statistics.
- Coach-attitude conditioning hook (`coach_style_adjustments`), ready for the
  `coach_club_seasons` table once the curated history is populated.

- `scripts/promote_roster_from_prices.py` bridges roster and quotation
  identities: watchlist rows evidenced by the official Fantacalcio quotation
  list (same club, exact name, surname+initial, or a surname unique within
  the club) are promoted to `confirmed` and adopt the quotation spelling, and
  `--adopt-unmatched` adds priced players missing from the roster snapshot as
  confirmed (quotation evidence), moving surname-only confirmed rows at other
  clubs when the role proves a missed transfer. Namesake conflicts are
  reported, never guessed.
- `scripts/validate_release.py --require-priced`: the default formation must
  be fillable with *priced* confirmed players; unpriced warm bodies no longer
  satisfy the release gate.
- `src/models/baselines.py` and a baseline fallback in the predict stage:
  without an approved model, `run_pipeline.py --stage predict` now emits
  transparent global-median/expanding-prior quantiles for priced confirmed
  players, labelled with `prediction_source`, so auction research no longer
  depends on the unapproved SHASH network. Prior ratings strictly exclude the
  target matchday.

### Fixed

- Quotation-to-roster matching handles particle surnames (`Di Lorenzo`,
  `De Bruyne`, `Da Cunha`) and double initials (`Esposito F.P.`,
  `Sanchez Ro.`) via a surname-tail rule; ambiguity is reported instead of
  guessed.
- `get_connection` now fails fast on databases stamped with a newer schema
  version, matching the existing `init_schema` guard: repository readers open
  connections without running `init_schema`, so the check must live on the
  connection path too.
- `tests/test_players_processor.py` passes explicit empty skill-stat frames to
  `merge_all_sources`, so the player-merge tests no longer depend on the
  presence (or schema age) of a local `fantapredictor.db`.

### Evaluated

- Whether a directories refactor would clean up the codebase. **Conclusion:
  not warranted as a broad restructure.** The project is ~60 Python files
  split across four purpose-named `src/` packages (`db`, `data_processing`,
  `models`, `utils`) plus flat `scripts/` (18 files) and `tests/` (23 files)
  directories that already mirror the module they cover. Nesting `scripts/`
  by workflow stage, or splitting `tests/` into unit/integration, would mean
  rewriting every doc reference (`README.md`, `AGENTS.md`,
  `docs/operations_runbook.md`, `docs/data_pipeline.md`) and the
  cross-script imports in `run_pipeline.py`
  (`from scripts.optimize_lineup import optimize`, `from scripts.validate_release
  import validate_roster`) for no clear navigability gain at this size. See
  `AGENTS.md`'s new "Layout" section for the standing rule this sets.

### Removed

- `src/utils/file_io.py`: dead code with zero importers anywhere in `src/`,
  `scripts/`, or `tests/` (confirmed by a repo-wide grep before deletion).
  Its `read_excel`/`to_excel` helpers were superseded by direct `pandas`
  calls at each actual call site.

### Changed

- `README.md`'s "Project map" now describes what each `src/` package and
  `scripts/`/`tests/`/`config/` directory is for, instead of one line per
  top-level directory.

## [0.7.0] - 2026-09-02

Implements `docs/ingestion_and_fixing_strategy.md` Strategy A/B (see that
document for the full design record and acceptance criteria).

### Added

- A declared source manifest, `config/data_sources.json`, resolved by the new
  `src/db/build.py`: `scripts/build_database.py` no longer discovers seasons
  or files through ad hoc globs when no explicit source path is passed (A3,
  B1).
- Per-source checksum-skip: a manifest source whose file/directory content
  matches its last successful load is skipped instead of re-ingested, tracked
  in the new `source_checksums` table (B2).
- Per-source error isolation: a failing manifest source is rolled back and
  recorded without aborting the rest of the build; `build_database.py` exits
  non-zero and prints a summary only if any source failed (B2).
- `PRAGMA user_version` schema versioning. `src/db/database.py::init_schema`
  refuses to open a database from a newer core version and applies an
  explicit, ordered migration list instead of one hardcoded function (A4,
  B3).
- `scripts/build_database.py --rebuild --confirm-wipe`: drops and recreates
  the schema from `schema.sql`, then reloads the full manifest, for
  reproducible from-scratch rebuilds (A4, B4). `--force` reloads every
  manifest source regardless of checksum-skip.
- `scripts/evaluate_model.py` now reports a hard `gate` verdict: the SHASH
  model must beat both the global-median and expanding-prior baselines on
  fantavoto MAE, else the script exits non-zero and prints that the run is
  not approved for auction or lineup decisions (A2's baseline gate; the
  broader historical-coverage and expected-minutes feature work in A2 is not
  part of this change -- it needs a data-sourcing decision, not just code).
- `fantapredictor-workspace/scripts/sync_workspace.sh` automates the
  `docs/operations_runbook.md` Git Synchronization flow and refuses to
  detach the submodule while it has uncommitted changes (A5).

### Fixed

- `scripts/run_pipeline.py`'s training stage now builds its dataset directly
  from `MatchDataBuilder` (the same warehouse-backed reader used by stage 4
  and `evaluate_model.py`) instead of unconditionally reading
  `mid_outputs/database_entries(_gk).xlsx`, so `--stage train` no longer
  requires `--stage training-data` to have run first in the same process
  (A1).

## [0.6.0] - 2026-09-01

### Added

- Offline normalization of browser-copied FBref CSVs, including their citation
  preamble and duplicated grouped metric headers, before warehouse ingestion.
- Current-season Understat downloads now retain completed fixtures, final
  scores, matchday numbers, and team xG alongside player-season aggregates.
- The warehouse builder ingests the Understat match snapshot when the
  Football-Data.co.uk current-season file is unavailable.
- Historical training now loads every observed vote season through the target
  season and creates season-specific player snapshots.
- Match feature matrices now include home/away, opponent identity and rolling
  five-match team/opponent xG, xG-against and points form from prior fixtures.
- Evaluation supports disjoint expanding walk-forward windows and reports
  aggregate, per-window, role, club, and historical-minute metrics.
- Operational documentation records the post-closure 2026/27 transfer,
  quotation, vote, match, xG, and warehouse checkpoint.

### Fixed

- Player-season aggregates are restricted to seasons strictly before each
  target season, preventing future and same-season feature leakage.
- The pipeline's `--include-history` flag now changes the training population
  instead of being accepted without effect.
- Football-Data match ingestion assigns round numbers from fixture order when
  the provider file has no matchday field, enabling historical context joins.
- Fantacalcio roles now take precedence over generic provider positions in the
  player identity record and evaluation cohorts.
- Missing Fantacalcio provider IDs no longer collapse every player from a club
  into one warehouse identity.
- Compact pre-2000 season codes such as `9394` and `9900` now resolve to
  1993/94 and 1999/00 instead of future seasons.
- Understat's `AC Milan` and `Parma Calcio 1913` labels resolve to canonical
  warehouse clubs. Comma-joined transfer aggregates use an official active
  roster destination when available and otherwise remain club-unassigned.

## [0.5.0] - 2026-08-28

### Added

- Offline ingestion of browser-exported FBref player tables into a normalized,
  provider-specific metric store. Passing, shooting, creation, defensive,
  possession, playing-time, misc, and goalkeeper exports are supported.
- Repository and player-merge access to FBref metrics, always prefixed with
  `fbref_` to preserve source semantics.
- Understat `xGChain` and `xGBuildup` are retained in the player-season store
  and surfaced in historical player data.
- Reproducible download of a single current Understat Serie A snapshot and
  formal-roster reconciliation from Lega Serie A's public transfer feed.
- Club-grade data strategy covering lawful source layers, deep player features,
  provenance, snapshot timing, and leakage-safe modelling.

### Fixed

- Database builds now derive the default roster filename from the requested
  season instead of hard-coding the 2026/27 file.
- Roster ingestion normalizes status capitalization/whitespace and avoids
  persisting pandas missing values as player roles.
- Manual FBref imports resolve a unique season-and-club roster match before
  falling back to a global normalized-name match.
- Understat ingestion no longer discards the `xGChain` and `xGBuildup` fields
  already present in the public aggregate archive.

All notable project changes are recorded here.

## [Unreleased] - 2026-08-24

### Added

- A `soccerdata` Understat adapter and CLI now retrieve a current Serie A
  player-season snapshot in the existing warehouse-ingestor CSV contract,
  retaining a source URL, retrieval timestamp, and local client cache.
- Chronological evaluation metrics and CLI for held-out matchday ranges,
  including point error and SHASH quantile/interval coverage.
- Bounded SHASH parameter decoding and median-based point outputs prevent
  numerical explosions from producing unusable prediction intervals.
- Added a central-target penalty to the SHASH training objective to stabilize
  point predictions alongside distribution likelihood optimization.
- Added a first-class lineup optimization CLI/pipeline stage that serializes
  legal budget-constrained Monte Carlo lineup results.
- Added roster release validation, private source checksum manifests, and a
  private-workspace credential pre-commit hook.
- Prediction generation now runs the strict confirmed-pool release gate before
  loading a model artifact.
- Release validation can now require a complete default 3-4-3 confirmed pool,
  not merely one confirmed record.
- Versioned the roster-membership role in the SQLite schema with an additive
  migration so provider roles cannot be overwritten by unrelated source roles.
- Centered SHASH predictions on expanding prior-vote/fantavoto features with a
  learned residual correction, making the model's baseline comparison fairer.
- Added a manual roster reconciliation template and a read-only SQLite
  inspection CLI for environments without the `sqlite3` shell.
- In-depth evaluation of USA football probabilistic modeling (`amiles2233/ff_prob`) and architectural blueprint in `docs/probabilistic_modeling_and_ff_prob_evaluation.md`.
- Sinh-Arcsinh (SHASH) distribution module (`src/models/distributions.py`) implementing 4-parameter asymmetric, heavy-tailed fantasy scoring density with PDF, CDF, quantile (PPF), sampling (RVS), and MLE fitting.
- Fantacalcio weekly vote processing engine (`src/data_processing/votes_processor.py`) supporting Italian spreadsheet formats and robust decimal/delimiter parsing.
- Unified multi-source player merging engine (`src/data_processing/players_processor.py`) with name normalization and empirical Bayesian shrinkage for low-minute per-90 metrics.
- Matchday feature matrix builder (`src/data_processing/match_data_builder.py`) for outfield players and goalkeepers.
- Probabilistic prediction engine (`src/models/neural_network.py` / `FantacalcioPredictor`) producing expected fantasy points and risk quantiles (floor q10, median q50, ceiling q90).
- Monte Carlo lineup optimizer (`src/models/lineup_optimizer.py` / `LineupOptimizer`) with formation validation and Italian Serie A *Modificatore Difesa* calculations.
- Historical Fantacalcio.it vote downloader (`scripts/download_historical_votes.py`) enabling automated retrieval and archiving of official matchday votes, fantavoti, and bonuses/maluses across 11 historical Serie A seasons (2015/16 to present).
- Multi-source vote parsing engine in `VotesProcessor` supporting both official matchday HTML tables and local spreadsheet files with automatic Italian decimal/grade normalization (e.g. scaling political 55/60 codes).
- Normalized SQLite ingestors for Understat, rosters, official ratings, Football-Data match results/odds, quotations, and curated coach history, plus `scripts/build_database.py`.
- Public Fantacalcio quotation parser and downloader (`scripts/download_current_prices.py`) providing current classic/mantra roles, prices, and FVM values.
- Full local source snapshot generated for analysis: 11 historical rating seasons, 33 match-result seasons, 124,122 player-match ratings, 11,726 matches, 46,866 odds rows, 539 current quotations, and 6,726 Understat player-season rows.
- Documented the executed private-workspace rebuild, SQLite inspection results,
  roster reconciliation checkpoint, and model evaluation results.
- Recorded the roster decision to include Venezia and exclude relegated Verona,
  with definitive reconciliation deferred until 1 September 2026 at 20:00 CEST.
- Dual-Repository security architecture and setup guide in `docs/repository_architecture_and_security.md` (Public Core for algorithms, Private Workspace for proprietary data).
- Automated pre-commit leak-prevention hook (`.githooks/pre-commit`) blocking accidental commits of database files (`.db`, `.sqlite`), spreadsheets (`.xlsx`, `.xls`, `.parquet`), and secret tokens.
- Hardened `.gitignore` excluding all credentials, database artifacts, private spreadsheets, and runtime logs.
- Comprehensive unit tests covering distributions, vote parsing, player merging, quotations, database ingestors, deep predictor, release validation, and lineup optimization (45 passing tests).

### Changed

- Added `FANTAPREDICTOR_DATA_DIR` and warehouse repository readers so the core
  can run from the private workspace without creating a second data tree.
- Replaced live FBref scraping, including the Selenium/cloudscraper paths, with
  a local manual-export validator and removed the `cloudscraper` dependency.
- Baseline roster snapshots now use the contract-compliant `watchlist` status
  until manual reconciliation promotes a player to `confirmed`.
- Player merging fails closed for missing/non-confirmed roster status, and the
  roster ingestor validates required provenance fields and status values.
- Promoted package structure from nested legacy directory `fantacalcio_refactored/` directly to standard root layout (`src/`, `config/`, `scripts/`, `tests/`, `data/`).
- Removed legacy artifacts (`venvfanta/`, `files.zip`, `DELIVERY_HANDOFF.md`, `DIRECTORY_STRUCTURE.txt`).
- Updated all execution commands and pipeline imports to run directly from repository root.

### Fixed

- Removed the legacy live FBref scraper path after replacing it with the
  manual-export validator.
- Fixed unused `import os` in `config/settings.py` and cleaned up pipeline script references.
- Fixed per-90 rate metric explosion for low-sample players by introducing Bayesian prior shrinkage in `PlayersProcessor`.
- Removed synthetic training fallback and prevented same-matchday vote target leakage in `MatchDataBuilder`.
- Replaced the gradient-boosting placeholder with a TensorFlow deep SHASH model and persisted Keras/scaler artifacts.
- Enforced the 500-credit lineup budget and added correlated Monte Carlo formation search with defence modifiers.
- Fixed season propagation and season-specific output directories in `scripts/run_pipeline.py`.


## [0.1.0] - 2026-08-23

### Added

- `download_baseline_data.py`, which downloads a dated 2026/27 20-club player snapshot and joins it to all available open-league Understat player-season history.
- Bootstrap report and coverage documentation: 626 roster entries, 419 players with open-data history, and 2,056 matched historical rows.

### Fixed

- Made the baseline downloader work when called directly from `scripts/`, as documented.

### Data notes

- Generated roster/history files are intentionally ignored by Git because they are time-sensitive third-party data. The downloader and its report schema are versioned instead.
