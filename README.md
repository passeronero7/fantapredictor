# FantaPredictor 2026/27

An evidence-led probabilistic prediction and research engine for Serie A Fantacalcio 2026/27.

## Current state

The codebase implements:
- FBref manual-export validation and utility modules (`src/data_processing/`, `src/utils/`).
- 20-club Serie A roster downloading and open historical stats matching (`scripts/download_baseline_data.py`).
- Explainable empirical-Bayes pre-season confidence scoring (`src/models/confidence_model.py`).
- SQLite research warehouse with normalized schema (`src/db/`).
- Weekly vote parsing and multi-source player merging (`src/data_processing/votes_processor.py`, `src/data_processing/players_processor.py`).
- Match dataset preparation (`src/data_processing/match_data_builder.py`).
- Probabilistic prediction with Sinh-Arcsinh (SHASH) distribution modeling expected fantasy points and upside/downside quantiles (`src/models/neural_network.py`, `src/models/distributions.py`), inspired by top-down probabilistic modeling concepts from USA fantasy football (`amiles2233/ff_prob`).
- Monte Carlo lineup optimizer with formation constraints and Serie A *Modificatore Difesa* bonus calculations (`src/models/lineup_optimizer.py`).
- Offline source ingestors and a reproducible SQLite builder (`scripts/build_database.py`).

The current release is not yet an auction-ready prediction release. The active
post-deadline 2026/27 snapshot checked at 21:32 CEST on 1 September contains
288 confirmed, 558 watchlist, and 15 excluded memberships and passes the legal
default 3-4-3 roster gate. The SHASH model is implemented and evaluated, but
the leakage-safe 2024/25 walk-forward study still shows the expanding-prior and
global-median baselines outperforming it. See the
[evaluation record](docs/evaluation_results.md) and
[operations runbook](docs/operations_runbook.md).

The 2026/27 roster research remains a live dataset rather than frozen truth;
the summer-market closure snapshot was taken after 20:00 CEST on 1 September
2026 and should still be refreshed for official corrections and the winter
window. The current competition population includes Venezia and excludes
relegated Verona. See the [scouting brief](docs/season_2026_27_roster_scouting.md)
for the roster policy, club population, and source hierarchy.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m unittest discover -s tests -v
```

## Available workflow

```bash
# Download official matchday votes, current stats/results, and quotations
python scripts/download_historical_votes.py --season 2026-27 --start 1 --end 2
python scripts/download_understat_season.py --season 2026
python scripts/download_current_prices.py --season 2026-27
python scripts/download_match_results.py --start-year 1993 --end-year 2025
python scripts/download_understat_data.py --season 2627
python scripts/build_database.py --db data/fantapredictor.db --season 2627
python scripts/inspect_database.py --db data/fantapredictor.db summary

# Run data pipeline stages
python scripts/run_pipeline.py --stage manual-fbref --season 2627
python scripts/run_pipeline.py --stage players --season 2627
python scripts/run_pipeline.py --stage training-data --season 2627 --include-history
python scripts/run_pipeline.py --stage train --season 2627
python scripts/run_pipeline.py --stage predict --matchday 1 --season 2627
python scripts/run_pipeline.py --stage lineup --matchday 1 --season 2627
python scripts/evaluate_model.py --season 2425 --cutoffs 10,20,30
```

Before an auction or model run, validate the private snapshot:

```bash
FANTAPREDICTOR_DATA_DIR=/path/to/fantapredictor-workspace/data \
  python scripts/validate_release.py --season 2627 --require-confirmed --require-lineup
```

When running the core from the private workspace, point it at the workspace
data directory without changing the submodule:

```bash
FANTAPREDICTOR_DATA_DIR=/path/to/fantapredictor-workspace/data \
  python fantapredictor_core/scripts/build_database.py
