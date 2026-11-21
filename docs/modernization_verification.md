# Modernization verification — 10 November 2026

## Scope and environment

Existing checkout and history preserved. Work performed on `codex/recoverx-modernization` against `A67med/RecoverX`.
Local platform: Ubuntu 24.04 under WSL, Python 3.12.3; TSK 4.12.1, PhotoRec 7.1, Streamlit 1.66.1, scikit-learn 1.9.1, Pillow 13.0.0.
No user evidence was tested, copied to Git, or uploaded. New fixtures, models, reports, logs and recovered outputs remain ignored/local.

## Verification performed

- Baseline: **50 passed, 1 failed**. `test_unwritable_output_is_reported` raised an uncaught PermissionError during output-directory creation.
- Final local suite: **91 passed, 0 skipped, 0 failed**, in 19.29 seconds.
- Ruff (`F`, `E9`) passed; `pip check` found no broken requirements; editable installation succeeded.
- Final dependency audit: **no known vulnerabilities** among 67 audited dependencies. The local RecoverX distribution is not on PyPI and is excluded by pip-audit. This is not a guarantee of absence of vulnerabilities.
- Dependency installation initially selected Pillow 12.3.0 under an overly restrictive upper bound. The audit detected advisories; the bound was corrected to `Pillow>=13,<14`, restoring the fixed release. Final tests and audit were rerun.
- Chrome desktop (1440×1050) and mobile viewport (390×844) reviewed locally. Browser smoke test started and completed a new recovery, verified the start button becomes available again, opened the inventory/report screens, and recorded zero page exceptions.
- GitHub Actions is configured for Python 3.11/3.12/3.13 and installs real tools. Remote CI status belongs to the PR checks, not this local result.

## Added regression coverage

Changed-source refusal before engine invocation; final hash failure; source/output overlap; permission/startup errors; missing tools; bounded stdout/stderr; cancellation; case locks; symlink/FIFO/hardlink inventory exclusion; unsupported containers; CSV formula protection; stale metadata truncation; safe JSON model checksum/schema/tree validation; seed/hash split leakage; generator overwrite refusal; invalid benchmark statistics; worker duplication; populated Streamlit pages.
The partitioned FAT16 fixture independently constructs an MBR with its filesystem at sector 2048. The tests verify TSK receives that offset, PhotoRec uses whole-image scope, expected deleted-file SHA-256 values are recovered, and source hashes remain unchanged.

## Actual CART evaluation

Existing synthetic records were re-evaluated; no recovery outcomes or training rows were invented. Splits remain 60 train / 12 validation / 24 test images, with seed and image-digest overlap rejected.
Hyperparameters are selected only using validation balanced accuracy. Depth 1 and minimum leaf size 4 won; optional balanced class weights did not win. Final training uses train+validation only. Test labels are inspected only for reporting after selection.

| Metric | Measured value |
|---|---|
| Held-out strategy-label agreement | 83.3333% (20/24) |
| Held-out balanced accuracy | 56.2963% |
| Macro F1 | 0.538721 |
| Oracle-eligible prediction rate | 91.6667% (22/24) |
| Majority / always PhotoRec agreement | 75.0000% |
| Rule-v1 agreement | 70.8333% |

Rows are actual class; columns are predicted class:

| Oracle class | TSK | PhotoRec | Combined |
|---|---:|---:|---:|
| TSK | 4 | 1 | 0 |
| PhotoRec | 2 | 16 | 0 |
| Combined | 0 | 1 | 0 |

| Class | Precision | Recall | F1 | Test support |
|---|---:|---:|---:|---:|
| tsk | 0.6667 | 0.8000 | 0.7273 | 5 |
| photorec | 0.8889 | 0.8889 | 0.8889 | 18 |
| combined | 0.0000 | 0.0000 | 0.0000 | 1 |

Four stratified group folds use training seeds only. Fold balanced accuracies: 0.604167, 0.944444, 0.592593, 0.625000; mean 0.691551.
These folds diagnose the already validation-selected configuration; they are not nested cross-validation estimates of the entire selection procedure. Rare classes may be missing within a fold. Per-class zero support is reported explicitly.

### Interpretation

This small dataset is strongly imbalanced (test: 18 PhotoRec, 5 TSK, 1 combined). CART missed the combined example. Label agreement is not evidence of equal recoverability, and leaf class fractions are not calibrated confidence. Automatic operation therefore defaults to both engines; out-of-range or incomplete inputs cannot justify a single-engine optimization.

## Fixed defects and architectural decisions

- Capture permission/output preparation errors in EngineRun instead of crashing.
- Verify registration digest before recovery and invalidate final integrity failures; correct run start timestamps.
- Stop silently ignoring PhotoRec offsets; enumerate TSK partitions and explicitly record whole-image carving scope.
- Bound command output while draining streams; treat truncated metadata as incomplete.
- Preserve partial output on errors/cancellation; isolate each new run and use POSIX case/experiment locks.
- Use atomic case/checkpoint writes, validated non-executable JSON CART and explicit model-domain checks.
- Resolve the registered nonzero tie-epsilon label policy and reject invalid/incomplete benchmark inputs.
- Refuse overwriting generated image fixtures and fix deterministic PDF metadata dates.
- Decouple worker lifetime from Streamlit reruns; ensure completion re-enables controls; guard analysis against concurrent case writes.
- Keep existing source layout and APIs. No database, heavy frontend, parallel forensic reads or new classifier family was introduced.

## Remaining limits

No full 96-image v0.2 recovery benchmark was run; archived timings and paper findings describe v0.1. No real evidence, physical disks, NTFS/exFAT corpus, encrypted/E01/split containers, native Windows, or crash-during-power-loss behavior was validated. Multi-partition enumeration is implemented, while the new real partition test has one FAT16 partition.
Cancellation waits for hashing/inventory to finish a stage. Hard process termination may prevent a final hash; checkpoints do not automatically resume an engine. Case inventories still consume memory proportional to output count. The log is not tamper-proof; raw-image read access is not a hardware write blocker. This remains a trusted, local single-user app.

## Reproduce

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check src scripts tests
.venv/bin/python -m pip check
.venv/bin/python -m pip_audit
.venv/bin/python scripts/evaluate_model.py
.venv/bin/python scripts/install_evaluated_model.py
```

## Technical references

- [TSK tsk_recover manual](https://sleuthkit.org/sleuthkit/man/tsk_recover.html): deleted-file default and sector-offset semantics.
- [CGSecurity scripted operation](https://www.cgsecurity.org/wiki/Scripted_run): PhotoRec command construction and scope.
- [scikit-learn model persistence](https://scikit-learn.org/stable/model_persistence.html): pickle-based loading risks. RecoverX uses a limited JSON tree evaluator instead.
