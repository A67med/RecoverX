"""Partition detection and filesystem offsets on synthetic images (MBR, EBR, GPT, superfloppy)."""
import struct
import uuid

from recoverx.usb.partitions import detect_filesystem, layout_of_image, parse_layout

BASIC = uuid.UUID("ebd0a0a2-b9e5-4433-87c0-68b6b72699c7")


def boot(kind):
    b = bytearray(512)
    b[0] = 0xEB
    b[510:512] = b"\x55\xaa"
    if kind == "FAT32":
        b[82:87] = b"FAT32"
    elif kind == "FAT16":
        b[54:59] = b"FAT16"
    elif kind == "NTFS":
        b[3:11] = b"NTFS    "
    elif kind == "exFAT":
        b[3:11] = b"EXFAT   "
    return bytes(b)


def mbr(entries):
    m = bytearray(512)
    for i, (ptype, start, count) in enumerate(entries):
        m[446 + 16 * i:462 + 16 * i] = struct.pack("<B3sB3sII", 0, b"\0" * 3, ptype, b"\0" * 3, start, count)
    m[510:512] = b"\x55\xaa"
    return m


def reader(buf):
    return lambda off, n: bytes(buf[off:off + n])


def test_signatures():
    assert detect_filesystem(boot("FAT32")) == "FAT32"
    assert detect_filesystem(boot("FAT16")) == "FAT16"
    assert detect_filesystem(boot("NTFS")) == "NTFS"
    assert detect_filesystem(boot("exFAT")) == "exFAT"
    assert detect_filesystem(bytes(512)) is None


def test_mbr_partition_offsets_in_bytes_and_tsk_sectors():
    img = bytearray(8 * 2**20)
    img[:512] = mbr([(0x0C, 2048, 8192), (0x07, 10240, 4096)])
    img[2048 * 512:2048 * 512 + 512] = boot("FAT32")
    img[10240 * 512:10240 * 512 + 512] = boot("exFAT")
    lay = parse_layout(reader(img), len(img))
    assert lay["scheme"] == "MBR"
    assert [(p["offset_bytes"], p["tsk_sector_offset"], p["type"]) for p in lay["partitions"]] == \
        [(2048 * 512, 2048, "FAT32"), (10240 * 512, 10240, "exFAT")]


def test_extended_partition_chain_is_followed():
    img = bytearray(16 * 2**20)
    img[:512] = mbr([(0x0F, 4096, 20000)])
    ebr = mbr([(0x06, 63, 1000)])
    img[4096 * 512:4096 * 512 + 512] = ebr
    img[(4096 + 63) * 512:(4096 + 63) * 512 + 512] = boot("FAT16")
    lay = parse_layout(reader(img), len(img))
    assert lay["partitions"][0]["start_lba"] == 4096 + 63 and lay["partitions"][0]["type"] == "FAT16"


def test_gpt_partitions():
    img = bytearray(4 * 2**20)
    img[:512] = mbr([(0xEE, 1, 8191)])
    hdr = bytearray(92)
    hdr[:8] = b"EFI PART"
    struct.pack_into("<QII", hdr, 72, 2, 128, 128)
    img[512:604] = hdr
    entry = bytearray(128)
    entry[:16] = BASIC.bytes_le
    struct.pack_into("<QQ", entry, 32, 2048, 6143)
    entry[56:56 + 10] = "DATA".encode("utf-16-le") + b"\0\0"
    img[1024:1152] = entry
    img[2048 * 512:2048 * 512 + 512] = boot("NTFS")
    lay = parse_layout(reader(img), len(img))
    assert lay["scheme"] == "GPT"
    p = lay["partitions"][0]
    assert (p["offset_bytes"], p["sectors"], p["type"], p["description"]) == (2048 * 512, 4096, "NTFS", "DATA")


def test_superfloppy_usb_without_partition_table(tmp_path):
    img = bytearray(2 * 2**20)
    img[:512] = boot("FAT32")
    path = tmp_path / "superfloppy.img"
    path.write_bytes(img)
    lay = layout_of_image(path)
    assert lay["scheme"] == "superfloppy" and lay["partitions"][0]["offset_bytes"] == 0


def test_truncated_image_warns_and_blank_media_reports_none():
    img = bytearray(2 * 2**20)
    img[:512] = mbr([(0x0C, 2048, 10 ** 6)])
    lay = parse_layout(reader(img), len(img))
    assert any("beyond the end" in w for w in lay["warnings"])
    assert parse_layout(reader(bytearray(4096)), 4096)["scheme"] == "none"


def test_4k_sector_media_reports_tsk_512_offsets(tmp_path):
    img = bytearray(4 * 2**20)
    img[:512] = mbr([(0x0C, 256, 512)])
    img[256 * 4096:256 * 4096 + 512] = boot("FAT32")
    path = tmp_path / "4k.img"
    path.write_bytes(img)
    lay = layout_of_image(path, sector_size=4096)
    assert lay["partitions"][0]["offset_bytes"] == 256 * 4096
    assert lay["partitions"][0]["tsk_sector_offset"] == 256 * 8
    assert any("4096" in w for w in lay["warnings"])
