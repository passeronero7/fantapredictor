# Changelog

All notable project changes are recorded here.

## [Unreleased] - 2026-08-22

### Added

- Root project operating guide (`AGENTS.md`), authoritative README, and 2026/27 roster scouting brief.
- Regression tests for FBref table parsing and season-aware scraper output.
- A root `.gitignore` that excludes virtual environments, generated data, logs, and local IDE state.
- A 2026/27 season data workspace and a tested free-source assessment.
- A reproducible baseline downloader for a 2026/27 club/player snapshot and matched historical player seasons.

### Changed

- Set the active configuration to Serie A 2026/27 (`2627` / `2026_27`).
- Make stage-one scraper reads and writes season-specific data.
- Move active paths to `data/season_2026_27/` and generate the season-specific FBref URL.
- Harden FBref parsing so missing cells do not create malformed DataFrames; map the project `team` field to FBref's `squad` column.

### Fixed

- Declare the `cloudscraper` runtime dependency used by the FBref scraper.
- Correct the stale root documentation, which claimed missing modules and a complete production pipeline.

### Known limitations

- Stages 2–6 import modules that are not present in this handoff, so they cannot run yet.
- The committed `venvfanta/` virtual environment has an invalid relocated interpreter path.
- FBref currently returns HTTP 403 to the automated scraper; see `docs/free_data_sources.md` for the tested alternatives.

## [0.1.0] - 2026-08-23

### Added

- `download_baseline_data.py`, which downloads a dated 2026/27 20-club player snapshot and joins it to all available open-league Understat player-season history.
- Bootstrap report and coverage documentation: 626 roster entries, 419 players with open-data history, and 2,056 matched historical rows.

### Fixed

- Made the baseline downloader work when called directly from `scripts/`, as documented.

### Data notes

- Generated roster/history files are intentionally ignored by Git because they are time-sensitive third-party data. The downloader and its report schema are versioned instead.
