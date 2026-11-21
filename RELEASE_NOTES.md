# One-Click Kali Edition

- Added `Install-RecoverX.desktop` and `INSTALL_ON_KALI.sh` to register a double-click desktop/application-menu launcher.
- Added `scripts/desktop_launcher.py` that boots an isolated `.venv` on first run if needed, opens a local browser URL and reuses an existing RecoverX server.
- Added Quick Recovery: one action for case creation or selecting a saved case, analysis, CART/TSK/PhotoRec strategy execution and results; direct file download limited to 40 MiB; export PDF in same screen.
- Added optional read-only GUI capture of an unmounted non-system Linux test disk using `pkexec dd`, without formatting or automatically deleting anything.
- Added offline tests for acquisition safety filters and the guided workflow.
- Forensic integration and graphical polkit flow still require validation on the user's Kali host.

---

# RecoverX — improved release (November 2026)

## Changes made in this release

1. **Source evidence integrity:** SHA-256 is verified against the case baseline before analysis and before any recovery engine runs. Changed/missing/unbaselined images block processing, log a specific event, and carry an explicit case status. Source changes during recovery are also flagged.
2. **Correct timing:** each recovery run saves its own `started_at`, rather than the creation timestamp of the parent case.
3. **CART installation:** `scripts/install_bundled_model.py` activates the model actually included under `results/exp1/models` without relying on archived workstation-specific paths. The legacy `train_model.py --install-only --exp results/exp1` now works without a local dataset.
4. **Safe Demo Mode:** a Case Management button creates an independent synthetic FAT16-delete disk image, validates it, stores local ground truth, and creates a ready-to-use case. No real device is accessed by this feature.
5. **Recovery status:** the dashboard displays real pipeline stages during the run, chosen strategy, engine status and elapsed time. It does not display invented percentages.
6. **Metadata-only PDF export:** Case Management and Evidence & Audit can export a report with source hashes, recovery records, selected engines and an audit disclaimer. Recovered file bodies are not opened or embedded.
7. **Simpler navigation:** Model Training and Benchmark Laboratory moved behind the optional `Show advanced research pages` sidebar toggle. The included exp1 results are available for read-only historical exploration.
8. **Partition offset awareness:** interactive recovery now enables pre-analysis by default so TSK can use a detected sector offset; research benchmark fixed-method behavior is left unchanged. PhotoRec's partition behavior has NOT been rewritten or retested.
9. **Tests/documentation:** added regression tests for tampering, timestamps, bundled model install, PDF generation and demo case creation. Archived experimental data remains unmodified for provenance.

## Verification in the packaging environment

- 36 passed, 16 skipped, 0 failed (`python -m pytest -q`)
- Skips: Streamlit is not installed and the OS-level TSK/PhotoRec/mtools binaries are not available here. Those functionalities **must be tested on Ubuntu** before claiming a complete real-engine end-to-end run.
- PDF generated and visually rendered; project sources compile.
- Bundled CART model installation was exercised; the model was trained under scikit-learn 1.9.1 and a version warning may arise if opened under another version (1.8.0 in the packaging environment).
- No new recovery accuracy/latency measurements were generated. Existing exp1 records are historical, unchanged.

## Known limitations / deferred work

- PhotoRec uses its own partition detection; partitioned disks need independent verification.
- The TestDisk/PhotoRec and Sleuth Kit binaries are external system dependencies and are not included in this archive.
- Streamlit behavior has not been live-validated in the packaging environment because the library is absent.
- Actual output verification requires independent ground truth; without it, hashes identify outputs but do not prove deleted-file exact recovery.
- Generated demo datasets consume real disk space and remain under `workspace/datasets/` until explicitly removed by the user.
- Historical experiment metadata contains original-workstation absolute paths; those reports are intentionally not rewritten. UI uses archived data read-only and the model installer resolves the bundled model directly.

## Quick start

See `START_HERE_AR.md` for Arabic instructions and `docs/installation_and_user_guide.md` for English steps.
