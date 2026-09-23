# Changelog

## [Unreleased]

### Added

- Added a complete Classic auction-roster MILP optimizer (3P/8D/8C/6A,
  500-credit default) driven by risk-adjusted Monte Carlo propensity summaries,
  plus synthetic unit coverage and a reproducible CLI.
- Added a 22 September 2026 open-access literature review mapping hierarchical
  player ratings, event-rate ability, fantasy MILP, player-adjusted xG,
  temporal forecasting and action-value work to adopted or deferred methods.

### Added (auction masterplan, phase 2: live auction, 24 September 2026)

- `src/models/live_auction.py`: auction log (`giocatore,acquirente,prezzo`)
  with accent/case-insensitive name and official-id resolution; per-manager
  credits, open slots and legal maximum bid; money-conservation market
  factor for unsold players; exact dominance pruning; residual plan with own
  buys forced at the price paid; maximum bid per player (break-even price on
  the real MILP), within 3 credits of exact bisection on the 23 September
  data.
- `scripts/live_auction.py`: interactive console (`q`, `m`, `v`, `p`, `b`,
  `s`, `u`) with atomic state writes; `--command` for scripted runs.
- `optimize_auction_roster.py --state`: residual plan, bids and manager
  table as files; `--me`, `--managers`, `--no-market-scaling`.

### Fixed (phase 2)

- The roster MILP solves to optimality (`MIP_REL_GAP = 1e-9`). HiGHS's
  default 0.01% gap (~0.009 objective) matched the gaps between
  near-equivalent plans, so reported rosters could be near-optima (the
  published 23 September roster scored 86.702 against a true 86.705).
- The dossier-derived pool keeps the official id (`source_ref`).

### Changed (23-24 September 2026: refresh, docs, repository hygiene)

- Data refreshed to matchday 5 (23 September); see `docs/auction_refresh.md`.
- README and AGENTS.md document the auction run end to end, the
  `FANTAPREDICTOR_DATA_DIR` requirement, id-based formation matching, the
  availability date rule and the coach-history maintenance rule.
- The core clone's ignored `data/` copy (479 files identical to the
  workspace, 2 stale August versions) was removed, so a run without
  `FANTAPREDICTOR_DATA_DIR` can no longer silently read stale data. The
  duplicate virtualenv in the workspace submodule, byte-identical backup
  files and superseded auction outputs were removed from the private
  workspace (untracked files only).

### Added (coach conditioning, 23 September 2026)

- `src/models/coach_profiles.py`: per-coach role shares of goals and assists
  (D/C/A) over every Serie A matchday since 2015/16, shrunk toward the league
  (120 pseudo-counts); per-player `goal_mult`/`assist_mult` compare the coach
  now in charge with the coaches the player produced his history under.
  The simulation rescales the goal (3) and assist (1) part of each sampled
  bonus, so the effect reaches `expected_fantavoto` and the optimizer.
  Strength λ = 0.25 from a season-ahead backtest on 2021/22-2025/26 (small
  gain; λ = 1 is worse). See `docs/coach_conditioning.md`.
- Coach history ingestion: 363 stints / 109 coaches with dates, including
  the 2026/27 changes at Fiorentina (Vanoli for Grosso) and Bologna
  (Palladino for Tedesco); matches attributed to coaches by date.
- `--coach-strength` on `simulate_auction_propensity.py` (0 disables).
- Availability discount on the real horizon calendar (share of horizon
  matchdays dated on or after the return), so international breaks count.
- Auction dossier: labels follow the latest observed matchday (no more
  hard-coded G5/G4/"16 settembre"); club sheet and summary list the current
  coach, module and in-season changes; players carry their coach.

### Changed (coach conditioning)

- The hand-set module/style-tag deltas are no longer applied by the
  forecast: they only moved the reported `p_good_mark` column, never the
  simulated marks, and had not been validated. `coach_style_adjustments`
  now returns the open stint only (a club with an in-season change used to
  resolve arbitrarily).
- The coach CSV loader writes blank cells as NULL instead of NaN.

### Added (auction masterplan, phase 1)

