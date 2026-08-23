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

The 2026/27 roster research is a live dataset, not a frozen truth: the summer market closes on 1 September 2026. See the [scouting brief](docs/season_2026_27_roster_scouting.md) for the roster policy, club population, sources, and first confirmed-transfer reconciliation queue.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m unittest discover -s tests -v
```

## Available workflow

```bash
# Download official historical matchday votes and ratings
python scripts/download_historical_votes.py --season 2024-25 --start 1 --end 38
python scripts/download_current_prices.py --season 2026-27
python scripts/download_match_results.py --start-year 1993 --end-year 2025
python scripts/build_database.py --db data/fantapredictor.db --season 2627

# Run data pipeline stages
python scripts/run_pipeline.py --stage manual-fbref --season 2627
python scripts/run_pipeline.py --stage players --season 2627
python scripts/run_pipeline.py --stage training-data --season 2627
python scripts/run_pipeline.py --stage train --season 2627
python scripts/run_pipeline.py --stage predict --matchday 1 --season 2627
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
- `src/` — modular Python package.
