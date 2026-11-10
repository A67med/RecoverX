# Architecture

```
            ┌────────────── Streamlit dashboard (ui/dashboard.py) ──────────────┐
            │  reads persisted case.json / events.jsonl / experiment records     │
            └──────────────┬──────────────────────────────────┬─────────────────┘
                           │                                  │
               recovery/orchestrator.py            benchmarking/experiment.py
   hash₀ → analyze → features → select → engines → verify → dedup → hash₁
              │            │          │         │
 forensic/filesystem_   ml/features  ml/selector engines/{sleuthkit,photorec}_engine
 analyzer (mmls/fsstat/fls)          (rule-v1, CART)   └ base_engine: preflight, safe output,
                                                          subprocess (process.py), inventory
 forensic/case_store: cases/<id>/{case.json, events.jsonl, runs/<run>/<engine>/…}
```

**Shared interfaces (agree in Week 1, change only by review):**
- `BaseEngine.run(image, output_dir, sector_offset, timeout, cancel_event) -> EngineRun`
- `RecoveredFile` / `EngineRun` / `CommandResult` dataclasses (`models.py`)
- `extract_features(FsAnalysis) -> dict` with `FEATURE_NAMES` (schema version in model meta)
- `run_recovery(case, method, ground_truth, …) -> run dict` (persisted in `case.json`)
- Ground truth JSON: `{"deleted":[{"id","sha256"}], "allocated":[{"sha256"}]}`

**Dependencies (why each):** scikit-learn (CART), numpy/pandas (tables), scipy (Wilcoxon),
joblib (model files), Pillow (deterministic test content), streamlit + plotly (UI), pytest.
No database, no network services, no deep learning.
