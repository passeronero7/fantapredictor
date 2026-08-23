# FantaPredictor agent guide

## Mission

Build a reproducible, evidence-led Fantacalcio research and prediction project for Serie A 2026/27 (named `fantapredictor`).

## Working rules

- Keep `README.md` and `CHANGELOG.md` authoritative.
- Do not describe unimplemented pipeline stages as working. The codebase implements FBref collection, Understat baseline downloading, empirical-Bayes player confidence scoring, SQLite relational warehouse (`src/db/`), vote processing (`VotesProcessor`), multi-source player merging (`PlayersProcessor`), match dataset preparation (`MatchDataBuilder`), probabilistic SinhArcsinh prediction (`FantacalcioPredictor`), and Monte Carlo lineup optimization (`LineupOptimizer`).
- Use only confirmed transfers for the active roster dataset. Keep rumours in a separate watchlist and never merge them into eligible players.
- Record a source URL and `checked_at` date for every roster or transfer assertion. The transfer market remains open until 1 September 2026, so refresh before every auction or model run.
- Keep raw, source-derived data out of Git unless it is small and redistributable. Store generated exports in `data/` (ignored).
- Add or update tests for behaviour changes. Do not make live network calls in tests.
- The SQLite research warehouse in `src/db/` is authoritative for data retrieval. The schema is versioned: bump `src/db/__init__.py::__version__` and `pyproject.toml` together with any schema change, and keep each ingestor idempotent (safe to re-run).
- Do not add runtime dependencies unless required; SQLite plus the standard library are preferred. If an ingestor needs a third-party package (e.g. `pandas`, `requests`), import it lazily inside the ingestor and document it.
- FBref is never scraped. Import FBref data only from browser-exported CSV files placed under `data/season_*_27/manual/`. Never add logic that defeats a 403 or other access control.
- Probabilistic modeling utilizes the Sinh-Arcsinh (SHASH) distribution to capture skewed, heavy-tailed fantasy scores, providing floor (q10), median (q50), and ceiling upside (q90) predictions alongside Monte Carlo matchday simulations.
- Security & IP protection: Maintain a Dual-Repository architecture (Public Core repo for algorithms and models, Private Workspace for raw data and personal league configs). Pre-commit hooks (`.githooks/pre-commit`) are enforced to block accidental commits of databases, spreadsheets, or credentials.
- For every material change, update `CHANGELOG.md` and the relevant user-facing documentation, then stage and commit the coherent change set. Generated data and local environments remain untracked.

## Commands

```bash
python -m unittest discover -s tests -v
python scripts/run_pipeline.py --stage players --season 2627
python scripts/run_pipeline.py --stage training-data --season 2627
python scripts/run_pipeline.py --stage train --season 2627
python scripts/run_pipeline.py --stage predict --matchday 1 --season 2627
```

## Data contract

Roster records must contain: `player`, `club`, `role`, `status`, `source_url`, and `checked_at`. Valid `status` values are `confirmed`, `watchlist`, and `excluded`. A player can enter model or auction outputs only with `confirmed` status.
