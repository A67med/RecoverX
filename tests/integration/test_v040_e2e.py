"""Real-engine end-to-end: deleted JPG + PDF on a synthetic FAT16 image, every Quick Recovery mode.

Uses the actual TSK and PhotoRec binaries (skipped with an explicit BLOCKED reason
when they are missing). The image is built with mtools in a temp dir; no real disk
is touched. The "USB" case streams the image through the same acquisition code
used for physical disks, via a file-backed source — it does NOT exercise hardware.
"""
import random
import subprocess

import pytest

from recoverx import workflow
from recoverx.datasets.generator import make_content
from recoverx.forensic.case_store import open_case
from recoverx.forensic.hashing import sha256_bytes
from recoverx.usb import controller, devices, imaging
from tests.conftest import needs_tools


@pytest.fixture(scope="module")
def deleted_media(tmp_path_factory):
    from tests.conftest import HAVE_TOOLS
    if not HAVE_TOOLS:
        pytest.skip("BLOCKED: forensic/dataset tools not installed")
    d = tmp_path_factory.mktemp("usbmedia")
    img = d / "usb-stick.img"
    with open(img, "wb") as f:
        f.truncate(24 * 2**20)
    subprocess.run(["mkfs.vfat", "-F", "16", "-n", "USBSTICK", str(img)], check=True, capture_output=True)
    rng = random.Random(2026)
    files = {"holiday.jpg": make_content("jpg", 48000, rng), "invoice.pdf": make_content("pdf", 30000, rng),
             "keep.txt": make_content("txt", 5000, rng)}
    for name, data in files.items():
        (d / name).write_bytes(data)
        subprocess.run(["mcopy", "-i", str(img), str(d / name), f"::{name}"], check=True)
    for name in ("holiday.jpg", "invoice.pdf"):
        subprocess.run(["mdel", "-i", str(img), f"::{name}"], check=True)
    hashes = {n: sha256_bytes(files[n]) for n in ("holiday.jpg", "invoice.pdf")}
    return {"image": img, "hashes": hashes, "bytes": img.read_bytes()}


def run_job(**params):
    job = workflow.start_quick_job(authorized=True, **params)
    assert job.done.wait(600), job.snapshot()
    return job.snapshot()


@needs_tools
@pytest.mark.parametrize("method", ["smart", "tsk", "photorec", "combined", "cart", "rule"])
def test_deleted_jpg_and_pdf_recovered_and_exported(deleted_media, tmp_path, method):
    snap = run_job(source="image", image_path=str(deleted_media["image"]), method=method,
                   output_dir=str(tmp_path / "out"), known_hashes="\n".join(deleted_media["hashes"].values()))
    assert snap["outcome"] == "success", snap["message"]
    run = snap["run"]
    assert run["source_unchanged"] and run["status"] == "completed"
    assert run["metrics"]["exact_recovered"] == 2, run["metrics"]
    exported = {f["sha256"]: f for f in snap["export"]["files"]}
    for name, h in deleted_media["hashes"].items():
        assert exported[h]["copy_verified"] and exported[h]["validation"]["state"] == "valid"
        if exported[h]["engine"] == "tsk":
            assert exported[h]["original_name"].lower().endswith(name[1:])  # FAT overwrites the first char of deleted names
    assert deleted_media["image"].read_bytes() == deleted_media["bytes"]  # evidence untouched
    sel = run["selection"]
    expected = {"tsk": ["tsk"], "photorec": ["photorec"], "combined": ["tsk", "photorec"],
                "cart": ["tsk", "photorec"], "rule": ["tsk", "photorec"]}
    if method in expected:
        assert sel["engines_attempted"] == expected[method]
    if method == "smart":
        assert sel["engines_attempted"][:len(sel["initial_engines"])] == sel["initial_engines"]


@needs_tools
def test_acquisition_path_then_recovery_from_streamed_image(deleted_media, tmp_path, monkeypatch):
    size = deleted_media["image"].stat().st_size
    disks = devices.build_inventory([{"number": 5, "size": size, "sector_size": 512, "bus_type": "USB",
                                      "vendor": "Test", "product": "Stick", "serial": "E2E"}], {}, {}, None, {})
    monkeypatch.setattr(devices, "list_devices", lambda **kw: disks)
    original = controller.AcquisitionJob.start
    monkeypatch.setattr(controller.AcquisitionJob, "start", lambda self, **kw: original(
        self, in_process=True, source_factory=lambda: imaging.FileSource(deleted_media["image"]),
        device_lister=lambda: disks, disks_for_path=lambda p: {0}))
    snap = run_job(source="usb", disk=disks[0], method="tsk", output_dir=str(tmp_path / "out"),
                   known_hashes="\n".join(deleted_media["hashes"].values()))
    assert snap["outcome"] == "success", snap["message"]
    acq = snap["acquisition"]
    assert acq["successful"] and acq["source_stream_sha256"] == acq["image_sha256"] == sha256_bytes(deleted_media["bytes"])
    assert acq["partition_layout"]["scheme"] == "superfloppy"
    rec = open_case(snap["case_id"]).load()
    assert rec["image_sha256_initial"] == acq["image_sha256"]
    assert snap["run"]["metrics"]["exact_recovered"] == 2
