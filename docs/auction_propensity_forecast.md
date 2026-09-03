# Auction Propensity Forecast: Simulated Time-Series Study

**Date:** 3 September 2026
**Scope:** propensity to hold a *median good mark* (base vote >= 6.0) over a
forecast horizon, conditioned on player history and club statistical attitude.
**Module:** `src/models/propensity.py` — CLI:
`scripts/simulate_auction_propensity.py` (`forecast` / `backtest` modes).

## Method

1. **Player propensity** (empirical-Bayes): per player, P(vote >= 6.0) shrunk
   toward the role prior with a 3-observation pseudo-count, and an appearance
   rate shrunk the same way against club games in the window. Bonus events
   (fantavoto - vote) are bootstrapped separately.
2. **Club attitude**: attack/defense z-indices per club-season from shots and
   goals for/against (`match_team_stats`, all historical seasons; the latest
   fully observed season is used as the current attitude).
3. **Style multiplier**: bonus draws are accepted with probability
   exp(0.15 z), role-directional — A/C feed on own attack and weak opponent
   defense; P/D feed on own defense and suffer opponent attack — clipped to
   [0.5, 2.0].
4. **Monte Carlo**: for each simulated matchday the 20 clubs are paired
   randomly (the official future calendar is not ingested — documented
   assumption), each player appears Bernoulli(p_plays), votes are
   bootstrapped from his own distribution (role pool below 3 observations),
   and the horizon statistic is P(median vote across the horizon >= 6.0)
   plus per-match P(vote >= 6), P(fantavoto >= 6.5), and expected fantavoto.
5. **Coach playing style**: the `coach_club_seasons` schema is ready but the
   curated table is empty, so coach-attitude conditioning is a documented
   hook (`coach_style_adjustments`) — team-style proxies stand in. Fabricating
   coach attributes would violate the project's evidence rules.

## Forecast snapshot (2026/27, MD3 horizon of 8 matchdays, 500 simulations)

Top of the median-good-mark propensity table is dominated by first-choice
goalkeepers (De Gea, Caprile, Di Gregorio, Carnesecchi, Svilar) plus Modric
and McTominay — players with high appearance rates and mark distributions
centred above 6.0. The value-per-credit ranking (expected good marks per
matchday divided by price) surfaces 1-credit squad players *only* when their
appearance rate justifies it: the p_plays factor prevents the classic
"1-credit backup keeper" artifact. Notably, Malen's 9.56 expected fantavoto
from two explosive matchdays is discounted to mid-table by his 0.48 appearance
probability — the model deliberately penalises small-sample explosions.

## Backtest (2025/26, cutoffs 10/20/30, 10-matchday windows)

Walk-forward calibration of P(vote >= 6.0):

| Cutoff | Players | Brier | Bin predicted -> realized |
|---|---|---|---|
| 10 | 453 | 0.070 | 0.439->0.428, 0.567->0.502, 0.654->0.542, 0.782->0.687 |
| 20 | 441 | 0.067 | 0.430->0.419, 0.566->0.514, 0.647->0.591, 0.779->0.691 |
| 30 | 455 | 0.074 | 0.416->0.396, 0.561->0.535, 0.645->0.575, 0.782->0.697 |

**Findings:**
- The ranking signal is real: every quartile is monotone in realized rate
  across all three cutoffs.
- The estimator is **systematically overconfident** by +0.05 to +0.11 in the
  upper bins. Established regulars (survivor bias of a long observed history)
  regress in the next window more than the shrinkage accounts for. A practical
  correction: subtract ~0.05 from p_good_mark or shrink with a 6-observation
  pseudo-count before ranking baskets; both are one-line changes left
  deliberate until more windows are evaluated.

## Coach and archetype conditioning (added 3 September)

Web-sourced coach profiles (football-italia.net probable-modules article,
19 August 2026) populate the curated `coach_club_seasons`/`coaches` tables for
all 20 clubs with `preferred_module` and `style_tags` (schema v2 migration:
`coaches.preferred_module`, `coaches.style_tags`). Two new conditioning layers:

1. **Coach/module deltas**: transparent additive deltas per role — back-three
   modules lift D (+0.02, wing-back potential), two-AM modules lift C (+0.02),
   pragmatic/defensive-solidity tags lift P (+0.02) and penalise A (-0.01),
   possession tags lift D/C (+0.01). Applied before simulation, clipped to
   [0, 1].
2. **Similar-player archetypes**: every historical player-season carries a
   per-90 technique signature (xG, xA, shots, key passes, xGChain/xGBuildup)
   and its realised share of 6.0+ marks. Each player is blended with the mean
   propensity of his 20 nearest same-role neighbours (own observations get
   weight n/(n+6), clamped to [0.35, 0.85]); unobserved players collapse
   almost entirely to their archetype.

With both layers active (300 simulations, MD3 horizon of 8): Caprile, Di
Gregorio, De Gea and Modric reach P(median >= 6.0) = 1.00; Modric's Milan
possession/3-4-2-1 profile lifts him above his raw history; Akanji enters the
top 15 as the Inter back-three benefit materialises.

## Known limitations (frank list)

1. **Random opponent pairing**: the official calendar is not ingested, so
   fixture difficulty is averaged rather than scheduled. Real fixtures would
   sharpen the horizon medians.
3. **Overconfidence bias** documented above — treat absolute propensities as
   ranks, not calibrated probabilities, until recalibrated.
4. New signings with zero Serie A observations enter at the role prior with a
   conservative 0.35 appearance prior — they are visible in the basket but
   intentionally not ranked high.
5. Five priced players with legacy identity spellings (e.g. `MONTIPO'`) are
   excluded from the forecast pending roster reconciliation.

## Reproduce

```bash
export FANTAPREDICTOR_DATA_DIR=/path/to/fantapredictor-workspace/data
python scripts/simulate_auction_propensity.py --mode forecast \
  --season 2627 --from-matchday 3 --matchdays 8 --simulations 1000
python scripts/simulate_auction_propensity.py --mode backtest \
  --season 2025-26 --cutoffs 10,20,30 --window 10
```
