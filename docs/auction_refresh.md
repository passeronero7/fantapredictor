# Serie A refresh and 8-manager auction dossier

## 23 September 2026 refresh (current)

Snapshot `refresh_2026_09_23` (acquired 13:31 UTC, `--last-matchday 5`):
matchdays 1-5 complete (1,590 ratings, 50 Football-Data results), matchday-6
probable XIs, 597 quotations, 48 availability notices. Compared with
16 September: no club or Classic-role changes; two public additions (Lovric,
Esteban) remain outside the 5 September league list; 240 quotation and 78
FVM moves of at least 5. The official Fantacalcio quotations export of the
same day (534 active + 63 sold) matches the scraped prices exactly; its only
disagreement with the league list is Piana (Udinese, sold but still listed).
The import rewrites the availability CSVs, so 38 return dates were re-derived
from the source windows and re-ingested (rule in `AGENTS.md`). The dossier
(`asta_8_500_2026_09_23`) now labels the latest matchday automatically and
lists each club's coach, module and in-season changes. Coach history and the
forecast's coach conditioning are documented in `docs/coach_conditioning.md`.

## Live auction (masterplan phase 2)

`scripts/live_auction.py` is the auction-day console; `optimize_auction_roster.py
--state` produces the same plan as files. Both read an append-only log
`giocatore,acquirente,prezzo` (workspace `asta/stato_asta.csv`), resolve names
ignoring case and accents (official ids work too), and after every sale:

- remove players bought by others, force your own buys at the price paid;
- rescale the reference cost of unsold players by the **market factor**:
  credits left across the league divided by the reference cost of the
  players needed to fill the league's open slots (per role). It starts at
  ~1 and falls when others overspend early;
- re-solve the roster MILP for the open slots (~0.1-1 s thanks to exact
  dominance pruning, which provably keeps the optimum);
- on request, the **maximum bid** for the player on the block (~0.2-4 s):
  the price at which buying him leaves the plan exactly as good as the best
  plan without him, capped by the legal maximum (credits left minus one per
  other open slot). It is found on the real MILP (linear estimate from the
  marginal value of a credit, then bracketed interpolation); on the 23
  September data it is within 3 credits of an exact bisection for every
  player checked, plan or not (e.g. De Gea 55 vs 54, Martinez L. 140 vs 140).

The maximum bid replaces the dossier's `soglia_estesa` as the operating
guide. Read it as an indifference price, not a target: buy at or below the
reference when possible and never above the maximum. Late in the auction, or
whenever many near-equivalent players remain, credits are worth little to
the plan and maximum bids rise far above references; that is a property of
the forecast's flat utilities, not a solver error.

A mock auction of 24 sales (4 own, 20 to 6 rivals, prices 1-2x reference),
including an unknown name, a double sale and an undo, ran end to end in
12.6 s. The MILP now solves to optimality (`MIP_REL_GAP = 1e-9`): the HiGHS
default 0.01% tolerance (~0.009 objective) was as large as the gaps between
near-equivalent plans, and the published 23 September roster (objective
86.702) was such a near-optimum; the true optimum is 86.705.

## 19 September 2026 refresh (historical)

The 19 September 2026 private snapshot (`refresh_2026_09_19`, acquired at
00:03 UTC) supersedes the 16 September one. It contains 41 completed
fixtures (matchdays 1-4 plus Monza-Sassuolo 2-1, the Friday opener of
matchday 5), the 380-fixture calendar, 1,274 observed Fantacalcio ratings
across four complete matchdays, 439 Understat player-season aggregates
(417 bridged to provider identities), 597 public quotations, 6,567
Fantacalcio summary metrics, matchday-5 probable XIs for all 20 clubs and
55 availability notices. Matchday 5 was in progress at snapshot time
(votes published for two clubs only), so the downloader was run with
`--last-matchday 4`; its votes are deliberately absent and the provider's
season summary already includes the Monza/Sassuolo marks, which is why the
dossier's `Discrepanze_fonte` sheet grew from 92 to 115 rows.

Compared with 16 September: two public quotation rows were added
(Lovric/Udinese, Esteban/Lecce), both outside the 5 September league list
and therefore `fuori_lista`; no club or Classic-role changes; FVM moved
for two players (Mastantuono 39→70, De Bruyne 103→97); eight players left
the availability page and two entered it (Spinazzola/Napoli, Terzic/
Frosinone); six clubs changed their probable XI or module. Results from
16 September (40 completed fixtures, 437 aggregates, 595 quotations, 61
notices) were retained in `data/backups/refresh_2026_09_19/`; on 24 September the
backups were reduced to files with no identical copy elsewhere (the
databases and the uncorrected 16 September dossier).

