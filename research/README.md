# Research artefacts

RecoverX evaluates whether an interpretable CART decision tree, given only
pre-recovery file-system features, can choose per disk image between
metadata-based recovery (The Sleuth Kit), signature carving (PhotoRec) and running
both. Everything needed to recompute the reported numbers is kept here; disk images
and recovered files are not (they are regenerated from the manifests' seeds).

| Path | Content |
|---|---|
| `datasets/dataset_v1/manifest.json` | Ground truth of the original 96-image synthetic corpus (FAT16/FAT32/ext4 × delete/overwrite/format/fragmented × seeds 0–7). |
| `results/exp1/` | Original benchmark (2026-10-30, TSK 4.12.1, PhotoRec 7.1): phase-1 runs, labels, training report, held-out runs, analysis. `models/cart-20261030-193546/` is the shipped model (`meta.json`, scikit-learn `model.joblib`, and `portable-tree.json` used by the Windows desktop). |
| `experiments/paper_2026_11/` | Harness for the 2026-11 study: `run_all.sh` (E1 replication, E2 192 fresh-seed images, E3 256/1024 MiB scaling), `rx_bench.py` (isolated per-run CPU/memory measurement), `rx_train.py`, `rx_stats.py` (bootstrap CIs, grouped CV, ablations), `rx_figures.py`. |
| `results/paper_2026_11/` | Records of that study: 6,408 recovery runs, dataset manifests, `stats.json`, `environment.json`, and `source_sha256.txt` (exact source files used). Large JSONL files are gzip-compressed; run `gunzip -k` before re-analysis. Scratch paths were removed from the records. |
| `archive/` | Earlier research write-up and template from v0.4.0 (kept for history). |

## Reproduce

Linux with root (ext4 images are built through a loop mount), `sleuthkit`, `testdisk`,
`mtools`, `dosfstools`, `e2fsprogs`, and the Python dependencies of RecoverX plus `psutil`
and `matplotlib`:

```bash
export CODE=$PWD WORK=/root/rxr OUT=$PWD/research/results/paper_2026_11_rerun
sudo -E bash research/experiments/paper_2026_11/run_all.sh
```

The harness requests the study protocol explicitly from the orchestrator: only rule/CART
runs pay for metadata analysis, and the selected strategy is executed as chosen
(`conservative=False`). The application itself defaults to running both engines for
automatic modes.

## Reproducibility notes

* Recovery outcomes are deterministic per image: re-running E1 phase 1 on the consolidated
  code gave identical recall and output counts in all 288 image × strategy cells.
* Oracle labels are not fully stable: most images have several strategies within the quality
  tolerance, so labels are decided by millisecond-scale timing differences (89/96 labels agreed
  in the re-run). Model selection on 12 validation images is correspondingly unstable.
* Corpus bytes depend on library versions (Pillow PNG/PDF encoders; PDF creation time), so
  regenerated corpora match the design and seeds but not every file byte.
* Timings are machine-specific (WSL2 on a laptop, no cache dropping); compare methods within a run.
