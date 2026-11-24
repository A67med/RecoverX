# Installation and operation

Use Ubuntu 24.04 or Ubuntu 24.04 under WSL2. The verified local runtime is Python 3.12.3.
Run all commands in the repository root, not in a PowerShell virtual environment.

```bash
sudo apt-get update
sudo apt-get install -y python3-venv sleuthkit testdisk dosfstools e2fsprogs mtools
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python scripts/check_environment.py
.venv/bin/python -m streamlit run app.py
```

## Windows 11 / Windows 10 (64-bit)

Follow the step-by-step guide in [WINDOWS_INSTALL.md](WINDOWS_INSTALL.md):
install Python 3.12 (64-bit), double-click `scripts\windows\setup_streamlit.cmd`, then start RecoverX from the desktop
icon. TSK runs natively; PhotoRec runs as a non-root user in the default WSL distribution (optional).

Quick Recovery (v0.4) can image a **USB flash drive directly**: select it under *USB drive*, choose an
output folder on another physical disk, confirm the disk identity and approve the Windows permission
prompt. Only the imaging worker is elevated. The workspace is `%LOCALAPPDATA%\RecoverX`; recovered
files, reports and the disk image go to the chosen output folder. See
[USB_RECOVERY_TESTING.md](USB_RECOVERY_TESTING.md) for the hardware test procedure and limitations.

## Kali desktop launcher

Install the forensic prerequisites first.

```bash
sudo apt update
sudo apt install python3-venv sleuthkit testdisk dosfstools e2fsprogs mtools
bash scripts/linux/install_desktop_entry.sh
```

On graphical Kali, the launcher registers an application-menu entry and opens the loopback-only app.
Optional physical-device image capture requires polkit and an unmounted authorized source.

Open http://localhost:8501 in your Windows or Linux browser. Configuration binds to localhost;
the app has no user authentication and should not be exposed to untrusted networks.
Set `RECOVERX_HOME` to select private storage. Engine timeouts can be set in the recovery panel or
with `RECOVERX_TSK_TIMEOUT` / `RECOVERX_PHOTOREC_TIMEOUT`. `.env` is not automatically read.

## Everyday workflow

Quick Recovery (main page): 1 select a USB drive or image · 2 choose one of the six methods · 3 choose an
output folder · 4 start and monitor · 5 review, validate and export results. The steps below describe the
expert pages in the *Advanced workspace*.

- Register a raw image copy in Case Management. Confirm authorization; its initial SHA-256 is stored.
- Inspect metadata in Forensic Analysis. Deleted names are filesystem claims, not recovered files.
- In Intelligent Recovery, automatic modes explain a recommendation but run both tools by default.
  Fixed/manual single-engine choices are explicit and may miss recoverable files.
- Start once. Navigation/reruns do not restart the worker. Live status shows real stages and completed-engine counts.
- Cancel safely when needed. Tools stop; partial output remains. Hash/inventory stages finish before cancellation takes effect.
- Inspect Recovered Files and its exact-match/unknown states. Export metadata CSV, not recovered executable content.
- Export JSON manifest and Markdown report from Evidence & Audit. Keep these sensitive reports private.

## Model evaluation and installation without images

```bash
.venv/bin/python scripts/evaluate_model.py
.venv/bin/python scripts/install_evaluated_model.py
```

These commands use the existing synthetic records, train a JSON CART model and save it only under ignored
`workspace/`. The old archived `model.joblib` is retained as a historical artifact but never deserialized.
For a new dataset, use `scripts/run_benchmarks.py --exp ... --dataset ...` and `scripts/train_model.py`.
Never mix new runs with the archived old timing records: the production policy and timing boundary changed.

## Troubleshooting

| Message | Action |
|---|---|
| Missing executables | Install `sleuthkit` and `testdisk`; dataset tests also need `dosfstools` and `mtools`. |
| Permission denied / blocked output | Select private writable storage; do not run the application as root to bypass it. |
| Source hash changed | Stop and investigate the image copy; create a new case only after verifying provenance. |
| Legacy pickle/joblib rejected | Re-evaluate recorded features and install the resulting JSON model. |
| Incomplete filesystem analysis | Review command errors; the selector cannot justify omitting an engine. |
| Unfinished checkpoint | Preserve partial output; inspect logs. Starting a fresh run requires acquiring the case lock. |
| No byte-progress percentage | The tool adapters expose stages and finished file counts, not reliable byte progress. |
| Unsupported container | Convert/acquire into a single raw image through a separate verified process. |
| Existing synthetic image | Use a new dataset folder; the generator refuses to overwrite previous images. |

## Validation

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check src scripts tests
.venv/bin/python -m pip check
.venv/bin/python -m pip_audit
```

Missing tools cause explicit skips. CI installs them and uses synthetic regular files only, without root mounts.
The full ext4 corpus generator is a separate privileged workflow. No real evidence is included in the repository.
