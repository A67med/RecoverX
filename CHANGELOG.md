# Changelog

All notable changes to RecoverX. Dates are UTC.

## [Unreleased] — repository consolidation

No new version number is assigned; the Python package remains 0.4.0 and the Windows desktop
identifies itself as Recovery Studio 1.0 RC1 (as built before consolidation).

### Added
- **Native Windows desktop (Recovery Studio 1.0 RC1)** merged from the separately developed RC1
  bundle: WPF front end (`native/`), partition-aware scan worker (`desktop/`), unelevated reader with a
  narrow elevated acquisition helper, MBR/EBR/GPT/4Kn layout reader, gallery/list review and verified
  export, installer (`packaging/`), validation fixture and checks (`validation/`).
- `scripts/windows/provision_desktop.ps1`: downloads CPython 3.12.7 embeddable, pytsk3 20260715,
  The Sleuth Kit 4.15.0 (Windows), TestDisk/PhotoRec 7.2 (Windows) and the corresponding source
  archives from their official publishers, verifies pinned SHA-256 values, and builds `RecoverX.exe`.
- Portable JSON export of the archived CART model (`research/results/exp1/models/.../portable-tree.json`)
  used by the desktop worker without scikit-learn or unpickling.
- `research/experiments/paper_2026_11/` and `research/results/paper_2026_11/`: scripts and run records of
  the replication (E1), fresh-seed evaluation (E2) and scaling (E3) experiments (6,408 recovery runs).
- `THIRD_PARTY_NOTICES.md`; licence texts in `licenses/`.
- Tests for the merged desktop components, including end-to-end recovery of the three deleted fixture
  files by the desktop worker with real TSK and PhotoRec.

### Changed
- Repository layout: research artefacts under `research/`, launchers under `scripts/windows` and
  `scripts/linux`, requirement files under `requirements/`, release notes and Arabic guides under `docs/`.
- TSK adapter passes `-i raw -b <logical sector size>` (4Kn media) and reports `tsk_recover`
  write/recovery errors printed on stderr as a failed engine run instead of silently completing.
- PhotoRec adapter uses a native Windows binary from `tools/photorec` when present (started as invoker,
  because the official build requests elevation it does not need) and falls back to WSL otherwise.
- Rule-v1 lives in `recoverx.ml.policy` and is shared by the selector and the desktop worker.

### Fixed
- Desktop worker rejected its request when the WPF host wrote a UTF-8 BOM on stdin (UTF-8 console code
  page), which made every desktop scan fail on such systems.

### Removed from version control
- No compiled executables, embedded runtimes, third-party binaries, installers, historical archives or
  experiment outputs are tracked; they are provisioned or regenerated (see README).


## [0.4.0] — 2026-11-21 (pre-release)

### Added
- **Direct USB recovery on Windows** (`recoverx.usb`): device discovery via Win32 IOCTLs on zero-access
  handles plus Storage CIM enrichment; reliable drive-letter → physical-disk mapping through volume disk
  extents (works for dynamic/spanned volumes); removable USB/SD/MMC disks distinguished from internal storage.
- **System-disk protection:** system/boot disks, disks hosting `%SystemDrive%`, the Windows folder, page
  files, the running Python/RecoverX installation, the RecoverX workspace/temp, or the chosen output folder
  can never be selected. Non-USB storage is listed as protected with the reason.
- **Integrated read-only imaging** of `\\.\PhysicalDriveN` (GENERIC_READ only) with bounded 1 MiB
  sector-aligned reads, exclusive-create destination on a different physical disk, free-space / permission /
  disk-identity validation, streamed source SHA-256, destination re-read verification, optional source
  re-read, sector-level retry with zero-fill and an unreadable-range list, cancellation, disconnection
  handling, `*.img.partial` for incomplete images, partition layout (MBR/EBR/GPT/superfloppy) with offsets,
  and a JSON acquisition record including its limitations.
- **UAC-only-when-needed elevation:** the app runs as a standard user; only the imaging worker is started
  through the Windows consent prompt (`ShellExecuteExW runas`, `python -I`), and it re-verifies identity and
  destination itself. Already-elevated sessions image in-process.