The supplied league XLSX remains authoritative for eligibility and Classic
roles. Its snapshot date is 5 September: 531 players are eligible, 62 are
flagged outside the list and two newer public entries are excluded pending
a refreshed league export. The database and public quotations cannot attest
to later private league decisions. No league credentials are required.

## Reproduce

Run every step with `FANTAPREDICTOR_DATA_DIR` pointing at the private
workspace `data/` directory (the core clone's own `data/` is empty on
purpose). First take a SQLite `Connection.backup()` of the warehouse and copy
the active season files into the ignored workspace `data/backups/`
directory. Do not rebuild or wipe the warehouse: additive ingestion preserves
history, attributes and manually curated sources.

```bash
export FANTAPREDICTOR_DATA_DIR=/path/to/workspace/data
SEASON=$FANTAPREDICTOR_DATA_DIR/season_2026_27

# 1. Download a dated snapshot (network). --last-matchday = last round whose
#    votes are published for all 20 clubs; the downloader refuses otherwise.
python scripts/download_auction_snapshot.py \
  --snapshot $SEASON/raw/refresh_YYYY_MM_DD --last-matchday N

# 2. Import it (offline, idempotent). The league list is the private Leghe
#    export; checked_at comes from the snapshot's acquisition_manifest.json.
python scripts/prepare_auction_snapshot.py \
  --snapshot $SEASON/raw/refresh_YYYY_MM_DD \
  --league-list $SEASON/fantacalcio/<league_export>.xlsx \
  --data-dir $FANTAPREDICTOR_DATA_DIR --checked-at <checked_at>

# 3. The import rewrites the availability CSVs without return dates:
#    re-derive them from the source windows, keep the twin file identical,
#    and ingest.
python scripts/ingest_availability.py --csv $SEASON/coaches/availability_current.csv \
  --derive-dates --as-of YYYY-MM-DD
cp $SEASON/coaches/availability_current.csv $SEASON/coaches/injuries_2026_27.csv

# 4. Coach changes since the last refresh: edit coaches/coach_history.csv
#    (see AGENTS.md), then load it (idempotent).
python scripts/ingest_coaches.py --csv $SEASON/coaches/coach_history.csv

# 5. Dossier, forecast (from the first unplayed matchday, 8 rounds; --as-of
#    = that matchday's date) and rosters.
python scripts/build_auction_dossier.py --data-dir $FANTAPREDICTOR_DATA_DIR --as-of YYYY-MM-DD
python scripts/simulate_auction_propensity.py --season 2627 --from-matchday N+1 \
  --matchdays 8 --simulations 10000 --seed 20260922 --as-of <date of N+1> \
  --output $SEASON/outputs/auction_propensity_2627_after_mdN_coach.csv
python scripts/optimize_auction_roster.py \
  --forecast $SEASON/outputs/auction_propensity_2627_after_mdN_coach.csv \
  --dossier-players $SEASON/outputs/asta_8_500_YYYY_MM_DD/giocatori.csv \
  --output-dir $SEASON/outputs/rosa_ideale_post_gN_YYYY_MM_DD_coach \
  --reserve 10 --defence-modifier --db $FANTAPREDICTOR_DATA_DIR/fantapredictor.db
```

Use a new dated directory for every refresh. Raw snapshots and
`acquisition_manifest.json` stay private. Step 2 can be rerun safely, and must
be rerun after a warehouse rebuild: the legacy general build manifest does
not declare the summary metrics or identity bridge. The season and the
private league-list file name are specific to this 2026/27 project.

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

Classic 3P/8D/8C/6A is the supplied roster structure. The defence modifier is
the average of goalkeeper plus the best three defenders: +1 strictly above
6.5 and +3 strictly above 7.0. The two 500-credit scenarios reserve 10 credits
and allocate P/D/C/A respectively 45/85/125/235 with the modifier or
45/65/130/250 without it. Expected
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
Saturday is 26 September. Refresh again once G5 is complete (last
fixture Milan-Lecce, Sunday 20 September) with `--last-matchday 5`, and
again before the auction.

## Validation

Run the unit suite without live HTTP calls, then `validate_release.py --season
2627 --require-confirmed --require-lineup --require-priced` with the private
`FANTAPREDICTOR_DATA_DIR`. Check SQLite integrity and foreign keys, four full
rounds, 20-club coverage, unique source identities and the eligibility gate.
Inspect the dated refresh/quality reports before relying on the workbook.
