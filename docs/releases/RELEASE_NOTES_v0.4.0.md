# RecoverX v0.4.0 (pre-release)

**Direct USB recovery for Windows, a redesigned Quick Recovery interface, and verified exports.**

## Highlights

- **Recover deleted files straight from a USB flash drive** — no FTK Imager needed. RecoverX lists
  connected USB drives (name, drive letters, filesystem, capacity, serial, physical disk), protects
  system and internal disks, confirms the exact disk identity, and images it **read-only** to a different
  disk with streamed SHA-256, destination verification, unreadable-sector reporting, cancellation and
  disconnection handling. Recovery starts automatically after a verified image.
- **Administrator rights only when needed:** RecoverX runs as a normal user; Windows asks for permission
  only when you confirm imaging, and only the imaging worker is elevated.
- **New five-step Quick Recovery UI:** Select source → Recovery method → Output folder → Start (live,
  event-driven progress with cancel) → Results (filter, safe preview, download, verified copies,
  PDF/JSON reports, audit trail).
- **All six methods preserved:** Smart Recovery, TSK only, PhotoRec only, TSK + PhotoRec,
  Automatic (CART only), Automatic (rule-v1 only).
- **Results you can trust:** success is reported only for real, hash-verified output; structural
  validation for JPG/PNG/GIF/PDF/Office files; optional comparison with known original hashes.
- **Easier Windows setup:** Python 3.12 detection (incl. the Python install manager), verified Sleuth Kit
  download that is test-executed, self-repairing virtual environment, tested package versions, optional
  consent-based PhotoRec setup in WSL, new desktop icon and app-window launcher.

## Verification performed

- Windows 11 + Python 3.12.10: setup ran end-to-end; Sleuth Kit 4.15.0 executed; PhotoRec 7.1 via WSL found.
- Native Windows smoke test: deleted JPG + PDF on a FAT16 image recovered with exact SHA-256 matches by
  all six methods; image unchanged.
- UI-driven recovery in a browser (TSK + PhotoRec): 2 files recovered, valid, copies verified.
- Automated tests on Windows and on Ubuntu 24.04 (WSL) with the real TSK and PhotoRec binaries.
- Read-only discovery against this machine's real disks: both internal disks were correctly protected.

## Not yet verified — why this is a pre-release

Imaging a **physical USB flash drive** was not tested on real hardware during this release. The
imaging algorithm is covered by tests with file-backed and fault-injecting sources, and the Win32
discovery code ran against real disks, but the elevated `\\.\PhysicalDriveN` read path still needs a
hardware run. Please follow [docs/USB_RECOVERY_TESTING.md](docs/USB_RECOVERY_TESTING.md) with a
disposable drive and report results.

Read-only access cannot stop Windows or other programs from writing to a mounted USB volume during
imaging; use a write blocker or the drive's write-protect switch when that must be guaranteed.

## Upgrade

Extract the new source, double-click `SETUP_WINDOWS.cmd` (it reuses or repairs `.venv`), then start
RecoverX from the desktop icon. Existing cases in `%LOCALAPPDATA%\RecoverX` remain readable.

See [CHANGELOG.md](CHANGELOG.md) for the full list of changes.