- **Quick Recovery pipeline** (`recoverx.workflow`): acquisition → case registration (hash must equal the
  acquisition hash) → recovery → verified export, in a background thread with real stage events and cancel.
- **Export to a chosen output folder:** one copy per distinct SHA-256 (duplicates listed), original names
  and folders for TSK results (sanitised for Windows), post-copy hash verification, never overwriting;
  `RecoverX-report.pdf`, `manifest.json`, `inventory.csv`, `export.json`.
- **Structural validation** of JPEG, PNG, GIF, PDF and ZIP/DOCX/XLSX/PPTX (bounded CRC checks).
- **Known-original comparison:** paste SHA-256 hashes; matches are marked as exact.
- **Safe previews:** image thumbnails decoded and re-encoded with Pillow (pixel limit), short text excerpts.
- Acquisition details in the PDF report and JSON manifest; per-run export summary.
- `scripts/windows_launcher.py` (desktop-style Edge/Chrome app window, loopback only),
  `scripts/smoke_e2e.py` (real-engine end-to-end smoke test), `scripts/make_icon.py`, `constraints-windows.txt`.
- Documentation: `docs/WINDOWS_INSTALL.md`, `docs/USB_RECOVERY_TESTING.md`, this changelog.
- Tests: USB discovery/protection, Win32 structure parsing, write-access refusal, imaging (complete,
  bounded reads, unreadable sectors, disconnection, cancellation, failing device, changing source,
  no-overwrite), destination validation, partition parsing, elevated-helper protocol, all six recovery
  modes, export/validation/outcome classification, the USB pipeline, the UI (AppTest) including the
  confirmation dialog, and real-engine end-to-end recovery of deleted JPG + PDF in every mode.

### Changed
- **Premium UI/UX redesign:** single Quick Recovery page in five steps (source, method, output, start with
  live progress, results), deep-navy/charcoal theme with cyan/blue/purple accents, selectable cards,
  stage pipeline, honest progress (byte progress for imaging; activity indicator for engines that do not
  report progress), outcome banners, expandable technical sections. The multi-page sidebar is removed;
  expert pages are reachable through the in-page *Advanced workspace* switch.
- Method labels: *Automatic (CART only)* and *Automatic (rule-v1 only)* (previously "Conservative (… advice)");
  behaviour is unchanged. *Automatic (CART only)* requires an installed model.
- Windows setup: Python 3.12 preferred (works with the Python install manager), Sleuth Kit download always
  SHA-256 verified and executed as a check, pip health check for the venv, tested constraints, long-path
  warning, optional consent-based TestDisk install inside an existing WSL distribution, new icon/shortcut.
- Start script checks the environment and opens the app window through the launcher.
- New application icon (`assets/recoverx.ico/.png/.svg`). Version 0.4.0 everywhere.
- `.gitattributes` keeps CRLF line endings for `.cmd`/`.ps1`; `.gitignore` covers partial images,
  acquisition records, release builds and local tool configs.

### Preserved
- TSK, PhotoRec (Windows via unprivileged WSL), CART JSON models, rule-v1, Smart fallback, conservative
  automatic policy, case locks, atomic records, before/after evidence hashing, blocked-run recording, PDF/
  Markdown/JSON/CSV reports, Linux polkit capture and the Kali launcher.

### Known limitations
- Physical USB imaging has **not** been verified on real USB hardware (see `docs/USB_RECOVERY_TESTING.md`).
- Read-only access cannot prevent other Windows processes from writing to mounted volumes during imaging.
- Disks with 4096-byte logical sectors are imaged correctly, but TSK analysis assumes 512-byte units.
- No progress percentage is available while TSK/PhotoRec run (the tools do not report it).
- Recovered-file content previews are limited to images and plain text.

## [0.3.0] — 2026-11

- Quick Recovery linking case registration, analysis, recovery, results and PDF export; Smart Recovery with
  recorded fallback; evidence SHA-256 checked before and after; Windows setup with native TSK and PhotoRec
  in WSL; modernization branch integration (atomic records, bounded process output, case locking,
  multi-partition TSK, validated JSON CART); Kali launcher and polkit capture.
