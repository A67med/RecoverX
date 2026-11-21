# RecoverX v0.4.0

**Recover deleted files from USB flash drives and raw disk images — with read-only imaging,
SHA-256 evidence integrity, The Sleuth Kit, PhotoRec and an interpretable CART strategy selector.**

RecoverX is a local Windows / Linux application (Python 3.12 + Streamlit). Version 0.4 adds
**direct USB acquisition on Windows** — no FTK Imager or other imaging tool is needed — and a
redesigned single-page **Quick Recovery** interface.

> **Hardware status:** the USB discovery layer was run read-only against this machine's real disks,
> and the imaging algorithm is tested with file-backed and fault-injecting sources. Imaging a physical
> USB flash drive end-to-end **has not yet been verified on real USB hardware**. v0.4.0 is therefore
> published as a **pre-release**. Please follow [the disposable-USB test procedure](docs/USB_RECOVERY_TESTING.md)
> before relying on USB acquisition.

## Quick Recovery in five steps

| Step | What happens |
|---|---|
| **1 · Select source** | *USB drive*: RecoverX lists connected disks with name, drive letters, filesystem, capacity, serial and physical disk number. Only removable USB/SD disks that are not system, boot, page-file or RecoverX disks can be selected. *Disk image file*: a raw `.img/.dd/.raw/.bin/.001`, or the image of a previous case. |
| **2 · Recovery method** | Smart Recovery · TSK only · PhotoRec only · TSK + PhotoRec · Automatic (CART only) · Automatic (rule-v1 only). |
| **3 · Output folder** | Must be on a **different physical disk** from the USB source; free space, write permission and disk identity are checked. |
| **4 · Start** | USB: a confirmation dialog shows the exact disk identity, then Windows asks for administrator permission (UAC) **only for the imaging worker**. Live progress shows bytes copied, throughput, unreadable sectors, then each real recovery stage. Cancel at any time. |
| **5 · Results** | Recovered files with original names (when metadata survives), type, size, SHA-256, structural validation, duplicate merging, optional known-hash comparison, safe thumbnail preview, download, PDF + JSON reports and the full audit trail. |

Logs, model predictions, engine commands, partition analysis, the acquisition record and the
audit trail are in expandable sections. Expert tools (case management, research laboratory,
diagnostics) stay available behind the *Advanced workspace* switch at the bottom of the page.

## Direct USB acquisition (Windows)

* Discovery uses documented Win32 IOCTLs on **zero-access** handles (disk number, size, sector size,
  bus type, vendor/product/serial) and `IOCTL_VOLUME_GET_VOLUME_DISK_EXTENTS` to map every drive
  letter to its physical disk(s) — this also works for dynamic/spanned volumes. The Windows Storage
  CIM classes add friendly names, `IsSystem`/`IsBoot` flags and partition offsets.
* The source is opened as `\\.\PhysicalDriveN` with **`GENERIC_READ` only**. RecoverX never formats,
  initialises, locks, dismounts or writes to the source; the code cannot request write access.
* Immediately before imaging, the device identity (number, size, serial, bus, vendor, product,
  sector size) is re-checked by the elevated worker; any change blocks acquisition.
* Data is streamed in bounded 1 MiB, sector-aligned reads into a **new** `.img` created with
  exclusive-create on another physical disk. SHA-256 is computed while reading
  (**source-stream hash**), the image is re-read from the destination (**image hash**) and they must
  match. An optional second full read of the USB drive (**source re-read hash**) detects a changing source.
* Unreadable sectors are retried sector-by-sector, zero-filled and listed; such an image is
  *completed with errors* and recovery is **not** started automatically. Cancellation, disconnection
  and failures leave a `*.img.partial` file that can never be registered as evidence.
* Partition tables (MBR, extended, GPT, "superfloppy" without a table) are recorded with byte and
  TSK sector offsets; TSK recovers every partition at its offset.
* After a verified acquisition, a case is created (its SHA-256 must equal the acquisition hash)
  and recovery starts automatically.

**Important limitation:** opening a disk read-only does **not** stop Windows, Explorer, antivirus or
other programs from writing to its mounted volumes. Close programs using the drive, do not browse it
during imaging, and use a hardware write blocker or the media's write-protect switch when write
protection must be guaranteed.

## Install on Windows 10/11 (64-bit)

Full non-technical guide: **[docs/WINDOWS_INSTALL.md](docs/WINDOWS_INSTALL.md)**.

1. Install **Python 3.12 (64-bit)** — `py install 3.12` or the python.org Windows installer.
2. Optional, for PhotoRec: install WSL 2 with Ubuntu and `testdisk` (setup offers to install
   `testdisk` into an existing distribution only after you type **Y**; it never installs WSL itself).
3. Double-click **`SETUP_WINDOWS.cmd`**. It finds Python 3.12, downloads the official Sleuth Kit 4.15.0
   ZIP (SHA-256 verified) and checks that `tsk_recover.exe` really runs, (re)builds the private `.venv`
   with tested package versions, activates the bundled CART model, checks PhotoRec in WSL and creates
   a **RecoverX** desktop shortcut. It never elevates and never touches disks.
