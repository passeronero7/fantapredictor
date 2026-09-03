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

The Lega feed can lag deadline-day registrations. After running it, bridge the
fantasy universe with the official quotation list: promote watchlist rows that
the quotations evidence and adopt priced players the roster snapshot is
missing. Review the dry-run report first; `--apply` writes the roster CSV:

```bash
$PYTHON fantapredictor_core/scripts/promote_roster_from_prices.py \
  --season 2627            # dry run: promotion report
$PYTHON fantapredictor_core/scripts/promote_roster_from_prices.py \
  --season 2627 --adopt-unmatched   # dry run incl. missing priced players
$PYTHON fantapredictor_core/scripts/promote_roster_from_prices.py \
  --season 2627 --adopt-unmatched --apply
$PYTHON fantapredictor_core/scripts/build_database.py \
  --db data/fantapredictor.db --season 2627 --rebuild --confirm-wipe
```

The rebuild is required after identity renames so stale memberships from old
player rows cannot linger. The September 2026 reconciliation produced 795
confirmed, 110 watchlist, and 32 excluded rows, with 503 of 587 priced players
joined to confirmed memberships and every club able to field a priced 3-4-3.

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

# From-scratch rebuild (drops and recreates the schema first):
$PYTHON fantapredictor_core/scripts/build_database.py \
  --db data/fantapredictor.db \
  --season 2627 --rebuild --confirm-wipe

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

This roster gate must pass before prediction or auction output. Add
`--require-priced` so every default-formation slot must be fillable with
priced confirmed players, not merely confirmed ones. The 21:32 CEST
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

The SHASH model currently fails its evaluation gate, so the predict stage
automatically falls back to labelled global-median/expanding-prior baseline
quantiles over priced confirmed players. The output records
`prediction_source` per row; treat it as the research baseline, not a model
verdict. For research-only output, run:

```bash
$PYTHON fantapredictor_core/scripts/run_pipeline.py \
  --stage predict --season 2627 --matchday 3

$PYTHON fantapredictor_core/scripts/optimize_lineup.py \
  --season 2627 --matchday 3 \
  --strategy expected_value --formation 3-4-3
```

## Git Synchronization

`fantapredictor-workspace/scripts/sync_workspace.sh` automates this flow: it
pushes a configured public-core dev clone first (`FANTAPREDICTOR_CORE_REPO`,
default `../fantapredictor` next to the workspace), refuses to continue if
the `fantapredictor_core` submodule itself has uncommitted changes, then
fetches/detaches the submodule to `origin/main` and commits and pushes the
workspace:

```bash
cd /path/to/fantapredictor-workspace
./scripts/sync_workspace.sh
```

Equivalent by hand -- commit and push public code first, then update the
private submodule and push the private workspace:

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
