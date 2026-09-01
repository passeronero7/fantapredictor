# Ingestion & Fixing Strategy

**Status:** implemented (B1, B2, B3, B4, A1, A5, and A2's baseline gate) --
see "Implementation status" below. Originally a proposal / design record
dated 1 September 2026.
**Scope:** public core (`fantapredictor`) ingestion layer, pipeline retrieval, and model-approval gate.

This document records two coupled strategies agreed after the 0.6.0 post-deadline
checkpoint:

1. **A — Fixing strategy**: the ordered debt-reduction and approval-gate plan.
2. **B — Clean, reusable DB ingestion**: the target architecture for how source
   snapshots become warehouse rows.

It is a design record, not a changelog entry. The rows below and
`CHANGELOG.md`'s `[0.7.0]` entry are the source of truth for what actually
shipped; the acceptance criteria under each item were verified against the
implementation (tests in `tests/test_manifest_build.py`,
`tests/test_db_schema.py`, `tests/test_run_pipeline.py`,
`tests/test_evaluate_model.py`) before this status line was written.

## Implementation status (2026-09-02)

| Item | Status | Notes |
|---|---|---|
| A1 -- unify retrieval on SQLite | Done | `run_pipeline.py`'s training stage now builds from `MatchDataBuilder` directly; `evaluate_model.py` already did. Remaining `read_excel` calls are the raw vote-spreadsheet ingestion path (a legitimate primary source, not a mid-output) and the unused `src/utils/file_io.py::read_excel_safe` helper (dead code, left as-is -- deleting unused modules was out of scope for this pass). |
| A2 -- feed the model gate | Partial | The hard pass/fail baseline gate (`evaluate_model.py`'s `gate_result`/exit code) is implemented. Broader historical player coverage and expected-minutes/availability features are **not** implemented here: coverage is a data-sourcing decision (which seasons/sources to prioritize, item 4 under "Decisions needed" was never answered), and expected-minutes needs per-match minutes data this warehouse does not currently ingest. The model still fails the gate on real data (see `docs/evaluation_results.md`) until that follow-up work happens. |
| A3 -- declared ingestion manifest | Done | Folded into B1. |
| A4 -- DB schema versioning + `--rebuild` | Done | Folded into B3/B4. |
| A5 -- workspace sync automation | Done | `fantapredictor-workspace/scripts/sync_workspace.sh`. |
| B1 -- declared sources manifest | Done | `config/data_sources.json` + `src/db/build.py`. |
| B2 -- ingestor contract (checksum-skip, error isolation) | Done | `source_checksums` table; `src/db/build.py::load_one_source`. Existing ingestors were wrapped, not rewritten. |
| B3 -- schema versioning on the DB | Done | `PRAGMA user_version`, `CURRENT_SCHEMA_VERSION`, ordered `MIGRATIONS` list in `src/db/database.py`. |
| B4 -- two build modes | Done | `--rebuild --confirm-wipe` (decision #3's explicit-confirmation answer), `--force`. |
| B5 -- repository as the single read path | Already done pre-existing | `src/db/repository.py` already covered ratings, players, prices, match context, and FBref skill stats; `MatchDataBuilder` and `evaluate_model.py` already read through it. No changes needed here. |

---

This document records two coupled strategies agreed after the 0.6.0 post-deadline
checkpoint:

1. **A — Fixing strategy**: the ordered debt-reduction and approval-gate plan.
2. **B — Clean, reusable DB ingestion**: the target architecture for how source
   snapshots become warehouse rows.

Implementation work was planned as phases and verified against the acceptance
criteria below before bumping the schema/ingestion version (now `0.7.0`).

---

## 1. Current state (pain points, as of 1 September 2026)

| # | Pain point | Evidence |
|---|---|---|
| 1 | Model fails its own gate | `docs/evaluation_results.md`: SHASH fantavoto MAE 1.860 vs global-median 0.801; intervals ~3x too wide; 9,670/9,865 test rows have no prior Understat minutes. |
| 2 | Dual retrieval path | `scripts/run_pipeline.py` stages `players`/`training-data`/`train` read/write `mid_outputs/*.xlsx`; `predict` reads SQLite. Same data, two shapes, two bug surfaces. |
| 3 | Magical path discovery | `scripts/build_database.py` derives inputs from globs (`raw/understat_serie_a_*_season.csv`, `season_*/fantacalcio/voti`) instead of a declared source list. |
| 4 | No DB schema versioning | version lives in `src/db/__init__.py` / `pyproject.toml`; migrations are a single hardcoded block in `src/db/database.py::_migrate_schema`; no `PRAGMA user_version`. |
| 5 | Reproducible rebuild impossible | `init_schema` never clears stale rows; incremental append is the only mode. |
| 6 | Fragile dual-repo sync | 9 + 7 unpushed commits, manual submodule `detach`-style update in `docs/operations_runbook.md`. |

The per-ingestor pattern (`start_run`/`finish_run` audit, idempotent upserts,
rollback on error) is already good (`src/db/ingestors/*.py`); the strategy
formalizes it, it does not replace it.

---

## 2. Strategy A — Fixing

Ordered by impact. Each item has a hard acceptance criterion.

### A1 (P0) Unify retrieval on the SQLite warehouse

- `scripts/run_pipeline.py` stages `players`, `training-data`, `train`,
  `predict` must read **only** `src/db/repository.py` and direct SQLite.
- Excel mid-outputs become optional artifacts written *after* the stage succeeds;
  they are never read as input.
- Single reader used by `MatchDataBuilder`, `FantacalcioPredictor`, and `evaluate_model.py`.

**Acceptance criterion:** no `.xlsx` file under `mid_outputs/` is read by any
script or model; a `grep` for `read_excel` in `scripts/` and `src/` only matches
artifact-writing calls or none.

### A2 (P0) Feed the Model gate

Next modeling work is *not* hyperparameter tuning:

1. Broader time-stamped historical player coverage (more seasons of votes + matched
   Understat/FBref minutes so >0% of test rows have prior minutes).
2. Expected-minutes / availability features.
3. Hard pass/fail baseline gate in `scripts/evaluate_model.py`: the SHASH model
   must beat the global-median and expanding-prior baselines on disjoint held-out
   windows, else the run exits non-zero and no model is approved.

**Acceptance criterion:** `evaluate_model.py --season 2024-25 --cutoffs 10,20,30`
exits 0, and `docs/evaluation_results.md` reports SHASH ≤ baselines on
aggregate fantavoto MAE and similar interval coverage.

### A3 (P1) Declared ingestion manifest

See Strategy B. Kills pain point 3.

### A4 (P1) DB schema versioning + `--rebuild`

See Strategy B. Kills pain points 4 and 5.

### A5 (P2) Workspace sync automation

- `scripts/sync_workspace.sh` implement the runbook's `Git Synchronization`
  section.
- Guard: fail before detaching the submodule if the core working tree is dirty.

**Acceptance criterion:** one command performs full sync and leaves both repos and
the submodule on matching heads.

---

## 3. Strategy B — Clean, reusable DB ingestion

### B1 Declared sources manifest

A **committed** manifest in the core repo, `config/data_sources.json`:

```json
{
  "version": 1,
  "sources": [
{"slug": "virgilio",   "kind": "roster",    "pattern": "season_{season_compact}/rosters/virgilio_rosters_{season_compact}.csv", "seasons": ["2026/27"]},
    {"slug": "understat",  "kind": "player-season", "pattern": "season_{season_compact}/raw/understat_players_aggregated_2014_td.csv", "seasons": ["*"]},
    ...
  ]
}
```

- `pattern` is relative to `DATA_DIR` and uses the season placeholder
  (`{season_compact}` = `2627`, `{season_full}` = `2026/27`).
- Resolution happens in `src/db/build.py`; path conventions die in one place.
- The manifest replaces the implicit globbing in `build_database.py`.
- The private workspace supplies the same relative tree under its own
  `FANTAPREDICTOR_DATA_DIR`, which is why the manifest stays in the public core.

As shipped, `config/data_sources.json`'s entries carry `root` (`data_dir` or
`season_dir`) and a `seasons` directive of `["$target"]` (resolve only the
`--season` passed to the build), `["*"]` (resolve every `season_YYYY_YY`
directory found on disk -- how votes stay multi-season by default), or
`[null]` (a single season-independent path). This is a slightly richer shape
than the sketch above because several real sources are directories with a
variable number of files per season (votes, FBref manual exports), not one
file per manifest entry; see `docs/data_pipeline.md`'s "Declared sources"
section for the resolved contract.

### B2 Ingestor contract

Every ingestor implements a uniform signature:

```python
def load(conn, source: IngestSource) -> int:
    """Wrap one source snapshot; return rows loaded."""
    run_id, _ = start_run(conn, source.slug, checksum=source.checksum())
    ...
    finish_run(conn, run_id, "ok", rows, detail=json.dumps({...}))
```

- `IngestSource` = manifest entry resolved to an on-disk path + content checksum.
- Per-source checksum skip: if `ingestion_runs` already recorded `ok` for this
  checksum, the source is skipped — rebuilds are byte-idempotent, not just
  natural-key idempotent.
- Per-source transaction boundary: on error, roll back that source, record
  `status=error` with the checksum and traceback in `detail`, continue with the
  next source, and report a summary (current `build_database.py` fails hard on
  the first error).
- Existing ingestors are wrapped; no rewrite of the row-upsert logic.

As shipped, the wrapper is `src/db/build.py::IngestSource`/`load_one_source`,
and checksum/outcome bookkeeping is a new `source_checksums` table keyed by
the manifest entry's own slug (plus season, e.g. `votes:1516`) rather than
overloading `ingestion_runs` -- several manifest entries (one per season of
votes, for example) share the same `sources.slug` (`fantacalcio`), so the
skip-check needs a finer-grained key than `ingestion_runs`'s
`(source_id, started_at)` uniqueness gives it. Each existing ingestor's own
`start_run`/`finish_run` call is untouched.

### B3 Schema versioning on the DB

- `PRAGMA user_version` stores the **schema version** number.
- `schema.sql` is only ever applied for `user_version == 0` (fresh DB) plus an
  ordered, Python-side migration list. `src/db/database.py::_migrate_schema`
  becomes a list of migrations keyed by target version.
- `init_schema(conn)` refuses to open a database whose `user_version` is newer
  than the core version (schema from a future core); `--rebuild` wipes and
  recreates the schema from `schema.sql`.
- Version bump rule (unchanged): minor for additive schema changes, major for
  breaking ones, kept in sync across `src/db/__init__.py`, `pyproject.toml`,
  `PRAGMA user_version`, and the CHANGELOG.

As shipped: `schema.sql` is idempotent (`CREATE TABLE IF NOT EXISTS`
throughout) and applied on every `init_schema` call regardless of version, so
it always reflects the fully-migrated shape; `MIGRATIONS` in
`src/db/database.py` only needs to carry the additive `ALTER TABLE` steps
that predate version tracking (the `role` and `xg_chain`/`xg_buildup`
columns), all keyed to `CURRENT_SCHEMA_VERSION = 1`. Every pre-existing
database (including the 40MB private warehouse) has `user_version = 0` since
it was never stamped before now; opening it applies those migrations once and
stamps it to `1`.

### B4 Two first-class build modes

- `python scripts/build_database.py --db ... --season 2627`: incremental,
  idempotent-by-checksum-skip, validates `PRAGMA user_version` matches the core.
- `--rebuild`: drops and recreates the schema from `schema.sql`, then loads the
  full manifest. Used for reproducible from-scratch rebuilds; the current 40MB
  private warehouse is the acceptance data set (861 roster rows, 11,746 matches,
  124,760 ratings, 7,096 player-season rows, 587 prices after rebuild).

As shipped: `--rebuild` requires `--confirm-wipe` (decision #3, answered
"yes, require it"). It has been verified against synthetic fixtures in
`tests/test_manifest_build.py`; it has **not** been run against the real
40MB private warehouse as part of this change -- that is a deliberate,
separate, explicitly-confirmed action, not something to run silently as a
side effect of a doc-implementation pass.

### B5 Reuse — repository as the single read path

`src/db/repository.py` (extended) is the only way scripts and models read
warehouse data (ratings, players, prices, match context, player-season stats).
DataFrames for `MatchDataBuilder` and model training are assembled from
repository readers, never from Excel.

As shipped: this was already true before this change (`repository.py`
already covered every reader `MatchDataBuilder` and `evaluate_model.py`
needed); no changes were required here.

---

## 4. Rollout plan (as executed)

| Phase | Work | Depends on | Status |
|---|---|---|---|
| B1+B2 | manifest + `IngestSource` + checksum-skip + per-source error isolation + `config/data_sources.json` | — | Done |
| B3+B4 | `PRAGMA user_version`, migration list, `--rebuild` | B1 | Done |
| A1 | pipeline stages read from repository; Excel becomes artifact-only | B5 (overlaps B1) | Done (B5 was already satisfied) |
| A2 | historical coverage + expected-minutes features + hard baseline gate | A1 | Gate done; coverage/features deferred (data-sourcing decision) |
| A5 | sync script | — | Done |

---

## 5. Decisions needed (as answered)

1. **Manifest location & format**: `config/data_sources.json` (core) — **answered: yes**, as proposed.
2. **Checksum scope**: SHA-256 per snapshot file vs. directory tree. **Answered: per-file for file sources; for directory sources (votes, FBref manual), a SHA-256 over every contained file's relative path, size, and hash, since those manifest entries map to a variable-count directory rather than one file.**
3. **`--rebuild` safety**: require an explicit `--confirm-wipe` flag before
   dropping the schema. **Answered: yes, implemented exactly as proposed.**
4. **Historical-coverage target for A2**: pick seasons and sources to extend first
   (e.g. votes 2015/16→2024/25 + Understat matched minutes), to size the work.
   **Still open** — not answered by this change; needs a follow-up decision
   informed by data availability and licensing, not just code.
5. **Phase ordering**: execute the table above as written, or jump to A2 first if
   the auction timeline (winter window) is the constraint? **Answered: executed
   as written** — no near-term auction/winter-window pressure was in effect
   when this was implemented (2026-09-02, right after the 1 September deadline).
