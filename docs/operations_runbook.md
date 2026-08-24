# Operations Runbook

This runbook is the operational record for the public core and private data
workspace. Raw and licensed data stays in
`fantapredictor-workspace/data/`; only code, schemas, tests, and documentation
belong in the public repository.

## Reconcile 2026/27

Edit the private roster file:

```text
fantapredictor-workspace/data/season_2026_27/rosters/virgilio_rosters_2026_27.csv
```

Use official destination-club announcements or squad pages for registration,
the official Fantacalcio quotation page for classic/Mantra roles and prices,
and the official Lega Serie A calendar/club registry for the competition
population. Use transfer trackers only to discover candidates. Every row must
contain `player`, `club`, `role`, `status`, `source_url`, and `checked_at`.

Allowed statuses are `confirmed`, `watchlist`, and `excluded`. Keep a player as
`watchlist` until both club membership and fantasy role are evidenced. The
public starter template is `config/roster_reconciliation.example.csv`.

## Rebuild And Inspect SQLite

Run from the private workspace. The repository has no dependency on the
optional `sqlite3` shell:

```bash
cd /path/to/fantapredictor-workspace
export FANTAPREDICTOR_DATA_DIR="$PWD/data"
export PYTHON=/path/to/fantapredictor/.venv/bin/python

$PYTHON fantapredictor_core/scripts/build_database.py \
  --db data/fantapredictor.db \
  --season 2627

$PYTHON fantapredictor_core/scripts/inspect_database.py \
  --db data/fantapredictor.db summary

$PYTHON fantapredictor_core/scripts/inspect_database.py \
  --db data/fantapredictor.db sql \
  "SELECT status, COUNT(*) FROM roster_memberships GROUP BY status"

$PYTHON fantapredictor_core/scripts/inspect_database.py \
  --db data/fantapredictor.db sql \
  "PRAGMA foreign_key_check"
```

The latest rebuild reported schema `0.4.0`, integrity `ok`, 626 roster rows,
11,726 matches, 124,122 player-match ratings, 6,726 player-season rows, and
539 prices.

## Release Gate

```bash
$PYTHON fantapredictor_core/scripts/validate_release.py \
  --season 2627 \
  --require-confirmed \
  --require-lineup
```

This gate must pass before prediction or auction output. As of the latest
snapshot it fails because the confirmed pool contains only 3 midfielders and 1
defender, with no confirmed goalkeeper or forwards.

## Evaluate

```bash
$PYTHON fantapredictor_core/scripts/evaluate_model.py \
  --season 2024-25 \
  --cutoff-matchday 20 \
  --epochs 25 \
  --output data/season_2024_25/reports/model_evaluation.json
```

Read `docs/evaluation_results.md` before accepting a model. The model currently
loses to both the global-median and expanding-prior baselines.

## Predict And Optimize

These commands are intentionally blocked until the release gate passes:

```bash
$PYTHON fantapredictor_core/scripts/run_pipeline.py \
  --stage predict --season 2627 --matchday 1

$PYTHON fantapredictor_core/scripts/optimize_lineup.py \
  --season 2627 --matchday 1 \
  --strategy expected_value --formation 3-4-3
```

## Git Synchronization

Commit and push public code first. Then update the private submodule and push
the private workspace:

```bash
cd /path/to/fantapredictor
git status --short --branch
git push origin main

cd /path/to/fantapredictor-workspace
git -C fantapredictor_core fetch origin main
git -C fantapredictor_core switch --detach origin/main
git add fantapredictor_core
git commit -m "Update public core submodule"
git push origin main
```

Activate the private credential hook once per clone:

```bash
git config core.hooksPath .githooks
```
