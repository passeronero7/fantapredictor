# Data Pipeline

The project separates network retrieval from local ingestion:

1. Download or manually export source snapshots.
2. Keep those snapshots under `data/`, which is ignored by Git.
3. Build the local SQLite warehouse from those snapshots.
4. Train only on observed ratings and evaluate chronologically.

FBref is the exception to automated downloads. Export the required tables in a
browser and place them under `data/season_<season>/manual/`; the pipeline only
validates and reads those local CSVs. The warehouse imports every numeric
column with its source file, table category, original FBref header, and a
normalized metric key.

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

For the first two completed 2026/27 matchdays:

```bash
python scripts/download_historical_votes.py \
  --season 2026-27 --start 1 --end 2 --delay 0.5
```

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

For the in-progress current season, retrieve one public Understat snapshot and
then rebuild. The player snapshot retains xG, xA, npxG, shots, key passes,
xGChain, and xGBuildup. A companion match snapshot retains completed fixtures,
scores, matchdays, and home/away xG:

```bash
python scripts/download_understat_season.py --season 2026
python scripts/build_database.py --season 2627
```

Refresh official incoming transfers with the Lega Serie A public Calciomercato
feed. Every change gets an official per-transfer URL and a retrieval timestamp;
missing official role labels remain watchlist rather than being guessed:

```bash
python scripts/reconcile_official_transfers.py --season 2627
python scripts/validate_release.py --season 2627 --require-confirmed --require-lineup
```

Alternatively, the `soccerdata` Understat adapter exports the same player-season
column contract together with a source URL and retrieval-time manifest. It is a
fallback for the direct snapshot above; it does not include the companion match
snapshot:

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

See [club-grade data strategy](club_grade_data_strategy.md) for the lawful
source hierarchy, snapshot policy, and analysis features.

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
Understat player and completed-match snapshots, current roster snapshot,
Football-Data match files, and the current quotation CSV when present. If a
`manual/` directory exists, it also imports local FBref exports. Supported
filenames are:

```text
fbref_standard_<season>.csv           fbref_shooting_<season>.csv
fbref_passing_<season>.csv            fbref_pass_types_<season>.csv
fbref_goal_shot_creation_<season>.csv fbref_defense_<season>.csv
fbref_possession_<season>.csv         fbref_playing_time_<season>.csv
fbref_misc_<season>.csv               fbref_keeper_<season>.csv
fbref_advanced_keeper_<season>.csv
```

`fbref_scouting_<season>.csv` remains supported as a legacy filename. Each
file must contain a `Player`/`player` column; `Squad`/`Team` is strongly
recommended. Values are exposed with an `fbref_` prefix in player merges, so
they cannot be confused with official Fantacalcio votes or targets. Do not use
season-end aggregate exports as features for earlier matchdays: they are useful
for scouting and research, but would leak future information into training.

The Understat archive also retains `xGChain` and `xGBuildup` in the stable
player-season table, alongside xG, xA, npxG, shots, key passes, and event
totals. These two measures capture a player's involvement in moves that end in
an expected-goal chance and in the build-up before the final action.

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
With `--include-history`, it loads all observed vote seasons through the target
season and derives a roster snapshot from that season's observed players.
Understat season aggregates are restricted to seasons strictly before each
target season. It also replaces all-season vote aggregates with season-scoped,
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
