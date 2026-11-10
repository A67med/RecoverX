# Installation, User Guide, Troubleshooting

## 1. Install (tested: Ubuntu 24.04, Python 3.13)

```bash
sudo apt-get update
sudo apt-get install -y sleuthkit testdisk dosfstools e2fsprogs mtools
cd RecoverX
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 scripts/check_environment.py
```
Every line should say `OK`. Exit code 0 = ready.

### Windows (not tested — recommended route: WSL2)
1. In PowerShell (admin): `wsl --install -d Ubuntu-24.04`, reboot, open "Ubuntu".
2. Inside Ubuntu, follow section 1 exactly.
3. Run `streamlit run app.py` and open the printed `http://localhost:8501` link in your Windows browser.
Native Windows builds of TSK and PhotoRec exist but RecoverX was not tested with them.

## 2. Run the app
```bash
streamlit run app.py
```
Data lives in `workspace/` (change with `RECOVERX_HOME=/path`).

| Page | What to do |
|---|---|
| Case Management | paste an **authorized** raw image path, tick the authorization box, create case (SHA-256 computed) |
| Forensic Analysis | run read-only mmls/fsstat/fls; see deleted entries and features |
| Intelligent Recovery | choose CART / rule / fixed / manual override; optional ground-truth JSON; start |
| Recovered Files | filter by engine, integrity state, name/hash; export CSV (contents never opened) |
| Model Training | features, labels, grid, tree, importances; retrain; install model |
| Benchmark Laboratory | launch/resume experiments in background; results, charts, paired tests |
| Evidence & Audit | event log, per-run hashes, re-hash now, export manifest |
| Settings & Diagnostics | tool versions, packages, storage, disk space |

A demo case is ready: test-split image `ext4-delete-s6` with ground truth
`workspace/datasets/v1/gt_ext4-delete-s6.json`.

## 3. Tests
```bash
python3 -m pytest -q          # unit + integration (real tools) + security + dashboard
```
If TSK/PhotoRec/mtools are missing, tool tests are **skipped with reason "BLOCKED"** — they are
not counted as passing.

## 4. Troubleshooting
| Symptom | Cause / fix |
|---|---|
| `engine photorec: MISSING` | `sudo apt-get install testdisk` |
| PhotoRec run `failed`, "log missing completion marker" | check `runs/<id>/photorec/photorec.log`; image unreadable or killed by timeout (`RECOVERX_PHOTOREC_TIMEOUT`) |
| `blocked: output directory not empty` | by design — each run needs a fresh directory |
| Dataset generator: "image not mounted; refusing to write" | needs root and an ext4-capable kernel; run with `sudo` or `--fs fat16 fat32` |
| CART run says "CART unavailable … rule-v1 used" | no model installed: `python3 scripts/train_model.py --exp workspace/experiments/exp1 --install-only` |
| Low disk warning | each benchmark run keeps its outputs; delete old `workspace/experiments/*/cases` manually |

## 5. Demonstration checklist (≈10 min)
1. `python3 scripts/check_environment.py` → all OK.
2. `python3 -m pytest -q` → 51 passed.
3. Dashboard → Settings & Diagnostics (tool versions).
4. Case Management → create case from `workspace/datasets/v1/images/fat16-delete-s6.img`.
5. Forensic Analysis → run; point out deleted entries with sizes.
6. Intelligent Recovery → CART; show decision path; then manual override to `combined`.
7. Recovered Files → filter `verified_exact_match`; show duplicate groups across engines.
8. Evidence & Audit → hashes before/after; export manifest; read the disclaimer aloud.
9. Benchmark Laboratory → explain the negative result with Table 1 and the trade-off chart.
