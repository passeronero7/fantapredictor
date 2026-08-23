# Season 2026/27 data workspace

Generated and manually sourced data for the active season belongs in this directory:

- `fbref_data/` — automatically collected FBref player and team tables.
- `fantacalcio/` — provider downloads (quotazioni, votes, calendar, role list, and confirmed roster CSV).
- `mid_outputs/` — derived datasets.
- `outputs/` — predictions and auction exports.

Raw data is intentionally ignored by Git. The scraper creates required child directories automatically. Do not place rumours in the confirmed roster dataset.

Run `python scripts/download_baseline_data.py --season 2627` to create a
provisional roster snapshot plus all available historical Understat rows for
those players. See `docs/free_data_sources.md` for coverage and limitations.
