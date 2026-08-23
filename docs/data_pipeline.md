# Data Pipeline

The project separates network retrieval from local ingestion:

1. Download or manually export source snapshots.
2. Keep those snapshots under `data/`, which is ignored by Git.
3. Build the local SQLite warehouse from those snapshots.
4. Train only on observed ratings and evaluate chronologically.

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

The existing baseline downloader creates the current roster snapshot and the
Understat aggregate archive:

```bash
python scripts/download_baseline_data.py --season 2627
```

## Build the Warehouse

```bash
python scripts/build_database.py \
  --db data/fantapredictor.db \
  --season 2627
```

The default build scans all `data/season_*/fantacalcio/voti/` directories, so
all downloaded historical vote seasons are loaded. It also loads the current
Understat archive, current roster snapshot, Football-Data match files, and the
current quotation CSV when present.

The build is idempotent for domain rows. Re-running it updates the same natural
keys instead of duplicating players, ratings, matches, odds, or prices. Every
run is recorded in `ingestion_runs`.

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

`LineupOptimizer` requires a price column and enforces the 500-credit default.
It uses a bounded beam search for legal formations and correlated Monte Carlo
draws by club before calculating the defence modifier.