- Auction costs are floored at `--quotation-floor` x the public quotation
  (default 0.5). The FVM reference prices only the top managers x slots
  players per role and puts everyone else at 1; at that boundary it is
  ~0.9-1.4x quotation, so a quotation-8 player just outside the pool looked
  eight times cheaper than one just inside it.
- `alternative_rosters`: the best roster plus runners-up that each differ
  from every earlier roster by at least `--min-changes` players (no-good
  cuts), with objective and cost, instead of one "ideal" roster.
- `selection_robustness`: re-solves the MILP under log-normal cost (σ 0.25)
  and forecast (σ 0.05) perturbations and reports each player's selection
  rate, mean depth and median cost when selected (pilastro / frequente /
  occasionale).
- `src/models/defence_modifier.py` calibrates the league modifier on
  observed matchdays (GK + best three defenders, strict +1/+3). On 2024/25
  and 2025/26 it averaged 0.12-0.13 points per matchday (best club 0.24-0.34)
  and one point of a starter's expected vote is worth ~0.22 modifier points
  per matchday. The optimizer now adds that marginal value, times the
  player's shrunk expected vote above his role's replacement level (median
  of regular starters in the pool) and his p_plays, only on the P1 and D1-D3
  slots (D4 at 0.3), replacing the flat x1.04 on every defender.
- The optimizer summary reports spend by role against the dossier's planned
  role budgets.

### Fixed

- `simulate_auction_propensity.py` silently skipped probable-formations
  conditioning when the formations file was missing from the resolved data
  directory (e.g. `FANTAPREDICTOR_DATA_DIR` not set), inflating `p_plays` for
  every player who had lost his place; it now fails unless
  `--allow-missing-formations` is passed. The 23 September phase-0 rerun hit
  exactly this and its published roster is superseded.
- Probable-formation titolars are matched by official player id
  (`source_refs`, as in the dossier) with an exact, club-scoped name fallback.
  The previous substring match ignored the club, so e.g. Inter's "Thuram"
  in the XI marked Juventus' injured Thuram K. as a titolar.
- Fixed the auction MILP constraint matrix indexing: filtering the player
  pool after resetting its index (instead of before) left `frame.index`
  sparse while row-position lookups assumed a dense `range(len(frame))`,
  which could throw `IndexError` or silently drop the "each player at most
  once" constraint for a player whose row landed on the budget row instead.
  Regression test reproduces it with ineligible rows placed before eligible
  ones.
- Added `AuctionOptimizationConfig.reserve` and enforced `cost <= budget -
  reserve` so the optimizer actually keeps the credits the auction config
  reserves for still-open slots, instead of spending to exactly the full
  budget.
- Joined the auction forecast and dossier on the warehouse's own
  `player_normalized` identity key (from `players.normalized_name` via
  `player_id`) instead of a second, independently re-derived text
  normalization applied to each CSV's display name; the previous key
  silently dropped or could miscollide players whose two export spellings
  differed (accents, suffixes, "Kamara H." vs "H. Kamara"-style variants).
  `build_pool` now raises on duplicate identities and reports unmatched
  rows on both sides instead of silently dropping them via an inner join.
- Made the availability-horizon reference date in
  `simulate_auction_propensity.py` an explicit `--as-of` argument instead of
  `date.today()`, so the same forecast run is reproducible on a later day.
- Fixed a data regression that had made the structured availability channel
  a no-op for every player: a bulk refresh of `injuries_2026_27.csv` /
  `availability_current.csv` had overwritten the only four rows carrying a
  real `expected_return` date (Yildiz, Ekhator, K. Thuram, McTominay) with
  the empty value used by the ~60 other, source-vague rows, so
  `horizon_factor` silently returned 1.0 (no discount) for everyone. Also
  stopped `optimize_auction_roster.py::build_pool`'s note-based 0.75/0.35
  heuristic discount from re-applying on top of a player already
  discounted by the (now working) structured channel, via a new
  `availability_structured` flag emitted by the forecast.
- Made the active Fantacalcio season-summary snapshot replace older snapshot
  rows even when its source filename changes, preventing ambiguous duplicate
  metrics during a point-in-time rollback or refresh.
