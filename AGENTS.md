# FantaPredictor agent guide

## Mission

Build a reproducible, evidence-led Fantacalcio research and prediction project for Serie A 2026/27 (named `fantapredictor`).

## Layout

See `README.md`'s "Project map" for the directory breakdown. The flat
`scripts/`/`tests/` layout and the four purpose-named `src/` packages
(`db`, `data_processing`, `models`, `utils`) were deliberately kept as-is
after an explicit evaluation (`CHANGELOG.md`) concluded that deeper
subpackaging would mean rewriting every doc and cross-script import
(`run_pipeline.py` imports `scripts.optimize_lineup` and
`scripts.validate_release` directly) for little real navigability gain at
this project's size (~60 Python files). Don't introduce new subdirectories
under `scripts/` or `tests/` without a concrete reason beyond tidiness; do
delete a module once nothing imports it (verify with a repo-wide grep first,
as was done for the unused `src/utils/file_io.py`).

## Working rules

- Keep `README.md` and `CHANGELOG.md` authoritative.
- Do not describe unimplemented pipeline stages as working. The codebase implements manual FBref export validation, Understat baseline downloading, empirical-Bayes player confidence scoring, SQLite relational warehouse (`src/db/`), vote processing (`VotesProcessor`), multi-source player merging (`PlayersProcessor`), match dataset preparation (`MatchDataBuilder`), probabilistic SinhArcsinh prediction (`FantacalcioPredictor`), and Monte Carlo lineup optimization (`LineupOptimizer`).
- Use only confirmed transfers for the active roster dataset. Keep rumours in a separate watchlist and never merge them into eligible players.
- Record a source URL and `checked_at` date for every roster or transfer assertion. The transfer market remains open until 1 September 2026, so refresh before every auction or model run.
- Keep raw, source-derived data out of Git unless it is small and redistributable. Store generated exports in `data/` (ignored).
- Add or update tests for behaviour changes. Do not make live network calls in tests.
- The SQLite research warehouse in `src/db/` is authoritative for data retrieval. The schema is versioned: bump `src/db/__init__.py::__version__` and `pyproject.toml` together with any schema change, and keep each ingestor idempotent (safe to re-run).
- Do not add runtime dependencies unless required; SQLite plus the standard library are preferred. If an ingestor needs a third-party package (e.g. `pandas`, `requests`), import it lazily inside the ingestor and document it.
- FBref is never scraped. Import FBref data only from browser-exported CSV files placed under `data/season_*_27/manual/`. Never add logic that defeats a 403 or other access control.
- Probabilistic modeling utilizes the Sinh-Arcsinh (SHASH) distribution to capture skewed, heavy-tailed fantasy scores, providing floor (q10), median (q50), and ceiling upside (q90) predictions alongside Monte Carlo matchday simulations.
- Training must use observed vote/fantavoto targets only; never use the bootstrap roster as synthetic training data. Historical expanding features must not include the target matchday.
- The lineup optimizer uses a 500-credit default budget, requires current player prices, and evaluates complete legal formations with correlated Monte Carlo draws and defence modifiers.
- Security & IP protection: Maintain a Dual-Repository architecture (Public Core repo for algorithms and models, Private Workspace for raw data and personal league configs). Pre-commit hooks (`.githooks/pre-commit`) are enforced to block accidental commits of databases, spreadsheets, or credentials.
- For every material change, update `CHANGELOG.md` and the relevant user-facing documentation, then stage and commit the coherent change set. Generated data and local environments remain untracked.

## Commands

```bash
python -m unittest discover -s tests -v
python scripts/download_match_results.py --start-year 1993 --end-year 2025
python scripts/download_current_prices.py --season 2026-27
python scripts/build_database.py --db data/fantapredictor.db --season 2627
python scripts/download_historical_votes.py --season 2024-25 --start 1 --end 38
python scripts/run_pipeline.py --stage players --season 2627
python scripts/run_pipeline.py --stage training-data --season 2627
python scripts/run_pipeline.py --stage train --season 2627
python scripts/run_pipeline.py --stage predict --matchday 1 --season 2627
python scripts/analyze_defenders.py
```

## Prediction strategy rules

- The official league auction list (Leghe app export) is authoritative over
  the public quotazioni page for auction eligibility; the `fuori_lista` flag
  must gate every auction-facing output.
- Official probable formations condition appearance estimates; never present
  bench players as starters without the formation discount.


- Auction propensity comes from `src/models/propensity.py`; keep the model
  transparent (empirical distributions + shrinkage) and backtested before any
  change to its estimates. Report propensity as a ranking metric: the
  documented 2025/26 calibration is monotone but overconfident in the top bin.
- Coach conditioning uses only curated `coach_club_seasons` rows with source
  URLs; never fabricate coach modules or style tags.
- The predict stage falls back to labelled global-median/expanding-prior
  baselines whenever no model has passed the evaluation gate; never present
  unapproved SHASH output as auction-ready.
- Roster status is authoritative for every forecast: players outside the
  confirmed pool are excluded even when ratings history exists.

## Data contract

Roster records must contain: `player`, `club`, `role`, `status`, `source_url`, and `checked_at`. Valid `status` values are `confirmed`, `watchlist`, and `excluded`. A player can enter model or auction outputs only with `confirmed` status.
