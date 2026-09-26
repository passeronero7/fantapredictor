# Auction forecast audit — 26 September 2026

The auction forecast is an empirical player resampling model, not a joint
simulation of scorelines, substitutions and fantasy lineups. Ten thousand
runs reduce Monte Carlo noise, but do not establish predictive accuracy.
The neural SHASH model remains unapproved for auction use.

## Corrections

- Preserve signed `fantavoto - vote`, including goals conceded, cards and
  missed penalties. The previous two clipping operations erased negative
  outcomes in 22,119 of 125,712 observed pairs. Mean inflation before any
  other adjustments was about 1.33 fantasy points for goalkeepers.
- Mix paired player observations with the same-role distribution using six
  prior appearances. This replaces the discontinuity between a role fallback
  below three appearances and full trust in the player's tiny sample above it.
  The fixed bootstrap bank contains 2,048 pairs per player and is deterministic.
- Estimate appearances from current-season use with three prior matches
  weighted by last season's appearance rate (role fallback without that
  season). Historical career rates remain available as `p_plays_career`.
  A current starter no longer inherits years spent as a backup indefinitely.
  Never-observed signings retain the documented 0.35 prior.
- The production forecast requires complete warehouse pairings for every
  horizon round. Conflicting/incomplete fixtures raise an error. The lower
  level simulator retains random pairings only for explicitly schedule-free
  research calls. Matchup multipliers are precomputed without changing their
  existing mathematical rule.
- Votes and team results are filtered before the target round for all direct
  forecast channels. Current official Classic roles override past vote roles.
- Injury recovery discounts use each club's own calendar dates, including
  early/late fixtures. Return-window dates remain approximations, not medical
  clearance. Keep official date corrections sourced in the private workspace.
- The live planner tolerates a valid minimum-cost or fully purchased roster
  when tightening the budget is infeasible. Confirmed legal purchases may use
  the operational reserve; state validation still enforces the actual budget.

## Historical checks

All comparisons use historical observations only, with G1-G5 known and G6-G13
held back. These are component checks, not an end-to-end winning-odds backtest.
Parameter comparisons use the same five seasons and therefore remain model
selection evidence; a new untouched season is still needed for confirmation.

For fantasy means, 1,877 player-seasons from 2021/22 through 2025/26 have at
least three target appearances. Six prior appearances change MAE 0.509 →
0.475 and RMSE 0.704 → 0.644. Among the 442 cases with fewer than 15 historical
appearances, MAE changes 0.582 → 0.450 and RMSE 0.813 → 0.589. Weights 3/6/12/24
were compared; six gives the lowest thin-history MAE. Target appearance
selection means this check validates the conditional fantasy mean only.

For availability, all 2,223 player-seasons observed in the first five rounds
are scored on eight future binary appearance events, including zero future
appearances. Brier score changes 0.2260 (career estimate) → 0.1962 (current
usage plus three prior games). Six and twelve prior games score 0.1992 and
0.2077. This check does not evaluate completely unobserved newcomers or
probable-XI/injury overlays.

Rechecking coach multipliers after filtering out unrated rows gives aggregate
Poisson deviance 3309.504 → 3306.691 (goals) and 2749.913 → 2748.946 (assists)
at strength 0.25 versus zero. Strength 1 is worse. Keep strength 0.25 and
shrinkage 120; this marginal improvement is not evidence of a large causal
coaching effect.

## Remaining limits

- The same probable XI discounts all eight forecast rounds; it is not a
  long-term lineup prediction. Current usage is based on only five games.
- Style acceptance can reduce positive bonuses but cannot increase them
  above the empirical distribution. Own-club context is partly counted twice.
  Home advantage is not estimated by this forecast.
- Goals and saves across players are not constrained to a coherent match
  score. The roster MILP uses role depth weights, not legal weekly formation
  selection with correlated bench substitutions. Its objective is a ranking
  utility, not expected points per matchday or championship win probability.
- FVM-based costs are planning references without calibration to this league's
  clearing prices. Maximum bids are conditional on all other reference costs.
- The historical fantasy distribution includes older seasons without recency
  weighting. Small-sample shrinkage does not model age or tactical role changes.
- Historical replay must also freeze prices, roster, injury notes, XIs and
  season aggregate features as of its cutoff; filtering votes/results alone
  does not turn `run_forecast` into a fully leakage-free end-to-end backtest.
- Betting markets are an independently sourced cross-check. Complete 1X2 and
  over/under markets can be normalized within bookmaker; partial top-scorer
  lists cannot be converted into fair probabilities or expected goals.