4. Double-click the **RecoverX** desktop icon (or `START_RECOVERX_WINDOWS.cmd`). RecoverX opens in its
   own app window (Microsoft Edge/Chrome app mode, or your default browser) on `127.0.0.1` only.

Data and audit records are stored in `%LOCALAPPDATA%\RecoverX`; recovered files, reports and USB
images go to the output folder you choose.

## Linux / WSL / Kali

```bash
sudo apt-get update
sudo apt-get install -y python3-venv sleuthkit testdisk dosfstools e2fsprogs mtools
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m streamlit run app.py
```

On Linux the *USB drive* source images an **unmounted, non-system** device through polkit (`pkexec dd`)
and then recovers from that image. Kali users can run `bash INSTALL_ON_KALI.sh` for a menu launcher.

## Recovery methods

| Method | Engines executed | Selection |
|---|---|---|
| Smart Recovery | CART's recommended strategy; if a single engine fails or finds nothing, the other engine runs | CART model (rule-v1 fallback, logged) |
| TSK only | TSK only | fixed |
| PhotoRec only | PhotoRec only | fixed |
| TSK + PhotoRec | TSK then PhotoRec | fixed |
| Automatic (CART only) | both engines (preservation policy); CART recommendation logged | trained CART model (must be installed) |
| Automatic (rule-v1 only) | both engines (preservation policy); rule-v1 recommendation logged | frozen rule-v1 |

TSK restores deleted files from filesystem metadata and keeps their names and folders (FAT replaces
the first character of a deleted name, e.g. `_oliday.jpg`). PhotoRec carves file signatures from
unallocated space when metadata is gone; names are not preserved. Every recommendation, fallback,
safety override and engine run is written to the case event log and reports.

## Results, validation and reports

* **Success is reported only** when the run completed, the evidence hash is unchanged before and after,
  and at least one recovered file was copied to the output folder with a matching SHA-256.
  "No files found", partial, blocked, cancelled and failed runs are reported as such.
* Structural validation (JPEG markers, PNG IEND, PDF `%%EOF`, ZIP/DOCX/XLSX/PPTX central directory
  and CRCs) marks files *valid / invalid / not checked*. This is a plausibility check; **exactness is
  proven only by matching a known original SHA-256**, which you can paste in step 4.
* Exports: `recovered/` (one copy per distinct SHA-256; duplicates listed), `RecoverX-report.pdf`,
  `manifest.json`, `inventory.csv`, `export.json`. Recovered files are never opened or executed;
  previews are decoded-and-re-encoded thumbnails.

## Verified in this release

* Windows 11, Python 3.12.10: `SETUP_WINDOWS.cmd` (non-interactive) installed and executed Sleuth Kit 4.15.0,
  found PhotoRec 7.1 in WSL, activated the CART model and created the shortcut.
* Native Windows end-to-end smoke test (`scripts/smoke_e2e.py`): a FAT16 image with a **deleted JPG and PDF**
  was recovered by **all six methods** with exact SHA-256 matches; the image hash was unchanged.
* The same recovery driven through the UI in a browser (TSK + PhotoRec): 2 files recovered, structurally
  valid, copies hash-verified.
* Automated tests: Windows 137 passed / 35 skipped (tool-dependent tests are marked *BLOCKED* on Windows);
  Ubuntu 24.04 (WSL) with real TSK 4.12 / PhotoRec 7.1 — 168 passed, 4 skipped (Windows-only and optional
  PyMuPDF tests). See
  [CHANGELOG.md](CHANGELOG.md).
* **Not verified:** imaging a physical USB flash drive (no USB hardware was available to the test run).

## Measured ML results and research limits (unchanged from v0.3.0)

Re-evaluation used only existing synthetic feature/label records: **60 training, 12 validation, 24 test images**.
The validation-selected tree (depth 1, minimum leaf size 4) achieved **20/24 label agreement (83.3%)**,
**56.3% balanced accuracy** and **53.9% macro F1**. Majority-class agreement was 75%; rule-v1 was 70.8%.
These are **strategy-label metrics on synthetic images**, not recovered-file success rates or real-media
accuracy. See [the verification record](docs/modernization_verification.md).

## Verify

```bash
.venv/bin/python -m pytest -q            # Windows: .venv\Scripts\python -m pytest -q
.venv/bin/python -m ruff check src scripts tests
python scripts/smoke_e2e.py --workdir <empty folder>   # real-engine end-to-end smoke test
```

## Safety and operational limits

Use image copies and write blockers when enforceable write protection is required. Hashes detect changes
but cannot prevent them. The event log supports auditability; it is not a signed legal chain of custody.
The application is a trusted **single-user local workspace** bound to `127.0.0.1`; do not expose its port.
Keep evidence, recovered files and reports out of Git.

See [Windows install](docs/WINDOWS_INSTALL.md), [USB test procedure](docs/USB_RECOVERY_TESTING.md),
[architecture](docs/architecture.md), [methodology](docs/methodology.md),
[installation and troubleshooting](docs/installation_and_user_guide.md) and [CHANGELOG](CHANGELOG.md).
