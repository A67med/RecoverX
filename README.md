# RecoverX — One-Click Kali Edition

**Start here (Arabic):** [`START_ONE_CLICK_AR.md`](START_ONE_CLICK_AR.md)

This edition adds a Kali launcher (desktop + application-menu shortcut), automatic Python environment setup on first launch, a *Quick Recovery* workflow that creates/opens a case, analyzes and recovers in one action, optional safe read-only capture from an unmounted non-system block device (polkit authorization), a recovered-file download option (size-limited), and a one-click PDF export.

**Install (once):** Open `Install-RecoverX.desktop` in your Kali file manager and allow launching; if the desktop environment blocks it, run `bash INSTALL_ON_KALI.sh` once. Subsequent starts are by clicking **RecoverX**. The launcher binds Streamlit only to localhost, reuses a healthy existing server, and logs failures under `~/.cache/recoverx/launcher.log`.

**Safety:** Never run Streamlit as root, never modify a disk in order to recover from it. The optional device imaging flow reads only from a verified, currently unmounted non-system disk/partition and requires explicit consent. Outputs go to a separate working directory. Real-world recovery is not guaranteed.

---

# RecoverX

## Improved version — quick demo & safety updates

This copy includes a safe synthetic FAT16 **Demo Mode**, fail-closed evidence SHA-256 checks,
per-run timestamps and stage updates, a metadata-only **PDF case report**, and an optional
installer for the CART model bundled in `results/exp1/models`.

```bash
python3 scripts/install_bundled_model.py  # trusts the model included with this repository
streamlit run app.py
```

In the app, create a demo case under **Case Management → Safe demo**, then use
**Forensic Analysis → Intelligent Recovery (Fixed: combined) → Recovered Files → Evidence & Audit**.
Open **Show advanced research pages** in the sidebar for archived, read-only experiment results.
See `START_HERE_AR.md` and `RELEASE_NOTES.md` for changes, known limitations and full setup.
**The historical 51-pass claim below describes the original developer environment, not a new
full integration run of this modified release.**

Research-grade evaluation of **CART-based deleted-file recovery strategy selection** over
**The Sleuth Kit (TSK)** and **PhotoRec**. RecoverX inspects a raw disk image, extracts
pre-recovery features, chooses TSK only / PhotoRec only / both, runs the real tools,
verifies outputs against ground truth by SHA-256, and benchmarks the choice against fixed
strategies and a rule-based selector.

> **Headline finding (experiment `exp1`, 24 held-out images):** CART selection was **not
> faster** than any fixed strategy on 48–96 MiB images — its own analysis (~29 ms) cost more
> than it saved. Running both tools reached acceptable quality on 24/24 images. This is a
> valid negative result; see `reports/research/paper.md`.

## What works (verified in this environment)

| Component | Status | Evidence |
|---|---|---|
| TSK 4.12.1 adapter (`tsk_recover`, `fls`, `fsstat`, `mmls`) | ✅ real runs | integration tests, 1,224 benchmark runs |
| PhotoRec 7.1 adapter (unattended `/cmd` mode) | ✅ real runs | integration tests, benchmark runs |
| Case store, SHA-256 before/after every run, evidence manifest | ✅ | 0 source-hash changes in 1,224 runs |
| Ground-truth corpus generator (FAT16/FAT32/ext4 × 4 scenarios) | ✅ | 96 images, independent validator: 0 problems |
| CART (`sklearn.tree.DecisionTreeClassifier`) + rule baseline | ✅ | trained on train+val only |
| Benchmark (5 methods, randomised repeats, Wilcoxon + Holm) | ✅ | `workspace/experiments/exp1/` |
| Streamlit dashboard, 9 pages on persisted data | ✅ | AppTest renders every page; server health check |
| Test suite | ✅ **51 passed, 0 skipped** | `reports/test_results.txt` |
| Windows | ⚠️ **not tested** | see `docs/installation_and_user_guide.md` |

## Quick start (Ubuntu / Debian)

```bash
sudo apt-get install -y sleuthkit testdisk dosfstools e2fsprogs mtools
python3 -m pip install -r requirements.txt
python3 scripts/check_environment.py         # verify everything is found
python3 -m pytest -q                          # 51 tests, ~10 s
streamlit run app.py                          # open http://localhost:8501
```

Reproduce the experiment (dataset generation needs root for ext4 loop mounts):

```bash
sudo python3 scripts/create_test_dataset.py --out workspace/datasets/v1
python3 scripts/run_benchmarks.py --exp workspace/experiments/exp1 all    # resumable
python3 scripts/train_model.py --exp workspace/experiments/exp1 --install-only
python3 scripts/build_paper.py --exp workspace/experiments/exp1
```

## Repository map

```
app.py                      Streamlit entry point
src/recoverx/
  forensic/                 hashing, image validation, TSK pre-analysis, case store + manifest
  engines/                  common interface; sleuthkit_engine, photorec_engine
  ml/                       features (pre-recovery only), oracle labels, rule-v1 + CART
  recovery/                 orchestrator (5 methods), dedup, ground-truth matching, metrics
  datasets/generator.py     controlled corpus + independent validator
  benchmarking/             3-phase experiment runner, statistical analysis
  ui/dashboard.py           9 dashboard pages
config/objective.json       pre-registered label objective, grid, comparisons (frozen)
scripts/                    check_environment, create_test_dataset, run_benchmarks, train_model, build_paper
tests/                      unit, integration (real tools), security, dashboard
docs/                       feasibility, architecture, methodology, installation & user guide, project plan
reports/research/           paper_template.md -> paper.md (numbers filled from records)
```

## Integrity rules this code follows

- Tools run with argument lists (no shell), timeouts and process-group kill; outputs go to
  fresh, empty, case-specific directories; output paths can never equal or sit inside the evidence.
- Recovery is counted **only** by SHA-256 match to ground truth — never by filename.
- Missing tools → status `blocked` with the reason; nothing is simulated.
- The dashboard shows "Not yet measured" instead of placeholder charts.
- Recovered files are never opened, rendered, or executed.
- The manifest supports auditability; it does **not** by itself prove chain of custody or admissibility.

## Attribution

TSK © Brian Carrier and contributors; PhotoRec/TestDisk © Christophe Grenier (GPL). RecoverX
calls them as external programs and does not redistribute them.
