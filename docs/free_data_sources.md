# Free data sources for Fantacalcio 2026/27

**Assessed:** 23 August 2026. “Free” does not mean unrestricted reuse: retain source attribution, obey each site’s terms, and rate-limit all requests.

## Recommended source stack

| Need | Primary source | Access result | Use in this project |
| --- | --- | --- | --- |
| Fixtures, results, standings, official player/team rankings | [Lega Serie A statistics](https://www.legaseriea.it/serie-a/statistiche/index) | HTTP 200 | Authoritative reconciliation source. Capture published tables or match reports; no documented public bulk API was identified. |
| Player, team, match, and shot-level xG data | [Understat](https://understat.com/league/Serie_A/2026) via [understatAPI](https://collinb9.github.io/understatAPI/) or `soccerdata` | HTTP 200 | Preferred automated analytical source. Covers Serie A from 2014/15; use the 2026 season identifier for 2026/27. |
| Historical and in-season match results, basic match stats, and odds | [Football-Data.co.uk Italy downloads](https://www.football-data.co.uk/italym.php) | Index available; direct `2627/I1.csv` returned HTTP 300 on 23 Aug | Good free historical baseline. Retry after the publisher creates the 2026/27 file; normal pattern is `mmz4281/{season}/I1.csv`. |
| Fixtures, tables, clubs, and top scorers | [football-data.org](https://www.football-data.org/documentation/quickstart) | HTTP 403 without an API token | Use only after registering for its free token/plan; it is a useful structured fixture fallback, not a complete Fantacalcio player-stat feed. |
| Fantasy prices, roles, votes, and probable line-ups | [Fantacalcio.it official matchday archive](https://www.fantacalcio.it/voti-fantacalcio-serie-a) | HTTP 200 | Programmatic retrieval supported via public matchday tables (`scripts/download_historical_votes.py`) across 11 seasons (2015/16 through 2025/26). Provides official votes, fantavoti, and detailed bonus/malus stats. |
| Squad and transfer confirmation | Official club announcements + Lega Serie A | Public web pages | Use for roster truth. Do not populate confirmed roster records from rumours or undocumented APIs. |
| Current club/player index | [Virgilio Sport Serie A player list](https://sport.virgilio.it/calcio/giocatori/) | HTTP 200 | Provisional 20-club roster snapshot, refreshed on every run. It does not define fantasy roles. |
| Deep historical player seasons | [Understat aggregated archive](https://github.com/vibedatascience/understat_players_aggregated) | 7 MB public CSV | Download and retain all matched player-season rows across the six covered leagues, with Understat player IDs. |

## Sources not selected for automation

- **FBref:** the 2026/27 page is valid, but the project’s automated request received HTTP 403 on 23 August. Keep it as a browser-export/manual fallback until access is explicitly reliable.
- **Sofascore, FotMob, Transfermarkt:** useful for human research but their commonly circulated endpoints are undocumented. Do not make them a production dependency without permission and stable terms.
- **Commercial APIs:** can improve coverage but are outside the free-first scope.

## Download checks performed

| URL | Result | Interpretation |
| --- | --- | --- |
| `https://fbref.com/en/comps/11/2026-27/stats/Serie-A-Stats` | HTTP 403 through `cloudscraper` | Endpoint recognised but blocked to the current automation route. |
| `https://understat.com/league/Serie_A/2026` | HTTP 200 | Reachable candidate for programmatic analytical data. |
| `https://www.legaseriea.it/serie-a/statistiche/index` | HTTP 200 | Reachable official reconciliation source. |
| `https://www.football-data.co.uk/mmz4281/2627/I1.csv` | HTTP 300 | Current-season CSV is not yet usable at that expected location. |
| `https://api.football-data.org/v4/competitions/SA/matches?season=2026` | HTTP 403 | Requires registration/token. |

## Data-model implications

Use official/Fantacalcio data for eligibility, roles, and votes; use Understat/Football-Data for model features and backtesting. Keep the source name, URL, retrieved timestamp, and licence/terms note with every raw file. This avoids training on a mixture of untraceable fantasy and event data.

## Bootstrap result: 23 August 2026

`scripts/download_baseline_data.py --season 2627` completed successfully and produced:

- 20 clubs and 626 provisional roster entries from Virgilio Sport;
- 2,056 matched player-season rows from the Understat archive;
- 419 roster players with at least one open-data historical row;
- 207 roster players without a match, principally academy/newer players and players whose history falls outside Understat’s six-league coverage;
- historical seasons from 2014/15 through the available 2025/26 data.

The generated `reports/baseline_download_report.json` is the source of truth for the exact retrieval timestamp and current coverage. Matching is name-based and must be reconciled with provider IDs before use in modelling.
