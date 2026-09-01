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

The official feed was refreshed after closure at 21:32 CEST on 1 September.
Repeat the reconciliation for any official correction and after the winter
window. The active population uses Venezia and excludes relegated Verona.

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

The post-closure 1 September rebuild reported schema/ingestion version `0.6.0`,
integrity `ok`, zero foreign-key errors, 861 roster rows, 11,746 matches,
124,760 player-match ratings, 7,096 player-season rows, and 587 prices. All
matches carry a matchday. The active season contributes 20 completed matches,
638 official player-match ratings, and 370 Understat player-season rows.

## Release Gate

```bash
$PYTHON fantapredictor_core/scripts/validate_release.py \
  --season 2627 \
  --require-confirmed \
  --require-lineup
```

This roster gate must pass before prediction or auction output. The 21:32 CEST
snapshot passes with 31 goalkeepers, 88 defenders, 83 midfielders, and 86
forwards confirmed. Model approval is a separate gate and currently fails.

## Evaluate

```bash
$PYTHON fantapredictor_core/scripts/evaluate_model.py \
  --season 2024-25 \
  --cutoffs 10,20,30 \
  --epochs 25 \
  --output data/season_2024_25/reports/model_walk_forward_evaluation.json
```

Read `docs/evaluation_results.md` before accepting a model. The model currently
loses to both the global-median and expanding-prior baselines.

## Predict And Optimize

For research-only output after training a model, run:

```bash
$PYTHON fantapredictor_core/scripts/run_pipeline.py \
  --stage predict --season 2627 --matchday 3

$PYTHON fantapredictor_core/scripts/optimize_lineup.py \
  --season 2627 --matchday 3 \
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
