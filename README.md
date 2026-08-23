# Fantacalcio 2026/27

An evidence-led workspace for Serie A roster scouting and the gradual rehabilitation of a legacy Fantacalcio prediction pipeline.

## Current state

The usable code is in `fantacalcio_refactored/`. It currently provides FBref data collection plus file and name-matching utilities. The old README overstated readiness: the vote-processing, player-merging, training-data, neural-network, and lineup-optimizer modules are absent. Those pipeline stages are intentionally out of scope until implemented and tested.

The 2026/27 roster research is a live dataset, not a frozen truth: the summer market closes on 1 September 2026. See the [scouting brief](docs/season_2026_27_roster_scouting.md) for the roster policy, club population, sources, and first confirmed-transfer reconciliation queue.

## Setup

```bash
cd fantacalcio_refactored
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m unittest discover -s tests -v
```

## Available workflow

```bash
cd fantacalcio_refactored
python scripts/run_pipeline.py --stage scrape --season 2627 --force
```

This writes 2026/27 FBref data under `data/season_2026_27/fbref_data/`. It makes live requests to FBref; respect rate limits and verify output before using it for any decisions.

## Bootstrap the roster database

```bash
cd fantacalcio_refactored
.venv/bin/python scripts/download_baseline_data.py --season 2627
```

This creates an ignored local snapshot in `data/season_2026_27/`: a 20-club player list, raw Understat archive, matched historical player-season rows, and a coverage report. The snapshot is provisional during the transfer window; it is not a Fantacalcio role or vote list.

## Project map

- `AGENTS.md` — working rules, commands, and roster data contract.
- `CHANGELOG.md` — change history and known limitations.
- `docs/` — time-stamped research notes.
- `fantacalcio_refactored/` — legacy Python package being repaired.

## Next milestones

1. Reconcile every 2026/27 player against official club and fantasy-provider sources after the market closes.
2. Implement and test vote ingestion and player-source merging.
3. Define the training target and validation protocol before building a new model.
4. Implement prediction and lineup optimisation only after the data pipeline is reproducible.
