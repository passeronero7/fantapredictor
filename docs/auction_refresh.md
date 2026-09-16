# Serie A refresh and 8-manager auction dossier

The 16 September 2026 private snapshot supersedes the earlier September
counts. It contains 40 completed fixtures, the 380-fixture calendar, 1,274
observed Fantacalcio ratings across four complete matchdays, 437 Understat
player-season aggregates, 595 public quotations, 6,545 Fantacalcio summary
metrics, probable XIs for all 20 clubs and 61 availability notices.

The supplied league XLSX remains authoritative for eligibility and Classic
roles. Its snapshot date is 5 September: 531 players are eligible, 62 are
flagged outside the list and two newer public entries are excluded pending
a refreshed league export. The database and public quotations cannot attest
to later private league decisions. No league credentials are required.

## Reproduce

Run from the public core or the workspace submodule with the existing Python
environment. First take a SQLite `Connection.backup()` and copy the active
season directory into the ignored workspace `data/backups/` directory.
Do not rebuild or wipe the warehouse: additive ingestion preserves history,
attributes and manually curated sources.

```bash
python scripts/download_auction_snapshot.py \
  --snapshot /path/to/workspace/data/season_2026_27/raw/refresh_2026_09_16 \
  --last-matchday 4

python scripts/prepare_auction_snapshot.py \
  --snapshot /path/to/workspace/data/season_2026_27/raw/refresh_2026_09_16 \
  --league-list /path/to/league_export.xlsx \
  --data-dir /path/to/workspace/data \
  --checked-at <checked_at-from-acquisition_manifest.json>

python scripts/build_auction_dossier.py \
  --data-dir /path/to/workspace/data --as-of 2026-09-16
```

Use a new dated directory for the next refresh. Increase `--last-matchday`
only after every club's votes are published; the downloader refuses incomplete
rounds. Raw snapshots and `acquisition_manifest.json` stay private. The
offline step imports normalized files into SQLite and can be rerun safely.
Run it after a warehouse rebuild as well: the legacy general build manifest
does not declare the new summary metrics or identity bridge. The season and
the original private league-list date in this workflow are currently specific
to this 2026/27 project; update the documented list date when replacing it.

## Data contract and quality controls

- Missing league membership defaults to excluded in schema v6. The migration
  is additive; a plain public quotation refresh never clears known flags.
- Provider IDs resolve the private list. Name matching for Understat requires
  a unique whole-token/initial match within the current club, with goalkeeper
  role consistency. At this snapshot 414 of 437 rows are bridged; the 23
  unresolved rows remain available for review and never receive guessed links.
- Universal player identities are retained. Only superseded club attributions
  for the same Understat source ID and season are replaced, preventing double
  counting transferred players' cumulative season totals.
- Future fixtures retain null scores and produce no observed team statistics.
  Array-derived Understat rounds are accepted only if each round contains ten
  games and all 20 clubs exactly once, and all 380 directed fixtures are unique.
  This checks internal consistency, not official rescheduling: reconcile round
  assignments explicitly if a later postponed fixture fails the check.
- Football-Data results remain separate provider records. Team-history readers
  count each fixture once, preferring the row with observed shot statistics.
  Understat xG remains separately identified in the dossier.
- Current vote URLs now retain their official player ID. This corrects legacy
  abbreviation/namesake joins (including the two Thiam identities), without
  deleting historical player records. The workbook preserves discrepancies
  between published season summaries and the downloaded daily marks instead
  of silently overwriting one with the other.
- Availability text and source dates are retained locally. Vague return windows
  are not stored as exact dates. Old expected-return guesses are superseded;
  a null return date does **not** imply full availability. Consult the explicit
  availability risk flag before using any forecast appearance rate.
- Each source loader commits independently; the download is separate from DB
  ingestion. Retain the backup until integrity, coverage and release gates pass.

## Auction outputs and limitations

The dated output directory contains `Dossier_asta_8_500.xlsx`, CSV sheets,
`LEGGIMI.md` and `impostazioni_e_limiti.json`. SQLite supplies the observed
ratings, historical averages, advanced aggregates, calendar and club statistics;
current source CSVs supply the provider spellings and narrative availability.
The workbook exposes exclusions, missing identities, per-club coverage,
minutes, npxG+xA/90, xGChain/xGBuildup, shots, key passes, bonuses, recent marks,
2025/26 comparisons and the G5 probable XI.

Classic 3P/8D/8C/6A is an explicit assumption pending the user's rules. The
two 500-credit scenarios reserve 10 credits and allocate P/D/C/A respectively
45/100/120/225 with a defence modifier or 45/65/130/250 without one. Expected
league slots are eight times those roster positions. Provider FVM weights
distribute each role budget after reserving one credit per slot. Prudence and
stretch thresholds are planning choices, not calibrated clearing prices.
The stretch threshold also reserves one credit for each other slot in the
same role. A live auction still requires tracking actual spending and open slots.

Four matchdays remain a small sample. No new SHASH training/approval is claimed,
and neither neural outputs nor the old MD3 propensity export drive dossier
prices. FBref is not scraped; pressing, duels and individual goalkeeper PSxG
are outside the downloaded coverage. Calendar dates come from Understat,
not an asserted official future-fixture feed.

The requested “Saturday 25” is unresolved: 25 September 2026 is Friday,
Saturday is 26 September. No exact auction date or defence-modifier rule is
silently recorded as confirmed. Refresh after G5 and again before the auction.

## Validation

Run the unit suite without live HTTP calls, then `validate_release.py --season
2627 --require-confirmed --require-lineup --require-priced` with the private
`FANTAPREDICTOR_DATA_DIR`. Check SQLite integrity and foreign keys, four full
rounds, 20-club coverage, unique source identities and the eligibility gate.
Inspect the dated refresh/quality reports before relying on the workbook.
