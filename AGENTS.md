# Fantacalcio agent guide

## Mission

Build a reproducible, evidence-led Fantacalcio research and prediction project for Serie A 2026/27. The legacy implementation lives in `fantacalcio_refactored/`; improve it in place until a deliberate migration is agreed.

## Working rules

- Treat `fantacalcio_refactored/README.md` as legacy documentation. Keep the root `README.md` and `CHANGELOG.md` authoritative.
- Do not describe unimplemented pipeline stages as working. The current source implements only FBref collection and utility modules.
- Use only confirmed transfers for the active roster dataset. Keep rumours in a separate watchlist and never merge them into eligible players.
- Record a source URL and `checked_at` date for every roster or transfer assertion. The transfer market remains open until 1 September 2026, so refresh before every auction or model run.
- Keep raw, source-derived data out of Git unless it is small and redistributable. Store generated exports in `fantacalcio_refactored/data/` (ignored).
- Add or update tests for behaviour changes. Do not make live network calls in tests.
- For every material change, update `CHANGELOG.md` and the relevant user-facing documentation, then stage and commit the coherent change set. Generated data and local environments remain untracked.

## Commands

```bash
cd fantacalcio_refactored
python -m unittest discover -s tests -v
python scripts/run_pipeline.py --stage scrape --season 2627 --force
```

The committed `venvfanta/` directory is a relocated environment and is not reliable; create a fresh virtual environment before installing dependencies.

## Data contract

Roster records must contain: `player`, `club`, `role`, `status`, `source_url`, and `checked_at`. Valid `status` values are `confirmed`, `watchlist`, and `excluded`. A player can enter model or auction outputs only with `confirmed` status.
