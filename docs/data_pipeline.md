# Data Pipeline

The project separates network retrieval from local ingestion:

1. Download or manually export source snapshots.
2. Keep those snapshots under `data/`, which is ignored by Git.
3. Build the local SQLite warehouse from those snapshots.
4. Train only on observed ratings and evaluate chronologically.

FBref is the exception to automated downloads. Export the required tables in a
browser and place them under `data/season_<season>/manual/`; the pipeline only
validates and reads those local CSVs.

## Source Downloads

### Official Fantacalcio ratings

The public HTML archive provides official player ratings, fantasy ratings, and
bonus/malus events for historical Serie A matchdays.

```bash
python scripts/download_historical_votes.py \
  --season 2024-25 --start 1 --end 38 --delay 0.5
```

Repeat for the seasons required by the experiment. The downloader writes one
CSV per matchday plus a convenience `Full.csv`. The loader ignores `Full.csv`
to avoid double-counting the daily files.

### Fantacalcio quotations

The public quotations page supplies classic/mantra roles, initial/current price,
and FVM. The current snapshot is used by the 500-credit lineup optimizer.

```bash
python scripts/download_current_prices.py --season 2026-27
```

### Football-Data.co.uk results and odds

```bash
python scripts/download_match_results.py \
  --start-year 1993 --end-year 2025 --delay 0.5
```

Files are stored as `data/raw/football-data.co.uk/<season>/I1.csv` and include
scorelines, half-time scores, shots, corners, cards, and bookmaker odds where
the source provides them.

### Understat and rosters

The existing baseline downloader creates a watchlist roster snapshot and the
Understat aggregate archive. It does not establish confirmed registration:

```bash
python scripts/download_baseline_data.py --season 2627
```

Promote only manually reconciled records to `confirmed`, keeping unresolved
players as `watchlist` or `excluded`. Downstream player processing fails closed
and admits confirmed records only.

For a current player-season feature snapshot, the `soccerdata` Understat
adapter exports the same column contract used by the existing Understat
warehouse ingestor, together with a source URL and retrieval-time manifest:

```bash
python scripts/download_understat_data.py --season 2627
python scripts/build_database.py --season 2627 \
  --understat data/season_2026_27/raw/soccerdata/understat_soccerdata_player_season_2627.csv
```

The adapter does not establish squad eligibility, fantasy role, or votes. It is
therefore a feature source only; use official/Fantacalcio data for those
contracts. The client cache remains next to the snapshot and may be discarded
with the ignored raw data. A repeat fetch refuses to overwrite data unless
`--overwrite` is supplied.

## Build the Warehouse

```bash
python scripts/build_database.py \
  --db data/fantapredictor.db \
  --season 2627
```

The core accepts `FANTAPREDICTOR_DATA_DIR` so the public submodule can use the
private workspace's data directory. The warehouse is the intended source for
pipeline retrieval; raw files are inputs to the builder, not model inputs.

The default build scans all `data/season_*/fantacalcio/voti/` directories, so
all downloaded historical vote seasons are loaded. It also loads the current
Understat archive, current roster snapshot, Football-Data match files, and the
current quotation CSV when present.

The build is idempotent for domain rows. Re-running it updates the same natural
keys instead of duplicating players, ratings, matches, odds, or prices. Every
run is recorded in `ingestion_runs`.

If the `sqlite3` shell is unavailable, inspect the warehouse with the bundled
standard-library CLI:

```bash
python scripts/inspect_database.py --db data/fantapredictor.db summary
python scripts/inspect_database.py --db data/fantapredictor.db sql \
  "SELECT status, COUNT(*) FROM roster_memberships GROUP BY status"
python scripts/inspect_database.py --db data/fantapredictor.db sql \
  "SELECT name, COUNT(*) FROM sqlite_master WHERE type = 'table' GROUP BY name"
```

Optional curated coach history can be loaded with:

```bash
python scripts/build_database.py \
  --db data/fantapredictor.db \
  --coaches config/coaches.example.csv
```

The example file is a schema template only. Replace it with records checked
against official club announcements or manually verified sources before use.

## Training Safety

`MatchDataBuilder` refuses to create synthetic targets when votes are absent.
For historical training rows it replaces all-season vote aggregates with
expanding prior-only aggregates, preventing the target matchday from leaking
into its own features. Missing fixture context is represented explicitly as
`context_available=0`; it is never silently converted to `is_home=1`.

`FantacalcioPredictor` is a TensorFlow deep network with a direct SHASH negative
log-likelihood. It persists both Keras models and scaler metadata. A model must
be trained on observed `target_vote` and `target_fantavoto` values before it can
serve predictions.

Chronological evaluation trains only on rows before the cutoff matchday and
scores the remaining rows without using their targets as features:

```bash
python scripts/evaluate_model.py --season 2024-25 --cutoff-matchday 20
```

The report includes vote/fantavoto MAE and RMSE, q10/q50/q90 coverage, and the
q10-q90 interval coverage and width. Use multiple cutoffs for an expanding
walk-forward study rather than treating one split as a final model verdict.

`LineupOptimizer` requires a price column and enforces the 500-credit default.
It uses a bounded beam search for legal formations and correlated Monte Carlo
draws by club before calculating the defence modifier.

Lineup optimization can be run from a saved prediction artifact:

```bash
python scripts/optimize_lineup.py --season 2627 --matchday 1 \
  --strategy expected_value --formation 3-4-3
```

The output contains the selected starters, total cost, budget remaining, base
points, defence modifier contribution, and simulation q10/q50/q90 results.

Use `scripts/validate_release.py --require-confirmed --require-lineup` before
an auction. It fails if roster provenance is missing, statuses are invalid,
confirmed roles are absent, no confirmed player exists, or the confirmed pool
cannot form the default 3-4-3 lineup. The private workspace can record a
checksum manifest with `scripts/create_data_manifest.py`; generated models and
prediction exports remain excluded from that source manifest.
