# Evaluation Record

**Run date:** 24 August 2026  
**Data:** private SQLite warehouse, schema `0.4.0`  
**Experiment:** 2024/25, train on matchdays `< 20`, evaluate on matchdays `>= 20`

## Reproduction

```bash
export FANTAPREDICTOR_DATA_DIR=/path/to/fantapredictor-workspace/data
python scripts/evaluate_model.py \
  --season 2024-25 \
  --cutoff-matchday 20 \
  --epochs 25 \
  --output /tmp/fantapredictor-evaluation.json
```

The evaluation is offline. It reads votes and features from SQLite and does not
make network calls.

## Results

| Metric | Residual SHASH | Expanding prior | Global median |
|---|---:|---:|---:|
| Test rows | 5,951 | 5,951 | 5,951 |
| Vote MAE | 1.460 | 0.444 | 0.424 |
| Fantavoto MAE | 2.052 | 0.888 | 0.794 |
| Fantavoto RMSE | 2.494 | 1.357 | 1.401 |
| q10 coverage | 0.977 | 0.936 | 0.952 |
| q50 coverage | 0.860 | 0.548 | 0.763 |
| q90 coverage | 0.989 | 0.912 | 0.919 |
| q10-q90 coverage | 0.967 | 0.847 | 0.871 |
| Mean interval width | 11.984 | 3.000 | 2.500 |

## Interpretation

The residual formulation is numerically stable and improves on the earlier
unanchored neural output, but it does not beat either baseline on point error.
Its intervals are also too wide and asymmetric relative to the observed
coverage targets. It is therefore not approved for auction use.

Next modelling work must use multiple chronological cutoffs and compare role,
minutes, and observed-appearance subsets separately. Candidate improvements
include expected-minutes modelling, role-specific residuals, fixture context,
and calibrated residual intervals. No neural model should replace the baseline
until it wins on held-out data without sacrificing calibration.
