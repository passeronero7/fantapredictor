# Serie A 2026/27 roster scouting brief

**Snapshot:** 22 August 2026 (opening weekend). **Status:** provisional until the Italian summer window closes on 1 September 2026.

## Competition population

The 20 clubs in the first roster pass are: Atalanta, Bologna, Cagliari, Como, Fiorentina, Frosinone, Genoa, Inter, Juventus, Lazio, Lecce, Milan, Monza, Napoli, Parma, Roma, Sassuolo, Torino, Udinese, and Verona. This population is cross-checked against the current Serie A transfer tracker and the official league calendar.

## Roster policy

1. Build one record per player in `data/season_2026_27/fantacalcio/rosters_2627.csv` using the data contract in `AGENTS.md`. The automated baseline is a `watchlist` input, not a confirmed roster.
2. Include only players registered or officially announced by a Serie A club as `confirmed`.
3. Keep uncompleted negotiations under `watchlist`; do not expose them to model training, auction valuations, or lineup selection.
4. Reconcile the file with official club squads and the fantasy-platform role list once published. Roles are provider-specific, so do not infer them from a transfer-site position.
5. Refresh the source and timestamp immediately after 1 September and again after the winter window.

## Confirmed-transfer watch items

These are examples to seed the first reconciliation pass, not a complete squad list:

| Player | Club | Role to verify | Evidence |
| --- | --- | --- | --- |
| Curtis Jones | Inter | Midfielder | Officially reported completed on 21 August |
| Alieu Fadera | Cagliari | Forward | Como announcement reported on 21 August |
| Josip Šutalo | Lazio | Defender | Club announcement reported on 22 August |
| Benoît Badiashile | Napoli | Defender | Listed as confirmed on 22 August |
| Elif Elmas | Atalanta | Midfielder | Listed as confirmed on 22 August |
| Niccolò Fortini | Torino | Midfielder | Listed as confirmed on 21 August |
| Diego Moreira | Milan | Midfielder | Listed as confirmed on 19 August |
| Omar Fayed | Frosinone | Defender | Listed as confirmed on 19 August |

## Sources

- [Official Serie A 2026/27 calendar](https://www.legaseriea.it/serie-a/news/calendario-della-serie-a-enilive-2026-27)
- [Lega Serie A’s 7 August club-news roundup](https://www.legaseriea.it/serie-a/news/serie-a-news-7-agosto)
- [Football Italia’s 22 August confirmed-deals tracker](https://football-italia.net/live-done-deal-tracker-latest-serie-a-transfer/)
- [Serie A confirmed-transfer tracker, updated 22 August](https://www.soccernews.com/soccer-transfers/italian-serie-a-transfers/)

The third-party trackers are useful for discovery; club announcements and the final fantasy-platform list take precedence when they conflict.
