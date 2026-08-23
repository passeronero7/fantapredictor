# Changelog

All notable project changes are recorded here.

## [Unreleased] - 2026-08-23

### Added

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
- Full local source snapshot generated for analysis: 11 historical rating seasons, 33 match-result seasons, 124,122 player-match ratings, 11,726 matches, 46,866 odds rows, and 6,726 Understat player-season rows.
- Dual-Repository security architecture and setup guide in `docs/repository_architecture_and_security.md` (Public Core for algorithms, Private Workspace for proprietary data).
- Automated pre-commit leak-prevention hook (`.githooks/pre-commit`) blocking accidental commits of database files (`.db`, `.sqlite`), spreadsheets (`.xlsx`, `.xls`, `.parquet`), and secret tokens.
- Hardened `.gitignore` excluding all credentials, database artifacts, private spreadsheets, and runtime logs.
- Comprehensive unit tests covering distributions, vote parsing, player merging, quotations, database ingestors, deep predictor, and lineup optimization (35 passing tests).

### Changed

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
