# Player confidence model: pre-season baseline

## Purpose

Produce one explainable scorecard per roster player for auction and shortlist decisions. This is a **pre-season baseline**, not a claim to predict a specific matchday precisely.

The output deliberately separates:

- `projected_event_points_per90` — expected points from the scoring events covered by the open data;
- `data_confidence` (0–100) — how much recent, repeated evidence supports the estimate;
- `selection_score` (0–100) — a transparent blend of within-role potential and data confidence.

## Method

1. Use every matched Understat player-season row from the previous six seasons, exponentially down-weighting older seasons (1.5-year half-life).
2. Translate expected goals, expected assists, yellow cards, and red cards into the league’s supplied rule points.
3. Calculate a weighted per-90 rate. Use xG/xA rather than realised goals/assists to reduce finishing-conversion noise.
4. Apply empirical-Bayes shrinkage toward the position average; lower-minute samples receive more shrinkage.
5. Calculate data confidence from weighted minutes (60%), freshness (25%), and history depth (15%).

Name-only joins that point to multiple Understat IDs are labelled `manual_review_required` and receive a confidence penalty; they must be reconciled before auction use. Goalkeepers receive a data-evidence record but no potential/selection score until goalkeeper and clean-sheet events are ingested.

This approach is aligned with the hierarchical-Bayesian treatment of Italian fantasy-player ratings by Egidi and Gabry, which highlights the noise in individual football performance, and with player-ability models based on event rates. [Egidi & Gabry (2018)](https://arts.units.it/retrieve/e2913fdc-4db0-f688-e053-3705fe0a67e0/jqas-2017-0066.pdf), [Whitaker et al.](https://arxiv.org/abs/1710.00001)

## Run

```bash
cd fantacalcio_refactored
.venv/bin/python scripts/download_baseline_data.py --season 2627
.venv/bin/python scripts/build_player_confidence.py --season 2627 \
  --rules config/fantacalcio_rules.example.json
```

The result is `data/season_2026_27/outputs/player_confidence_baseline.csv`.

## Rules configuration

Copy `config/fantacalcio_rules.example.json`, set every scoring weight in your league, and pass the copied file via `--rules`. The current source supports goals, assists, yellow cards, and red cards. It explicitly does **not** support base votes, goalkeeper events, clean sheets, penalties, own goals, or defence modifiers yet; their omission is represented by `model_scope=event_points_only`.

## Next model increment

To produce calibrated matchday probabilities, add official fantasy votes/roles, fixture and opponent strength, expected minutes/probable line-ups, and goalkeeper/defensive event data. Evaluate chronologically using held-out matchdays and calibration metrics (Brier score/log loss for events; MAE and interval coverage for points). Team-level goal models such as Dixon–Coles and Bayesian hierarchical extensions can provide the opponent/fixture layer. [Dixon & Coles (1997)](https://www.research.lancs.ac.uk/portal/en/publications/modelling-association-football-scores-and-inefficiencies-in-the-football-betting-market%28d16276a2-d6e0-483b-a708-1d29663f1992%29.html), [Baio & Blangiardo (2010)](https://discovery.ucl.ac.uk/id/eprint/16040/)
