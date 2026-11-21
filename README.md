# RecoverX v0.3.0

**Auditable deleted-file recovery with The Sleuth Kit, PhotoRec and interpretable CART recommendations.**

RecoverX is a local Python / Streamlit application for examining **raw disk-image copies**.
It preserves the original project’s research pipeline while adding conservative automatic recovery,
background execution, explicit integrity checks and a dark forensic workspace.

## Run on Ubuntu 24.04 / WSL2

```bash
sudo apt-get update
sudo apt-get install -y python3-venv sleuthkit testdisk dosfstools e2fsprogs mtools
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python scripts/check_environment.py
.venv/bin/python -m streamlit run app.py
```

Open **http://localhost:8501**. The server binds to localhost and disables usage telemetry.
Python 3.11+ is declared; this modernization was verified locally on **Python 3.12.3, Ubuntu 24.04 / WSL**.
CI is configured for Python 3.11–3.13; see the actual Actions run for remote results.


Data stays in `workspace/` by default. Set `RECOVERX_HOME=/your/private/workspace` before starting.
`.env.example` documents variables; the app does not implicitly load `.env`.

## Windows 11 / Windows 10 with WSL 2

1. Install 64-bit Python 3.11, 3.12 or 3.13.
2. For PhotoRec, install Ubuntu under WSL 2 and complete its first launch as a regular Linux user.
   Make it the default WSL distribution if needed. Inside Ubuntu, run
   `sudo apt update && sudo apt install testdisk`. TSK-only recovery can run without WSL.
3. Run `SETUP_WINDOWS.cmd` from a writable copy of the source. It installs Sleuth Kit and Python dependencies.
4. Run `START_RECOVERX_WINDOWS.cmd`. Quick Recovery opens by default. Use **Show advanced pages**
   in the sidebar to reach case analysis, audit, model evaluation and benchmarking.

The app runs as a regular Windows user. PhotoRec runs as a non-root Linux user through WSL.
Use image and output paths on local drives visible to WSL and keep the same default distribution
during a run. Cancelling a WSL PhotoRec scan waits for it to exit or reach its configured timeout.
The app does not capture physical disks on Windows. The default workspace is
`%LOCALAPPDATA%\RecoverX`. Setup moves an unusable virtual environment aside as
`.venv.broken-…` so a fresh one can be created without touching the workspace.

## Kali desktop launcher

Install the forensic prerequisites first.

```bash
sudo apt update
sudo apt install python3-venv sleuthkit testdisk dosfstools e2fsprogs mtools
bash INSTALL_ON_KALI.sh
```

On graphical Kali, the launcher registers an application-menu entry and opens the loopback-only app.
Optional physical-device image capture requires polkit and an unmounted authorized source.

## Workflow

1. **Case Management** — register an authorized image copy and its initial SHA-256.
2. **Forensic Analysis** — inspect partitions, filesystem and deleted metadata entries.
3. **Intelligent Recovery** — choose automatic or explicit manual/fixed recovery; start, monitor stages, cancel safely.
4. **Recovered Files** — filter inventory by engine, hash, name and validation state; export safe CSV.
5. **Evidence & Audit** — inspect operation history, compare hashes and export JSON plus Markdown and PDF reports.

Automatic CART/rule modes **recommend a strategy but execute both engines sequentially by default**.
A classifier prediction does not prove that the other engine cannot recover more files.
Explicit fixed/manual single-engine runs remain available. Research code can request
`conservative=False`; incomplete analysis, model failure and out-of-domain CART inputs still trigger both engines.
Quick Recovery also offers Smart mode. It starts with the recommendation and records any second-engine attempt after a failure or zero outputs. Every override is recorded. No confidence score is presented as a recovery probability.

## Implemented and verified

- TSK metadata recovery of unallocated files; PhotoRec carving; SHA-256 deduplication retaining every output and its provenance.
- Non-overlapping source/output paths, non-empty output refusal, permission and subprocess error records.
- Source hash checked **before tools start** and again afterward; changed evidence blocks the run or invalidates its status.
- Sequential multi-partition TSK recovery; whole-image PhotoRec carving when a single filesystem scope is unavailable.
- Case locks, atomic JSON records, stage checkpoints, bounded command-output capture and process-group cancellation.
- CART saved as validated **JSON**, with a digest and schema checks. Legacy pickle/joblib files are never loaded.
- Dark UI, background worker independent of Streamlit reruns, real stage/file-count updates, report and inventory export.
- Real-engine synthetic FAT16 and partitioned FAT16 tests, security regressions and the Streamlit UI.

Supported input containers are single raw `.img`, `.dd`, `.raw`, `.bin` and `.001` files.
The extension is an input policy, **not proof of a valid filesystem**. Split images, E01, virtual disks,
encrypted containers and physical devices need a separate acquisition/conversion workflow.
FAT16 is exercised by the current real-engine tests. FAT32/ext4 results in the archive are historical;
NTFS/exFAT and damaged/fragmented real-world media have not been validated by this update.

## Measured ML results and research limits

Re-evaluation used only existing synthetic feature/label records: **60 training, 12 validation, 24 test images**.
The validation-selected tree (depth 1, minimum leaf size 4) achieved **20/24 label agreement (83.3%)**,
**56.3% balanced accuracy** and **53.9% macro F1**. Majority-class agreement was 75%; rule-v1 was 70.8%.
The one `combined` test sample was misclassified. These are **strategy-label metrics**, not recovered-file success rates.
Grouped cross-validation on training seeds, all per-class metrics and limitations are documented in
[the modernization verification record](docs/modernization_verification.md).

```bash
# No disk images or old pickle model needed; report/model stay under ignored workspace/.
.venv/bin/python scripts/evaluate_model.py
# Install the evaluated JSON model locally:
.venv/bin/python scripts/install_evaluated_model.py
```

`results/exp1/`, `results/dataset_v1/` and `reports/research/` are preserved **historical synthetic research artifacts**.
The original experiment found no speed advantage from CART on small images. Its timings are not results of this
new pipeline. No full 96-image recovery benchmark was rerun during modernization.

## Verify

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check src scripts tests
.venv/bin/python -m pip check
.venv/bin/python -m pip_audit
```

Tests create synthetic images under temporary directories, with no real disk writes or mounts.
Missing external tools cause explicit skips, not fabricated passes. Full dataset generation can require
privileged ext4 loop mounts; it is separate from the ordinary tests and refuses existing image paths.

## Safety and operational limits

Use image copies and OS/hardware write blockers when enforceable write protection is required.
Hashes detect changes but cannot stop another process modifying evidence. The event log supports auditability;
it is not a signed or tamper-proof legal chain of custody. Ground truth is examiner supplied.
Filename/signature hints alone never establish completeness; without ground truth, output remains unverified.

Cancellation kills running tools and keeps partial output. Hashing and inventory finish their current stage;
hard process termination leaves a checkpoint but cannot guarantee a final digest. Restart with a fresh run;
partial engine directories are never overwritten or silently resumed. File inventories/case JSON still scale
with output count: very large investigations may need a future database/indexed inventory.

The application is a trusted **single-user local workspace**, not an authenticated multi-tenant service.
Do not expose its port to untrusted networks. Keep evidence, recovered files, credentials, logs and new model
binaries out of Git. `.gitignore` covers common artifacts but is not a substitute for reviewing staged paths.

See [architecture](docs/architecture.md), [methodology](docs/methodology.md),
[installation and troubleshooting](docs/installation_and_user_guide.md), and
[verification](docs/modernization_verification.md).
