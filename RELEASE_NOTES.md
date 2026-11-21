# RecoverX v0.3.0

- Quick Recovery links case registration, analysis, recovery, results and metadata-only PDF export. Windows opens this view first and still offers advanced pages.
- Evidence SHA-256 is checked against the registered baseline before tools start and verified again after recovery. Blocked attempts are recorded.
- Smart Recovery records the initial plan, any fallback trigger, per-engine outcomes and the order of attempts.
- Windows setup detects unusable virtual environments. TSK runs natively and PhotoRec runs in an unprivileged WSL distribution with TestDisk installed. UAC stays enabled.
- Integrated the modernization branch with atomic case records, bounded process output, case locking, multi-partition TSK recovery and validated JSON CART models. The historical pickle is never loaded.
- Kali users can register the desktop launcher and optionally capture an authorized, unmounted source through polkit.

The historical benchmarks are unchanged. No new full-corpus benchmark or real-media accuracy claim is included. See the installation guide for the tested platforms and prerequisites.
