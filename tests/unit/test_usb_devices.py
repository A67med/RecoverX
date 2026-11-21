"""USB discovery, drive-letter → physical-disk mapping and system-disk protection (synthetic inputs)."""
import re
import struct
from pathlib import Path

import pytest

from recoverx.usb import devices, win32


def disk(n, bus="USB", size=16_000_000_000, serial="AA11", product="Flash Disk", vendor="Generic", **kw):
    return {"number": n, "size": size, "sector_size": 512, "bus_type": bus, "bus_type_code": 7,
            "removable_media": True, "vendor": vendor, "product": product, "revision": "1.0", "serial": serial, **kw}


def inventory(raw, extents=None, volumes=None, cim=None, protected=None):
    return {d.number: d for d in devices.build_inventory(raw, extents or {}, volumes or {}, cim, protected or {})}


def test_usb_disk_selectable_and_nvme_system_disk_protected():
    raw = [disk(0, bus="NVMe", size=256_000_000_000, product="SSD"), disk(2)]
    extents = {"C:": [(0, 1_048_576, 255_000_000_000)], "F:": [(2, 1_048_576, 15_999_000_000)]}
    vols = {"C:": {"filesystem": "NTFS", "label": "SYSTEM", "size": 255_000_000_000},
            "F:": {"filesystem": "FAT32", "label": "PHOTOS", "size": 15_999_000_000, "drive_type": "removable"}}
    cim = {"disks": [{"Number": 0, "FriendlyName": "Samsung SSD", "BusType": 17, "IsSystem": True, "IsBoot": True,
                      "PartitionStyle": 2}],
           "partitions": [{"DiskNumber": 2, "PartitionNumber": 1, "DriveLetter": "F", "Offset": 1_048_576,
                           "Size": 15_999_000_000}]}
    inv = inventory(raw, extents, vols, cim, {0: ["Hosts the Windows system drive"]})
    usb, ssd = inv[2], inv[0]
    assert usb.selectable and usb.is_usb and usb.letters == ["F:"]
    assert usb.volumes[0].filesystem == "FAT32" and usb.volumes[0].offset == 1_048_576
    assert usb.partitions == [{"number": 1, "offset": 1_048_576, "size": 15_999_000_000, "letter": "F",
                               "is_system": False, "is_boot": False, "gpt_type": "", "mbr_type": 0}]
    assert not ssd.selectable
    assert any("system disk" in r for r in ssd.protected_reasons)
    assert any("Not a removable USB" in r for r in ssd.protected_reasons)
    # selectable devices sort first
    assert [d.number for d in devices.build_inventory(raw, extents, vols, cim, {})][0] == 2


def test_usb_disk_hosting_windows_or_recoverx_is_protected():
    raw = [disk(1)]
    inv = inventory(raw, {"C:": [(1, 0, 10)]}, protected={1: ["Hosts the Windows system drive"]})
    assert not inv[1].selectable and inv[1].is_usb
    inv = inventory(raw, protected={1: ["Hosts RecoverX workspace or temporary files"]})
    assert not inv[1].selectable


def test_cim_system_and_boot_partition_flags_protect_usb_disk():
    cim = {"disks": [{"Number": 3, "BusType": 7}],
           "partitions": [{"DiskNumber": 3, "PartitionNumber": 1, "Offset": 1048576, "Size": 100, "IsSystem": True}]}
    inv = inventory([disk(3)], cim=cim)
    assert not inv[3].selectable and inv[3].is_system


def test_empty_card_reader_internal_sata_and_query_errors_are_blocked():
    raw = [disk(4, size=0), disk(5, bus="SATA"), {"number": 6, "error": "access denied"}, disk(7, bus="SD")]
    inv = inventory(raw)
    assert not inv[4].selectable and any("No media" in r for r in inv[4].protected_reasons)
    assert not inv[5].selectable and not inv[5].is_usb
    assert not inv[6].selectable
    assert inv[7].selectable  # SD/MMC readers are removable flash


