# Walk-Forward Evaluation Record

**Run date:** 1 September 2026

**Data:** private SQLite warehouse, schema `0.6.0`

**Experiment:** 2024/25 expanding walk-forward windows starting at matchdays
10, 20, and 30; 25 epochs per window

## Reproduction

```bash
export FANTAPREDICTOR_DATA_DIR=/path/to/fantapredictor-workspace/data
CUDA_VISIBLE_DEVICES=-1 python scripts/evaluate_model.py \
  --season 2024-25 \
  --cutoffs 10,20,30 \
  --epochs 25
```

The evaluation is offline. It reads votes and features from SQLite and does not
make network calls. Player-season statistics are limited to seasons before
2024/25. Team and opponent form is shifted by one fixture. The three test
windows are disjoint: matchdays 10-19, 20-29, and 30-38. Fixture context was
available for 11,887 of 12,697 season rows (93.6%).

## Aggregate Results

| Metric | Residual SHASH | Expanding prior | Global median |
|---|---:|---:|---:|
| Test rows | 9,865 | 9,865 | 9,865 |
| Vote MAE | 1.155 | 0.448 | **0.425** |
| Fantavoto MAE | 1.860 | 0.908 | **0.801** |
| Fantavoto RMSE | 2.429 | **1.387** | 1.413 |
| q10 coverage | 0.945 | 0.928 | 0.953 |
| q50 coverage | 0.821 | 0.547 | 0.759 |
| q90 coverage | 0.970 | 0.911 | 0.918 |
| q10-q90 coverage | 0.915 | 0.839 | 0.871 |
| Mean interval width | 8.842 | 3.031 | 2.500 |

## Window Stability

| Test window | Training rows | Test rows | SHASH fantavoto MAE |
|---|---:|---:|---:|
| Matchdays 10-19 | 2,832 | 3,541 | 2.650 |
| Matchdays 20-29 | 6,373 | 3,499 | 1.235 |
| Matchdays 30-38 | 9,872 | 2,825 | 1.645 |

The neural model remains unstable across training-window sizes. Aggregate
fantavoto MAE is 132% worse than the global-median baseline, and its mean 80%
interval is more than three times wider. It is therefore still not approved
for auction or lineup decisions.

Role labels are now restricted to the Fantacalcio contract (`P/D/C/A`). SHASH
fantavoto MAE is 1.269 for goalkeepers, 1.755 for defenders, 1.850 for
midfielders, and 2.273 for attackers. The detailed JSON report also records
club and historical-minute cohorts.

Historical Understat coverage remains sparse for players outside the current
roster-derived archive: 9,670 of the 9,865 test rows have no matched prior
Understat minutes. The next modelling gate is therefore broader time-stamped
historical player coverage, followed by expected-minutes and availability
features. No neural model should replace the global-median or expanding-prior
baseline until it wins on disjoint held-out windows without sacrificing
calibration.
