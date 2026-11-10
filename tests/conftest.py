"""Shared fixtures. The FAT fixture is built with mtools (no root, no mount) from
files generated here, so tests need no downloaded corpus."""
import random
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from recoverx.datasets.generator import make_content  # noqa: E402
from recoverx.forensic.hashing import sha256_bytes  # noqa: E402

TOOLS = ["mkfs.vfat", "mcopy", "mdel", "tsk_recover", "fls", "fsstat", "mmls", "photorec"]
HAVE_TOOLS = all(shutil.which(t) for t in TOOLS)
needs_tools = pytest.mark.skipif(not HAVE_TOOLS, reason=f"BLOCKED: requires {', '.join(TOOLS)}")


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("RECOVERX_HOME", str(tmp_path / "home"))


@pytest.fixture(scope="session")
def fat_fixture(tmp_path_factory):
    if not HAVE_TOOLS:
        pytest.skip("BLOCKED: forensic/dataset tools not installed")
    d = tmp_path_factory.mktemp("fatfix")
    img = d / "fixture.img"
    with open(img, "wb") as f:
        f.truncate(16 * 2**20)
    subprocess.run(["mkfs.vfat", "-F", "16", str(img)], check=True, capture_output=True)
    rng = random.Random(42)
    files = {"a.png": make_content("png", 20000, rng), "b.txt": make_content("txt", 9000, rng),
             "c.jpg": make_content("jpg", 15000, rng), "d.pdf": make_content("pdf", 12000, rng)}
    for n, data in files.items():
        (d / n).write_bytes(data)
        subprocess.run(["mcopy", "-i", str(img), str(d / n), f"::{n}"], check=True)
    for n in ("a.png", "b.txt"):
        subprocess.run(["mdel", "-i", str(img), f"::{n}"], check=True)
    gt = {"deleted": [{"id": n, "sha256": sha256_bytes(files[n])} for n in ("a.png", "b.txt")],
          "allocated": [{"sha256": sha256_bytes(files[n])} for n in ("c.jpg", "d.pdf")]}
    return {"image": img, "gt": gt, "files": files}
