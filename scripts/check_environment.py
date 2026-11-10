#!/usr/bin/env python3
"""Print an environment report. Exit code 1 if a required component is missing."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from recoverx.diagnostics import run_diagnostics  # noqa: E402

d = run_diagnostics()
ok = True
print(f"Python {d['python']}")
for p, v in d["packages"].items():
    print(f"  {'OK ' if v else 'MISSING'} {p} {v or ''}")
    ok &= bool(v) or p in ("pytest",)
for e in d["engines"]:
    print(f"  {'OK ' if e['available'] else 'MISSING'} engine {e['engine']} version={e['version']}")
    ok &= e["available"]
for e, path in d["dataset_tools"].items():
    print(f"  {'OK ' if path else 'missing (dataset generation only)'} {e}")
for k, v in d["directories"].items():
    print(f"  {'OK ' if v['writable'] else 'NOT WRITABLE'} {k}: {v['path']}")
print(f"  disk free: {d['disk_free_gb']} GB{'  (WARNING: low)' if d['disk_warning'] else ''}")
print(f"  model: {d['model'] or 'none trained yet'}")
print(f"  datasets: {d['datasets'] or 'none'} | experiments: {d['experiments'] or 'none'}")
if "--json" in sys.argv:
    print(json.dumps(d, indent=2))
sys.exit(0 if ok else 1)