- Replaced the generic +1/+3/+6 defence modifier with the league rule supplied
  by the user: goalkeeper plus best three defenders, +1 above 6.5 and +3 above
  7.0 (strict thresholds), and reduced the auction defence premium accordingly.

### September 19 data refresh (pre-matchday 5)

- Re-run the documented download → offline ingestion → dossier flow into a
  new dated snapshot (`refresh_2026_09_19`), after a SQLite backup and a
  copy of the season directory. Matchday 5 was in progress (only
  Monza-Sassuolo played), so votes were fetched through matchday 4 only.
- Warehouse now holds 41 completed fixtures, 439 Understat aggregates
  (417 bridged), 597 quotations (two new `fuori_lista` rows: Lovric,
  Esteban), 6,567 summary metrics, matchday-5 probable XIs and 55 current
  availability notices; 531 eligible players and 1,274 ratings unchanged.
  Release gates (`--require-confirmed --require-lineup --require-priced`),
  integrity and foreign-key checks pass. Dated refresh, quality and
  checksum manifests were written alongside the 8-manager dossier.

### September 16 data refresh and auction preparation

- Add a reproducible download → offline ingestion → Excel/CSV dossier flow
  for the active season, with source URLs, retrieval times and checksums.
- Refresh 380 fixtures (40 completed), 1,274 observed Fantacalcio ratings,
  437 Understat aggregates, 6,545 provider summary metrics and 20 probable
  formations. The private 8-manager/500-credit dossier preserves league-list
  eligibility, source gaps and uncertain availability.
- Schema v6 / package 0.8.0 implements missing `in_league_list` and
  `fuori_lista` columns. Unknown eligibility is excluded; public price
  refreshes preserve previously asserted league flags.
- Bridge unambiguous Understat identities by current club, full name tokens,
  explicit initials and goalkeeper role, without deleting player identities.
  Replace only stale club attributions of the same provider-season aggregate.
- Prevent future fixtures and duplicate provider match rows from inflating
  observed team appearance counts. Support canonical club names and excluded
  players in the priced roster validation gate.
- Parse official player IDs from both current and historical vote URLs;
  consolidate only superseded observations whose old source reference lacked
  an ID. Missing HTML grades remain missing. Preserve discrepancies between
  provider season summaries and individual matchday marks in a workbook sheet.
- Budget scenarios reserve 1 credit per league slot and 10 per manager;
  workbook instructions clearly label assumptions and unvalidated price
  references. Exact recovery dates are not invented from vague injury notes.

### Added

- EAFC attribute bridge: surname-tail matching that prefers fantasy-
  referenced identities, lifting roster coverage to 205 confirmed players;
  an overeager orphan cleanup was recovered via the manifest rebuild path.
- Attribute weight gate: point-biserial correlations of EAFC technique
  attributes against realized 6.0+ marks on the MD1-3 sample came out
  negative (selection bias on 132 player-matches), so the fusion weight is
  held at 0 pending a stable positive signal at MD6-8.
- Availability channel (schema v5 `availability_notes` + curated CSV with
  official sources): proportional `p_plays` discount by expected return
  date -- Yildiz/Ekhator drop to 0, McTominay to 0.39 for the MD4-11
  horizon.
- Recalibration: the documented -0.05 walk-forward offset is now applied
  inside `player_propensity`, not just documented.

### Added

- Official auction-data layer: league-list availability flags
  (`fuori_lista`, 62 unselectable players), the official Statistico 2026/27
  season aggregates (`fantacalcio_season_stats`, through MD3), and official
  probable formations as an appearance conditioning feature (titolar x1.0 /
  rotation x0.6, club-scoped name matching).
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
- Coach and archetype conditioning for the propensity forecast: web-sourced
  coach profiles (module + style tags, schema v2 `coaches` columns) drive
  role deltas, and a k-NN over historical per-90 technique signatures
  (xG/xA/shots/key passes/xGChain/xGBuildup + realised mark rates) blends
  similar-player propensity into every estimate.
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
