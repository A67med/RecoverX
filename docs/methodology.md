# Methodology

All choices below were fixed in `config/objective.json` **before** any benchmark run.

## Corpus
`src/recoverx/datasets/generator.py` — 3 filesystems (FAT16, FAT32, ext4) × 4 scenarios
(delete, overwrite, format, fragmented) × 8 seeds = 96 raw images of 48 or 96 MiB.
File types: PNG, JPEG, PDF (Pillow), TXT, ZIP; sizes 8 KB–1.5 MB; contents random per seed
and unique (checked). Observed — not intended — conditions are stored per target file:
physical extents before deletion, fragment count, and fraction overwritten by data written
after deletion. `validate_dataset()` independently re-hashes every image and reference file,
checks duplicate ground truth, and checks no seed appears in two splits.

**Splits (grouped by image):** seeds 0–4 train (60), 5 validation (12), 6–7 test (24).

## Methods compared
| Method | Analysis charged? | Decision |
|---|---|---|
| tsk | no | always TSK (`tsk_recover`, unallocated files) |
| photorec | no | always PhotoRec (`freespace`, all file families) |
| combined | no | TSK then PhotoRec, sequential, merged by SHA-256 |
| rule | yes | rule-v1 (see `ml/selector.py`) |
| cart | yes | trained CART; falls back to rule-v1 *visibly* if the model is missing |

## Timing boundary
`total_s` = initial source hash → … → final source hash. Includes analysis (mmls/fsstat/fls),
feature extraction, inference, engines, output inventory hashing, ground-truth verification,
deduplication. Fixed methods skip analysis; selectors cannot.

## Labels
Per image, from phase-1 fixed runs (3 repeats): eligible = strategies with recall ≥ best − 0.05;
label = fastest eligible by median time; ties → TSK < PhotoRec < Combined. Labels are
training targets only. Sensitivity reported for τ ∈ {0, 0.05, 0.10, 0.20}.

## Model
CART grid: depth 1–5 × min leaf 1/2/4; selected by validation balanced accuracy, ties → simpler;
refit on train+val. Test images were never used for training or selection.

## Metrics & statistics
Exact recall (SHA-256), pooled recall, false-candidate rate, duplicates, time components,
source-hash consistency, selector agreement with oracle labels. Per-image medians over 3
repeats; paired Wilcoxon signed-rank, rank-biserial r, Holm across the four time comparisons.
