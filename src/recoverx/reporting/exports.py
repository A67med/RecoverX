"""Metadata-only report exports; recovered contents are never embedded."""
from __future__ import annotations
import csv
import io
from ..forensic.case_store import build_manifest


def csv_inventory(rows: list[dict]) -> str:
    if not rows:
        return ""
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=list(rows[0]))
    writer.writeheader()
    for row in rows:
        safe = {}
        for key, value in row.items():
            if isinstance(value, str) and (value.lstrip().startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n"))):
                value = "'" + value
            safe[key] = value
        writer.writerow(safe)
    return output.getvalue()


def case_report(case) -> str:
    rec = case.load()
    # Untrusted names/notes are intentionally omitted from Markdown; the JSON
    # manifest retains paths as inert strings.
    lines = ["# RecoverX forensic operation report", "", f"Case: {rec['case_id']}",
             f"Evidence size: {rec['image_size']} bytes", f"Registered SHA-256: {rec['image_sha256_initial']}",
             "", "## Scope and limitations", "",
             "This report records application observations, not legal chain-of-custody certification.",
             "Exact match means SHA-256 equality to examiner-supplied ground truth. It does not establish authenticity of that ground truth.",
             "Signature/type hints, filenames and leaf class fractions are not proof of complete recovery.",
             "Original evidence is read through tools; use an OS or hardware write blocker for enforceable write protection.", ""]
    for run in rec.get("runs", []):
        sel = run["selection"]
        lines += [f"## Run {run['run_id']}", "", f"Status: {run['status']}",
                  f"Started: {run['started_at']}", f"Finished: {run['finished_at']}",
                  f"Requested method: {run['method']}; applied strategy: {sel['strategy_used']}",
                  f"Source unchanged: {run['source_unchanged']}",
                  f"SHA-256 before: {run['image_sha256_before']}", f"SHA-256 after: {run['image_sha256_after']}",
                  f"Output files: {run['metrics']['outputs']}; distinct contents: {run['metrics']['distinct_contents']}",
                  f"Duration: {run['timing']['total_s']:.3f} seconds", "",
                  "Selection, commands, tool versions, warnings, paths, output hashes and event timestamps are included in the companion JSON manifest.", ""]
    lines += ["## Inventory", "", f"Runs included: {len(build_manifest(case)['runs'])}"]
    return "\n".join(lines)
