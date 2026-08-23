# FantaPredictor 2026/27

An evidence-led probabilistic prediction and research engine for Serie A Fantacalcio 2026/27.

## Current state

The codebase implements:
- FBref data collection and utility modules (`src/scrapers/`, `src/utils/`).
- 20-club Serie A roster downloading and open historical stats matching (`scripts/download_baseline_data.py`).
- Explainable empirical-Bayes pre-season confidence scoring (`src/models/confidence_model.py`).
- SQLite research warehouse with normalized schema (`src/db/`).
- Weekly vote parsing and multi-source player merging (`src/data_processing/votes_processor.py`, `src/data_processing/players_processor.py`).
- Match dataset preparation (`src/data_processing/match_data_builder.py`).
- Probabilistic prediction with Sinh-Arcsinh (SHASH) distribution modeling expected fantasy points and upside/downside quantiles (`src/models/neural_network.py`, `src/models/distributions.py`), inspired by top-down probabilistic modeling concepts from USA fantasy football (`amiles2233/ff_prob`).
- Monte Carlo lineup optimizer with formation constraints and Serie A *Modificatore Difesa* bonus calculations (`src/models/lineup_optimizer.py`).

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

# Run data pipeline stages
python scripts/run_pipeline.py --stage players --season 2627
python scripts/run_pipeline.py --stage training-data --season 2627
python scripts/run_pipeline.py --stage train --season 2627
python scripts/run_pipeline.py --stage predict --matchday 1 --season 2627
```

## Bootstrap the roster database

```bash
.venv/bin/python scripts/download_baseline_data.py --season 2627
```

This creates an ignored local snapshot in `data/season_2026_27/`: a 20-club player list, raw Understat archive, matched historical player-season rows, and a coverage report. The snapshot is provisional during the transfer window; it is not a Fantacalcio role or vote list.

## Player confidence baseline

An explainable empirical-Bayes baseline ranks roster players using recent, open historical event data and your league's scoring weights. It reports potential and evidence confidence separately; see the [model documentation](docs/player_confidence_model.md).

## Probabilistic Modeling & Inspiration from `ff_prob`

Our predictive architecture adapts concepts from `amiles2233/ff_prob`:
1. **Top-Down Conditioning:** Situating players within team and match tempo/odds context.
2. **Sinh-Arcsinh (SHASH) Distributions:** Capturing right-skewed explosive scoring for attackers ($\epsilon > 0$) and fat tails ($\delta$).
3. **Monte Carlo Optimization:** Simulating $N$ matchday slates to optimize lineups for expected value or tournament upside while accounting for Serie A rules (*Modificatore Difesa*).
See the full evaluation in [`docs/probabilistic_modeling_and_ff_prob_evaluation.md`](docs/probabilistic_modeling_and_ff_prob_evaluation.md).

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
