# Serie A 2026/27 roster scouting brief

**Snapshot:** 24 August 2026. **Status:** watchlist-first and incomplete until the Italian summer window closes on 1 September 2026.

## Competition population

The 20 clubs in the first roster pass are: Atalanta, Bologna, Cagliari, Como, Fiorentina, Frosinone, Genoa, Inter, Juventus, Lazio, Lecce, Milan, Monza, Napoli, Parma, Roma, Sassuolo, Torino, Udinese, and Verona. This population is cross-checked against the current Serie A transfer tracker and the official league calendar.

## Roster policy

1. Build one record per player in `data/season_2026_27/fantacalcio/rosters_2627.csv` using the data contract in `AGENTS.md`. The automated baseline is a `watchlist` input, not a confirmed roster.
2. Include only players registered or officially announced by a Serie A club as `confirmed`.
3. Keep uncompleted negotiations under `watchlist`; do not expose them to model training, auction valuations, or lineup selection.
4. Reconcile the file with official club squads and the fantasy-platform role list once published. Roles are provider-specific, so do not infer them from a transfer-site position.
5. Refresh the source and timestamp immediately after 1 September and again after the winter window.

## Manual reconciliation workflow

Use the public Virgilio listing only to seed candidates. Reconcile each row in
the private workspace roster file using this evidence order:

1. Official announcement or first-team squad page from the destination club.
2. The official Serie A club registry and competition calendar for the league
   population.
3. The official Fantacalcio quotation page for `role`, current price, and the
   fantasy-platform player identity.
4. Reputable transfer trackers for discovery and cross-checking only. They do
   not replace a club announcement for a `confirmed` assertion.

The working file is
`fantapredictor-workspace/data/season_2026_27/rosters/virgilio_rosters_2026_27.csv`.
It must contain `player`, `club`, `role`, `status`, `source_url`, and
`checked_at`. Keep unresolved rows as `watchlist`, departed/ineligible rows as
`excluded`, and promote a row only when its club and fantasy role are evidenced.
The public template is `config/roster_reconciliation.example.csv`.

Useful primary sources:

- [Lega Serie A 2026/27 calendar](https://www.legaseriea.it/serie-a/news/calendario-della-serie-a-enilive-2026-27)
- [Fantacalcio quotations and roles](https://www.fantacalcio.it/quotazioni-fantacalcio)
- Official club websites and verified club announcements for each individual assertion

The [Football Italia tracker](https://football-italia.net/live-done-deal-tracker-latest-serie-a-transfer/)
and [SoccerNews confirmed-transfer page](https://www.soccernews.com/soccer-transfers/italian-serie-a-transfers/)
are useful discovery sources, but rumours, medicals, agreements, and transfer
probabilities must remain outside the confirmed dataset.

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

## Latest Reconciliation Checkpoint

Checked on 24 August 2026. Four rows have both club evidence and a fantasy
role; all other baseline rows remain `watchlist`:

| Player | Club | Role | Primary evidence |
|---|---|---|---|
| Alieu Fadera | Cagliari | C | [Como 1907 announcement](https://x.com/Como_1907/status/2090887713461342366) |
| Curtis Jones | Inter | C | [Inter announcement](https://www.inter.it/en/news/curtis-jones-new-inter-player) |
| Diego Moreira | Milan | C | [AC Milan announcement](https://www.acmilan.com/it/news/articoli/media/2026-08-19/comunicato-ufficiale-diego-moreira) |
| Niccolò Fortini | Torino | D | [Torino announcement](https://x.com/TorinoFC_1906/status/2090733807263477882) |

The private roster currently contains 4 `confirmed` and 622 `watchlist` rows.
It cannot yet form a legal `3-4-3` lineup. Re-run the release validator after
each manual update.