```

## Bootstrap the roster database

```bash
.venv/bin/python scripts/download_baseline_data.py --season 2627
```

This creates an ignored local snapshot in `data/season_2026_27/`: a 20-club player list, raw Understat archive, matched historical player-season rows, and a coverage report. The roster records are `watchlist` until each player is manually reconciled against official registration/transfer evidence and the fantasy role list; they are not eligible for modelling or auction outputs until promoted to `confirmed`.

## Live Understat snapshot

To retrieve a current Serie A player-season snapshot through `soccerdata`, run
`python scripts/download_understat_data.py --season 2627`. It writes an
ingestor-compatible CSV and a provenance manifest under
`data/season_2026_27/raw/soccerdata/`. Pass that CSV explicitly to
`scripts/build_database.py --understat <path>` when it should replace the
aggregate archive for a warehouse build. Refreshing an existing snapshot
requires `--overwrite`.

## Player confidence baseline

An explainable empirical-Bayes baseline ranks roster players using recent, open historical event data and your league's scoring weights. It reports potential and evidence confidence separately; see the [model documentation](docs/player_confidence_model.md).

## Probabilistic Modeling & Inspiration from `ff_prob`

Our predictive architecture adapts concepts from `amiles2233/ff_prob`:
1. **Top-Down Conditioning:** Situating players within team and match tempo/odds context.
2. **Sinh-Arcsinh (SHASH) Distributions:** Capturing right-skewed explosive scoring for attackers ($\epsilon > 0$) and fat tails ($\delta$).
3. **Monte Carlo Optimization:** Simulating $N$ matchday slates to optimize lineups for expected value or tournament upside while accounting for Serie A rules (*Modificatore Difesa*).
See the full evaluation in [`docs/probabilistic_modeling_and_ff_prob_evaluation.md`](docs/probabilistic_modeling_and_ff_prob_evaluation.md).

The complete retrieval and build contract is in [`docs/data_pipeline.md`](docs/data_pipeline.md).

The current defender auction analysis is documented in [`docs/auction_defender_analysis.md`](docs/auction_defender_analysis.md); rerun `scripts/analyze_defenders.py` after the transfer window closes.

## Security & Dual-Repository Architecture

To protect intellectual property and comply with third-party website Terms of Service:
- **Public Core Repo:** Contains algorithms, Bayesian models, schemas, and synthetic tests.
- **Private Workspace Repo:** Holds raw data spreadsheets, local SQLite databases (`fantacalcio.db`), and personal league configs.
- **Pre-Commit Protection:** Automated hook in `.githooks/pre-commit` prevents accidental commits of database files (`.db`, `.sqlite`), spreadsheets (`.xlsx`), or API keys.
See the full setup and future merge guide in [`docs/repository_architecture_and_security.md`](docs/repository_architecture_and_security.md).

## Project map

- `AGENTS.md` — working rules, commands, and roster data contract.
- `CHANGELOG.md` — change history and known limitations.
- `docs/` — time-stamped research notes, probabilistic modeling evaluation, and security architecture.
- `config/` — `settings.py` (paths, hyperparameters) plus example CSV/JSON templates for private data the workspace supplies (rosters, coaches, league rules) and the declared `data_sources.json` ingestion manifest.
- `scripts/` — one CLI entry point per file, run as `python scripts/<name>.py`: downloaders (`download_*`), the warehouse builder (`build_database.py`), the orchestrator (`run_pipeline.py`), evaluation/inspection (`evaluate_model.py`, `inspect_database.py`), and standalone analysis tools (`analyze_defenders.py`, `optimize_lineup.py`, `reconcile_official_transfers.py`, `prepare_manual_fbref.py`).
- `src/` — modular Python package:
  - `src/db/` — the SQLite warehouse: `database.py` (connection, schema, versioned migrations), `build.py` (manifest resolution, checksum-skip, per-source error isolation), `repository.py` (the single read path for scripts and models), `schema.sql`, and `ingestors/` (one loader per source, e.g. `votes.py`, `understat.py`, `football_data.py`).
  - `src/data_processing/` — DataFrame-level transforms between raw exports and the warehouse or model inputs (`votes_processor.py`, `players_processor.py`, `match_data_builder.py`, `prices_processor.py`, `fbref_manual.py`, `soccerdata_understat.py`).
  - `src/models/` — the probabilistic prediction and optimization layer (`neural_network.py`, `distributions.py`, `evaluation.py`, `confidence_model.py`, `lineup_optimizer.py`).
  - `src/utils/` — small cross-cutting helpers (`name_matching.py`).
- `tests/` — one file per module under test, run with `python -m unittest discover -s tests` or `pytest`.

This structure was deliberately kept as-is rather than reorganized into deeper
subpackages (e.g. grouping `scripts/` by workflow stage): with roughly 60
Python files split across four purpose-named `src/` packages plus a flat
`scripts/`/`tests/`, further nesting would mean updating every doc and
cross-script import for little navigability gain. See `CHANGELOG.md`
`[Unreleased]` for that evaluation.
