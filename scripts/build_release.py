#!/usr/bin/env python3
"""Build the distributable source ZIP from a committed Git revision.

Uses ``git archive`` so the ZIP contains exactly the tracked files of that
commit (no virtual environments, caches, tools, evidence, workspaces or
secrets), with Windows scripts in CRLF form per .gitattributes. Writes
release/RecoverX-v<version>-source.zip and a SHA256SUMS.txt next to it.
"""
from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = (".venv/", "tools/", "downloads/", "workspace/", ".env", "__pycache__/", ".smoke/", ".claude/")


def main() -> int:
    sys.path.insert(0, str(ROOT / "src"))
    from recoverx import __version__
    ap = argparse.ArgumentParser()
    ap.add_argument("--rev", default="HEAD")
    args = ap.parse_args()
    if subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT, capture_output=True,
                      text=True, check=True).stdout.strip():
        print("Refusing to build: tracked files have uncommitted changes.", file=sys.stderr)
        return 1
    out_dir = ROOT / "release"
    out_dir.mkdir(exist_ok=True)
    name = f"RecoverX-v{__version__}"
    zpath = out_dir / f"{name}-source.zip"
    if zpath.exists():
        zpath.unlink()
    subprocess.run(["git", "archive", "--format=zip", f"--prefix={name}/", "-o", str(zpath), args.rev],
                   cwd=ROOT, check=True)
    with zipfile.ZipFile(zpath) as z:
        names = z.namelist()
        bad = [n for n in names if any(f"/{f}" in n or n.endswith("/.env") for f in FORBIDDEN)]
        if bad or z.testzip():
            print(f"Archive check failed: {bad[:5]}", file=sys.stderr)
            return 1
        cmd = z.read(f"{name}/START_RECOVERX_WINDOWS.cmd")
        if b"\r\n" not in cmd:
            print("START_RECOVERX_WINDOWS.cmd lost its CRLF line endings", file=sys.stderr)
            return 1
    digest = hashlib.sha256(zpath.read_bytes()).hexdigest()
    commit = subprocess.run(["git", "rev-parse", args.rev], cwd=ROOT, capture_output=True, text=True,
                            check=True).stdout.strip()
    (out_dir / "SHA256SUMS.txt").write_text(f"{digest}  {zpath.name}\n", encoding="ascii")
    print(f"{zpath}\n{len(names)} entries · {zpath.stat().st_size:,} bytes · commit {commit}\nSHA-256 {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