def test_dynamic_or_spanned_volume_maps_to_every_backing_disk():
    raw = [disk(0, bus="SATA"), disk(1, bus="SATA")]
    inv = inventory(raw, {"E:": [(0, 100, 10), (1, 200, 10)]}, {"E:": {"filesystem": "NTFS"}})
    assert inv[0].letters == ["E:"] and inv[1].letters == ["E:"]


def test_identity_mismatch_detects_swapped_removed_and_protected_disks():
    d = devices.build_inventory([disk(2)], {}, {}, None, {})[0]
    expected = d.identity()
    assert devices.identity_mismatch(expected, d) is None
    assert "no longer connected" in devices.identity_mismatch(expected, None)
    other = devices.build_inventory([disk(2, serial="ZZ99")], {}, {}, None, {})[0]
    assert "serial" in devices.identity_mismatch(expected, other)
    bigger = devices.build_inventory([disk(2, size=32_000_000_000)], {}, {}, None, {})[0]
    assert "size" in devices.identity_mismatch(expected, bigger)
    now_protected = devices.build_inventory([disk(2)], {}, {}, None, {2: ["Hosts the selected output folder"]})[0]
    assert "protected" in devices.identity_mismatch(expected, now_protected)


def test_storage_descriptor_extents_and_geometry_parsing():
    vendor, product, serial = b"Kingston\x00", b"DataTraveler 3.0\x00", b"60A44C3FAE\x00"
    header = struct.pack("<IIBBBBIIIIII", 1, 0, 0, 0, 1, 0, 36, 36 + len(vendor), 0,
                         36 + len(vendor) + len(product), 7, 0)
    d = win32.parse_storage_descriptor(header + vendor + product + serial)
    assert (d.bus_type, d.vendor, d.product, d.serial, d.removable_media) == ("USB", "Kingston", "DataTraveler 3.0",
                                                                              "60A44C3FAE", True)
    raw = struct.pack("<I4x", 2) + struct.pack("<I4xqq", 3, 1048576, 4096) + struct.pack("<I4xqq", 4, 0, 512)
    assert win32.parse_disk_extents(raw) == [(3, 1048576, 4096), (4, 0, 512)]
    geom = struct.pack("<qIIII", 1000, 11, 255, 63, 512) + struct.pack("<q", 8_004_304_896)
    assert win32.parse_geometry_ex(geom) == (8_004_304_896, 512)


def test_handles_can_never_request_write_access():
    with pytest.raises(ValueError, match="never opens"):
        win32.Handle(r"\\.\PhysicalDrive9", 0x40000000)  # GENERIC_WRITE
    with pytest.raises(ValueError):
        win32.Handle(r"\\.\PhysicalDrive9", win32.GENERIC_READ | 0x40000000)


def test_usb_package_contains_no_write_format_or_dismount_calls():
    pkg = Path(win32.__file__).parent
    code = "\n".join(p.read_text(encoding="utf-8") for p in pkg.glob("*.py"))
    for forbidden in (r"GENERIC_WRITE\s*=", r"0x40000000", r"FSCTL_LOCK_VOLUME", r"FSCTL_DISMOUNT_VOLUME",
                      r"IOCTL_DISK_SET", r"IOCTL_DISK_CREATE", r"WriteFile\(", r"DeleteVolumeMountPoint",
                      r"diskpart", r"Format-Volume", r"Initialize-Disk", r"Clear-Disk"):
        assert not re.search(forbidden, code), forbidden


@pytest.mark.skipif(not win32.IS_WINDOWS, reason="requires Windows storage APIs")
def test_live_windows_inventory_protects_the_disk_running_recoverx():
    """Real (read-only) query of this machine: the disk hosting Python is never selectable."""
    inv = devices.list_devices()
    assert inv, "Windows reported no physical disks"
    host = win32.disks_for_path(str(Path(win32.__file__)))
    for d in inv:
        if d.number in host:
            assert not d.selectable
        assert d.selectable == (d.is_usb and not d.protected_reasons)
