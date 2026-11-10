# Project Plan — Team of Four, Eight Weeks (provisional)

> ⚠️ **Final-examination date not provided.** Dates assume a start on Mon 2 Nov 2026 and
> finish on Fri 25 Dec 2026, which meets the two-week buffer only if exams start on or after
> **Fri 8 Jan 2027**. Replace the dates once the real exam date is known; if it is earlier,
> apply the scope cuts at the bottom.

A working baseline (all milestones 0–9 at MVP level) already exists. The team's job is to
**understand, extend, verify and defend** it — every member must be able to explain the full pipeline.

## Ownership

| Member | Primary ownership | Paper sections | Also contributes |
|---|---|---|---|
| M1 — Forensic engines | `engines/`, `forensic/filesystem_analyzer.py`, partitioned-image support, PhotoRec offset handling | 5 Architecture, 15 Limitations | reviews M4's dataset changes |
| M2 — ML & selection | `ml/`, label objective, rule baseline, sensitivity analysis, larger-image extension | 4, 6, 7 | reviews M1's feature inputs |
| M3 — Application | `ui/`, case workflow, exports, usability test with 2 outside students | demo script, user guide | reviews orchestrator changes |
| M4 — Benchmark & research | `datasets/`, `benchmarking/`, statistics, literature review, paper assembly | 1–3, 8–14, 16 | runs final benchmark |

Rules: every change by pull request with one reviewer from a different area; `pytest -q` must pass before merge; interfaces in `docs/architecture.md` change only with all four agreeing.

## Schedule

| Week | Dates | Goals | Owner(s) | Exit check |
|---|---|---|---|---|
| 1 | 2–6 Nov | Read code; each member reruns tests + one benchmark phase; finish literature search (Table L1 ≥ 12 verified papers); freeze scope | all; lit. M4 | everyone demos the app end-to-end |
| 2 | 9–13 Nov | Partitioned image test (MBR + offset) for TSK and PhotoRec; NTFS feasibility check | M1 | new integration test passes |
| 3 | 16–20 Nov | Larger-image extension (e.g., 1–4 GiB) to test the size hypothesis; disk-space budget | M4, M2 | dataset v2 validates |
| 4 | 23–27 Nov | **Integration date 1**: run exp2 on dataset v2 (same pre-registered objective) | M4 | records saved, 0 hash changes |
| 5 | 30 Nov–4 Dec | Analysis of exp2; sensitivity; usability test of dashboard | M2, M3 | analysis.json for exp2 |
| 6 | 7–11 Dec | Paper full draft generated from records; internal review | M4 + all | draft circulated |
| 7 | 14–18 Dec | **Feature freeze (Mon 14 Dec)**; security/regression tests; documentation pass | all | 0 failing tests |
| 8 | 21–25 Dec | **Final submission (Fri 25 Dec)**; demo rehearsal ×2 | all | rehearsal timed ≤ 15 min |
| buffer | ≥ 2 weeks | no new features; fixes only | — | — |

## Critical path
Literature (W1) → dataset v2 (W3) → exp2 runs (W4) → analysis (W5) → paper (W6). A slip in
dataset v2 delays everything after it.

## If the exam is earlier — scope cuts in this order
1. Drop the larger-image extension (report exp1 only; it is already complete).
2. Drop NTFS feasibility.
3. Reduce UI polish.
Never cut: evidence hashing, grouped splits, pre-registration, honest reporting of the negative result.
