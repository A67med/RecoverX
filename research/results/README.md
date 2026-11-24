# Saved experimental records (real runs, 2026-10-30)

`exp1/` — copied from `workspace/experiments/exp1/` after the benchmark finished.
- runs.jsonl (864 phase-1 runs), test_runs.jsonl (360 held-out runs), features.jsonl, labels.json,
  training_report.json, models/ (trained CART), analysis.json, per_image_results.csv.
`dataset_v1/manifest.json` — ground-truth manifest for the 96 synthetic images (images themselves are
not included: regenerate with `scripts/create_test_dataset.py`; regenerated images are not
byte-identical, file contents are).
Recovered file outputs and per-run case folders are not included (size).
