"""Raw image acquisition: bounded streaming, SHA-256, errors, cancellation, disconnection.

The real Windows source (\\\\.\\PhysicalDriveN) needs hardware; these tests drive the same
``acquire`` algorithm through disposable file-backed and fault-injecting sources.
"""
import hashlib
import os
import threading

import pytest

from recoverx.usb import imaging
from recoverx.usb.imaging import DisconnectedError, FileSource, acquire, validate_destination


def make_source(tmp_path, size=3 * 1024 * 1024 + 4096, seed=7):
    data = bytes((i * seed + i // 512) % 251 for i in range(size))
    p = tmp_path / "device.bin"
    p.write_bytes(data)
    return p, data


class FaultySource:
    """Behaves like a disk with unreadable sectors or a device that disappears."""

    def __init__(self, data, *, bad=(), disconnect_at=None, sector_size=512, mutate_after_first_pass=False):
        self.data, self.bad, self.disconnect_at = bytearray(data), set(bad), disconnect_at
        self.size, self.sector_size = len(data), sector_size
        self.description = {"kind": "test"}
        self.reads = 0
        self.mutate = mutate_after_first_pass
        self.max_request = 0

    def read_at(self, offset, length):
        self.reads += 1
        self.max_request = max(self.max_request, length)
        if self.disconnect_at is not None and offset >= self.disconnect_at:
            raise DisconnectedError(1167, "device not connected")
        for s in range(offset // 512, (offset + length + 511) // 512):
            if s in self.bad:
                raise OSError(23, "CRC error")
        if self.mutate and offset == 0 and self.reads > 2:
            self.data[0] ^= 0xFF
        return bytes(self.data[offset:offset + length])

    def close(self):
        pass


def test_complete_acquisition_hashes_and_verifies(tmp_path):
    src_path, data = make_source(tmp_path)
    events = []
    out = tmp_path / "out" / "usb.img"
    out.parent.mkdir()
    src = FileSource(src_path)
    try:
        res = acquire(src, out, progress=events.append, chunk_size=1024 * 1024)
    finally:
        src.close()
    assert res.status == "completed" and res.successful and res.image_verified
    assert res.bytes_copied == len(data) == out.stat().st_size
    assert res.source_stream_sha256 == res.image_sha256 == hashlib.sha256(data).hexdigest()
    assert out.read_bytes() == data
    assert res.unreadable_bytes == 0 and res.unreadable_ranges == []
    stages = {e["stage"] for e in events}
    assert {"imaging", "verifying_image", "finished"} <= stages
    assert all(e["bytes_done"] <= e["bytes_total"] for e in events if "bytes_done" in e)
    assert res.limitations and "does not prevent" in " ".join(res.limitations)


def test_reads_are_bounded_and_sector_aligned(tmp_path):
    _, data = make_source(tmp_path, size=5 * 1024 * 1024)
    src = FaultySource(data, sector_size=4096)
    res = acquire(src, tmp_path / "a.img", chunk_size=1_000_000)  # not a multiple of 4096 → rounded down
    assert res.successful
    assert src.max_request <= 1_000_000 and src.max_request % 4096 == 0


def test_unreadable_sectors_are_zero_filled_listed_and_not_successful(tmp_path):
    _, data = make_source(tmp_path)
    bad = {10, 11, 12, 4000}
    res = acquire(FaultySource(data, bad=bad), tmp_path / "bad.img")
    assert res.status == "completed_with_errors" and not res.successful
    assert res.unreadable_bytes == 4 * 512
    assert res.unreadable_ranges[0]["offset"] == 10 * 512 and res.unreadable_ranges[0]["length"] == 3 * 512
    img = (tmp_path / "bad.img").read_bytes()
    assert img[10 * 512:13 * 512] == b"\x00" * 1536 and img[:5120] == data[:5120]
    assert res.image_verified  # destination equals what was read (zero-fill included)
    assert res.source_stream_sha256 != hashlib.sha256(data).hexdigest()


def test_disconnection_marks_partial_and_never_success(tmp_path):
    _, data = make_source(tmp_path)
    res = acquire(FaultySource(data, disconnect_at=2 * 1024 * 1024), tmp_path / "gone.img")
    assert res.status == "disconnected" and not res.successful
    assert res.bytes_copied == 2 * 1024 * 1024
    assert res.image_path.endswith(".img.partial") and not (tmp_path / "gone.img").exists()
    assert os.path.getsize(res.image_path) == 2 * 1024 * 1024


def test_cancellation_stops_and_marks_partial(tmp_path):
    _, data = make_source(tmp_path, size=8 * 1024 * 1024)
    cancel = threading.Event()

    class Cancelling(FaultySource):
        def read_at(self, offset, length):
            if offset >= 1024 * 1024:
                cancel.set()
            return super().read_at(offset, length)

    res = acquire(Cancelling(data), tmp_path / "c.img", cancel=cancel)
    assert res.status == "cancelled" and not res.successful
    assert res.bytes_copied < len(data) and res.image_path.endswith(".partial")


def test_failing_device_stops_after_too_many_unreadable_sectors(tmp_path, monkeypatch):
    _, data = make_source(tmp_path, size=2 * 1024 * 1024)
    bad = set(range(0, 4096))
    monkeypatch.setattr(imaging, "MAX_UNREADABLE_BYTES", 64 * 1024)
    res = acquire(FaultySource(data, bad=bad), tmp_path / "f.img")
    # every sector unreadable → exceeds 5% → stop as failed, never success
    assert res.status == "failed" and not res.successful


def test_source_reread_detects_a_changing_source(tmp_path):
    _, data = make_source(tmp_path)
    res = acquire(FaultySource(data, mutate_after_first_pass=True), tmp_path / "m.img", reread_source=True)
    assert res.source_reread_matches is False and res.status == "failed" and not res.successful
    ok = acquire(FaultySource(data), tmp_path / "ok.img", reread_source=True)
    assert ok.source_reread_matches is True and ok.successful


def test_never_overwrites_and_requires_img_extension(tmp_path):
    _, data = make_source(tmp_path, size=4096)
    existing = tmp_path / "exists.img"
    existing.write_bytes(b"keep me")
    res = acquire(FaultySource(data), existing)
    assert res.status == "failed" and existing.read_bytes() == b"keep me"
    with pytest.raises(ValueError):
        acquire(FaultySource(data), tmp_path / "x.raw")


def test_partition_layout_recorded_after_imaging(tmp_path):
    import struct
    data = bytearray(4 * 1024 * 1024)
    data[446:462] = struct.pack("<B3sB3sII", 0, b"\0" * 3, 0x0C, b"\0" * 3, 2048, 4096)
    data[510:512] = b"\x55\xaa"
    boot = 2048 * 512
    data[boot] = 0xEB
    data[boot + 82:boot + 87] = b"FAT32"
    data[boot + 510:boot + 512] = b"\x55\xaa"
    res = acquire(FaultySource(bytes(data)), tmp_path / "p.img")
    layout = res.partition_layout
    assert layout["scheme"] == "MBR"
    assert layout["partitions"][0]["offset_bytes"] == 2048 * 512 and layout["partitions"][0]["type"] == "FAT32"
    assert layout["partitions"][0]["tsk_sector_offset"] == 2048


def test_destination_validation_blocks_unsafe_targets(tmp_path):
    ok = validate_destination(tmp_path / "images", required_bytes=1024, source_disk=2, disks_for_path=lambda p: {0})
    assert ok == [] and not (tmp_path / "images").exists()  # validation creates nothing
    same = validate_destination(tmp_path, required_bytes=1024, source_disk=2, disks_for_path=lambda p: {2})
    assert any("source disk" in p for p in same)

    def unknown(p):
        raise OSError("no extents")
    assert any("Cannot verify" in p for p in validate_destination(tmp_path, required_bytes=1, source_disk=2,
                                                                     disks_for_path=unknown))
    huge = validate_destination(tmp_path, required_bytes=1 << 60, source_disk=None)
    assert any("Not enough free space" in p for p in huge)
    assert validate_destination("relative/dir", required_bytes=1, source_disk=None)
    unc = validate_destination(r"\\server\share\x", required_bytes=1, source_disk=None)
    assert unc and (os.name != "nt" or any("Network" in p for p in unc))  # on POSIX it is a relative path
    f = tmp_path / "file.txt"
    f.write_text("x")
    assert any("not a folder" in p for p in validate_destination(f, required_bytes=1, source_disk=None))
