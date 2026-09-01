# Serie A 2026/27 roster scouting brief

**Snapshot:** 1 September 2026 at 21:32 CEST. **Status:** reconciled from the official transfer feed after the Italian summer window closed at 20:00 CEST.

## Competition population

The 20 clubs in the first roster pass are: Atalanta, Bologna, Cagliari, Como, Fiorentina, Frosinone, Genoa, Inter, Juventus, Lazio, Lecce, Milan, Monza, Napoli, Parma, Roma, Sassuolo, Torino, Udinese, and Venezia. This population is cross-checked against the current Serie A transfer tracker and the official league calendar. Verona was relegated to Serie B after 2025/26 and is not part of the 2026/27 Serie A population.

## Roster policy

1. Build one record per player in `data/season_2026_27/fantacalcio/rosters_2627.csv` using the data contract in `AGENTS.md`. The automated baseline is a `watchlist` input, not a confirmed roster.
2. Include only players registered or officially announced by a Serie A club as `confirmed`.
3. Keep uncompleted negotiations under `watchlist`; do not expose them to model training, auction valuations, or lineup selection.
4. Reconcile the file with official club squads and the fantasy-platform role list once published. Roles are provider-specific, so do not infer them from a transfer-site position.
5. Refresh the source and timestamp immediately after 1 September at 20:00 CEST and again after the winter window.

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

Checked against the Lega Serie A Calciomercato feed at 21:32 CEST on 1
September. The private roster contains 288 `confirmed`, 558 `watchlist`, and
15 `excluded` rows. The confirmed pool contains 31 goalkeepers, 88 defenders,
83 midfielders, and 86 forwards and passes the legal `3-4-3` release gate.
The post-closure feed added 12 destination memberships relative to the 15:01
snapshot and applied 15 prior-club exclusions. Three official feed entries lack
a mapped P/D/C/A role and remain watchlist.

## Market-closure decision

The 21:32 CEST checkpoint is the post-closure summer snapshot. Retain its
per-row source URL and UTC `checked_at` value, and refresh for any official
correction or the winter window. The active club population includes Venezia
and excludes relegated Verona.
