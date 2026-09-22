# Open literature review for auction forecasting

**Reviewed:** 22 September 2026  
**Scope:** open-access work on individual soccer performance, uncertainty and
budget-constrained fantasy selection.

This is a method registry, not a claim that every cited model transfers to
Fantacalcio. A method is production-eligible only after chronological,
leakage-safe evaluation against simple baselines on this project's targets.

## Methods used in the current post-matchday-4 run

1. **Hierarchical shrinkage of noisy player marks.** Egidi and Gabry model
   Serie A fantasy ratings with players nested in position and team, explicitly
   treat missing ratings, and validate on held-out data. The current propensity
   model implements the cheaper empirical-Bayes analogue: low-observation
   player rates shrink toward role priors and appearance probability is
   modelled separately. It does not claim to reproduce their Stan posterior.
   [Open paper](https://arts.units.it/bitstream/11368/2929586/1/jqas-2017-0066.pdf)

2. **Event-rate ability rather than raw realised totals.** Whitaker et al. use
   a variational Bayesian Poisson model to infer player abilities for event
   types. This supports the project's use of shrunk xG/xA and bonus-event rates
   instead of treating four matchdays of goals as stable ability.
   [arXiv:1710.00001](https://arxiv.org/abs/1710.00001)

3. **Simulation followed by constrained optimization.** Mahoney and Paniak
   combine supervised fantasy-point projections with a mixed-integer linear
   program under roster and salary constraints. The new auction optimizer uses
   the same separation of concerns: the existing empirical-Bayes/Monte Carlo
   layer supplies forecasts, then MILP selects exactly 3P/8D/8C/6A under 500
   credits. Their NFL results are not evidence of Serie A accuracy; the paper
   itself reports only middling performance against real contest entries.
   [arXiv:2309.15253](https://arxiv.org/abs/2309.15253)

4. **Correlation and risk-aware fantasy selection.** Hunter, Vielma and Zaman
   formulate daily-fantasy selection with expected score, variance and lineup
   correlation. This supports retaining full simulations and risk summaries
   instead of optimizing point estimates alone. Their portfolio-of-lineups
   objective is not copied into the present single-roster auction problem.
   [arXiv:1604.01455](https://arxiv.org/abs/1604.01455)

## Relevant candidates not promoted to production

- **Bayesian player-adjusted xG.** Hierarchical logistic xG can stabilize
  player and position effects, but it requires shot-level context absent from
  the current Understat aggregate snapshot. It is a candidate once a licensed,
  reproducible event feed exists.
  [Bayes-xG, arXiv:2311.13707](https://arxiv.org/abs/2311.13707)
- **Position/player-adjusted ML xG.** Logistic regression and gradient boosting
  on shot features are relevant to finishing estimates, but aggregate xG must
  not be reverse-engineered into shot-level training rows.
  [arXiv:2301.13052](https://arxiv.org/abs/2301.13052)
- **Temporal CNN/LightGBM FPL forecasts.** Recent-match sequences, minutes,
  creativity and threat are useful candidate features. No architecture is
  imported because the paper targets English FPL scoring and the project's
  existing deep SHASH network loses badly to its chronological baselines.
  [arXiv:2405.02412](https://arxiv.org/abs/2405.02412)
- **Time-varying action value (I-VAEP/O-VAEP) and EPV.** These approaches can
  measure intention, execution, volatility, possession value and duel skill.
  They require event/action data not present in this warehouse, so they are
  documented rather than approximated from unrelated columns.
  [Valuing Players Over Time, arXiv:2209.03882](https://arxiv.org/abs/2209.03882),
  [EPV extensions, arXiv:2406.00814](https://arxiv.org/abs/2406.00814)
- **Random forest/XGBoost with uncertainty.** A 2025 study finds nonlinear
  tree ensembles effective for one-year player-quality/value forecasts and
  emphasizes time-series features and uncertainty. Its transfer-value target
  is different from Fantacalcio marks; a future candidate must be evaluated on
  player-match fantavoti, not adopted by analogy.
  [arXiv:2502.07528](https://arxiv.org/abs/2502.07528)

## Reproducibility and decision rule

The post-G4 auction output uses the already backtested transparent propensity
stack, not the failed neural SHASH model. Forecast history is cut strictly at
`matchday < 5`, so G1-G4 are inputs and no G5 observation leaks into the run.
The Monte Carlo seed, horizon, simulation count, source snapshot and auction
cost proxy are stored beside the output. The MILP objective discounts players
by appearance probability, forecast reliability and current availability, and
gives decreasing weights to deeper roster slots. Availability notices use a
documented 0.75 factor, or 0.35 when the source explicitly describes surgery,
a fracture or a long stop. These are conservative heuristics, not inferred
recovery dates. Auction costs are rounded FVM-derived planning references, not
learned clearing prices.

Promotion of a new paper-derived model requires:

1. expanding-window evaluation with all features computed strictly before the
   target matchday;
2. comparison with global-median and expanding-player-prior baselines;
3. MAE plus calibration/coverage reporting, not ranking anecdotes alone;
4. an ablation showing that the added data family improves held-out results;
5. no use of synthetic bootstrap roster rows as observed training targets.
