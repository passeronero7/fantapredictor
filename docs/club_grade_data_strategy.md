# Club-grade Serie A data strategy

This project should aim for the *method* used by professional analysis teams:
multiple complementary sources, unambiguous identities, time-aware features,
and rigorous evaluation. It must not obtain data by bypassing authentication,
rate limits, paywalls, robots controls, or contractual restrictions. Private
use does not remove those obligations.

## Data layers

| Layer | Data | Acquisition | Use |
| --- | --- | --- | --- |
| Official truth | Lega Serie A transfer registrations, fixtures, results | Public official pages/feed, stored with retrieval time | Roster eligibility, club assignment, fixture truth |
| Fantasy truth | Fantacalcio roles, prices, votes, bonus/malus | Official files/pages where permitted, kept private | Targets, auction constraints, scoring rules |
| Open event layer | Understat xG, xA, shots, key passes, xGChain, xGBuildup | One season snapshot at a time, rate-limited | Shot quality, creation, involvement, team style |
| Rich player skills | Passing, shooting, possession, defensive actions, playing time, goalkeeper actions | Browser-exported FBref tables or a properly licensed provider | Scouting profiles and pre-match features only when time-stamped |
| Premium event/video layer | Event coordinates, pressure, tracking, physical load, medical/readiness data | Licensed supplier and club-controlled systems only | Tactical and physical models; never infer from inaccessible data |

## Highest-value additions

1. Obtain a lawful event-data licence if the budget permits. Opta, Stats
   Perform, Wyscout, StatsBomb, SkillCorner, and Second Spectrum cover different
   portions of event, tracking, and physical data. Select by written licence,
   historical coverage, update latency, and identity quality—not by the size of
   an unauthorised dump.
2. For the open stack, export all supported FBref tables at a fixed pre-match
   cutoff: standard, shooting, passing, pass types, shot creation, defence,
   possession, playing time, misc, keeper, and advanced keeper.
3. Maintain a player identity crosswalk with provider IDs, date of birth where
   licensed, and an explicit human-review state. Do not resolve ambiguous names
   automatically.
4. Capture snapshots before each deadline. A final-season aggregate is useful
   for retrospective scouting but invalid as a feature for earlier matchdays.

## Core player profile

For every player-season, retain raw provider values and compute only
well-defined derived features:

- Availability: minutes, starts, substitute usage, rolling 90s, recent minutes
  trend, and fixture congestion.
- Finishing: non-penalty xG/90, shots/90, shots on target, xG per shot,
  penalties, and realised-goal minus xG residual with shrinkage.
- Creation: xA/90, key passes, shot-creating actions, goal-creating actions,
  progressive passes/carries, final-third and penalty-area entries.
- Possession and progression: touches by zone, carries, progressive receptions,
  dispossessions/miscontrols, and pass completion by length.
- Defence: tackles by zone, interceptions, blocks, clearances, aerial duels,
  errors, and ball recoveries.
- Involvement: xGChain/90 and xGBuildup/90, separated from the final shooter or
  assister so the model recognises build-up contributors.
- Goalkeepers: post-shot xG versus goals allowed, saves, cross claims/stops,
  sweeper actions, launch/distribution quality, and penalties.

Normalise rate features by minutes and apply empirical-Bayes shrinkage. A
two-shot player must not outrank a 2,000-minute player merely because of a
high observed percentage.

## Modelling contract

- Train Fantacalcio predictions only on observed Fantacalcio votes/fantavoti.
- Store `source_url`, source file, provider ID, metric definition, retrieval
  time, and the latest event time included in every snapshot.
- Join a feature only when its `as_of` time precedes the kickoff being
  predicted. Use walk-forward evaluation by matchday and compare every model to
  global-median and expanding-prior baselines.
- Publish coverage and calibration by role, minutes band, club, and player
  cohort. Missing data must be a feature/flag, never a silently fabricated zero.

## Operating cadence

1. Daily during the transfer window: refresh the official transfer feed; keep
   unclassified roles as watchlist.
2. After each matchday: capture official votes/prices where permitted, the
   single Understat season snapshot, and any lawful manual skill exports.
3. Before the fantasy deadline: validate roster/roles, freeze an `as_of`
   snapshot, generate predictions, then log the model and data manifests.
4. Monthly: audit source licences, identifier collisions, duplicate players,
   stale data, model calibration, and feature leakage.
