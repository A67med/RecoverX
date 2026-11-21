"""Thin ctypes wrappers over documented Win32 storage APIs.

Only read access is ever requested for physical disks (GENERIC_READ). Metadata
queries open devices with *zero* access rights, which Windows allows for
non-administrators and which cannot read or write sectors.

Opening a disk read-only does NOT stop Windows, Explorer, antivirus or any other
process from writing to the mounted volumes on that disk. RecoverX records this
limitation in every acquisition record; use a hardware write blocker or the
device's physical write-protect switch when enforceable protection is required.
"""
from __future__ import annotations

import os
import string
import struct
from dataclasses import dataclass

IS_WINDOWS = os.name == "nt"

GENERIC_READ = 0x80000000
FILE_SHARE_READ = 0x1
FILE_SHARE_WRITE = 0x2
OPEN_EXISTING = 3
FILE_FLAG_SEQUENTIAL_SCAN = 0x08000000
INVALID_HANDLE_VALUE = -1

IOCTL_VOLUME_GET_VOLUME_DISK_EXTENTS = 0x00560000
IOCTL_STORAGE_GET_DEVICE_NUMBER = 0x002D1080
IOCTL_STORAGE_QUERY_PROPERTY = 0x002D1400
IOCTL_DISK_GET_DRIVE_GEOMETRY_EX = 0x000700A0
IOCTL_DISK_GET_LENGTH_INFO = 0x0007405C

ERROR_ACCESS_DENIED = 5
ERROR_CANCELLED = 1223

# Error codes meaning the device itself went away (abort, never zero-fill).
DISCONNECT_ERRORS = {2, 3, 6, 21, 55, 433, 1167, 1617}
# Error codes that indicate unreadable media regions (retry per sector, zero-fill).
MEDIA_ERRORS = {23, 25, 27, 30, 483, 1117, 1784}

BUS_TYPES = {
    0: "Unknown", 1: "SCSI", 2: "ATAPI", 3: "ATA", 4: "1394", 5: "SSA", 6: "Fibre Channel",
    7: "USB", 8: "RAID", 9: "iSCSI", 10: "SAS", 11: "SATA", 12: "SD", 13: "MMC",
    14: "Virtual", 15: "File Backed Virtual", 16: "Storage Spaces", 17: "NVMe", 18: "SCM", 19: "UFS",
}
DRIVE_TYPES = {0: "unknown", 1: "no_root", 2: "removable", 3: "fixed", 4: "network", 5: "cdrom", 6: "ramdisk"}


class Win32Error(OSError):
    def __init__(self, function: str, code: int):
        super().__init__(code, f"{function} failed with Windows error {code}: {_format_error(code)}")
        self.function = function
        self.code = code


def _format_error(code: int) -> str:
    if not IS_WINDOWS:
        return "unavailable"
    try:
        import ctypes
        return ctypes.FormatError(code).strip()
    except Exception:  # pragma: no cover - defensive
        return "unknown error"


_k32 = None


def _kernel32():
    global _k32
    if _k32 is not None:
        return _k32
    if not IS_WINDOWS:
        raise OSError("Windows storage APIs are only available on Windows")
    import ctypes
    from ctypes import wintypes as w
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateFileW.restype = w.HANDLE
    k.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, ctypes.c_void_p, w.DWORD, w.DWORD, w.HANDLE]
    k.DeviceIoControl.restype = w.BOOL
    k.DeviceIoControl.argtypes = [w.HANDLE, w.DWORD, ctypes.c_void_p, w.DWORD, ctypes.c_void_p, w.DWORD,
                                  ctypes.POINTER(w.DWORD), ctypes.c_void_p]
    k.ReadFile.restype = w.BOOL
    k.ReadFile.argtypes = [w.HANDLE, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD), ctypes.c_void_p]
    k.SetFilePointerEx.restype = w.BOOL
    k.SetFilePointerEx.argtypes = [w.HANDLE, ctypes.c_longlong, ctypes.POINTER(ctypes.c_longlong), w.DWORD]
    k.CloseHandle.restype = w.BOOL
    k.CloseHandle.argtypes = [w.HANDLE]
    k.GetLogicalDrives.restype = w.DWORD
    k.GetDriveTypeW.restype = w.UINT
    k.GetDriveTypeW.argtypes = [w.LPCWSTR]
    k.GetVolumeInformationW.restype = w.BOOL
    k.GetVolumeInformationW.argtypes = [w.LPCWSTR, w.LPWSTR, w.DWORD, ctypes.POINTER(w.DWORD),
                                        ctypes.POINTER(w.DWORD), ctypes.POINTER(w.DWORD), w.LPWSTR, w.DWORD]
    k.GetDiskFreeSpaceExW.restype = w.BOOL
    k.GetDiskFreeSpaceExW.argtypes = [w.LPCWSTR, ctypes.POINTER(ctypes.c_ulonglong),
                                      ctypes.POINTER(ctypes.c_ulonglong), ctypes.POINTER(ctypes.c_ulonglong)]
    k.GetVolumePathNameW.restype = w.BOOL
    k.GetVolumePathNameW.argtypes = [w.LPCWSTR, w.LPWSTR, w.DWORD]
    k.GetVolumeNameForVolumeMountPointW.restype = w.BOOL
    k.GetVolumeNameForVolumeMountPointW.argtypes = [w.LPCWSTR, w.LPWSTR, w.DWORD]
    _k32 = k
    return k


def _last_error() -> int:
    import ctypes
    return ctypes.get_last_error()


class Handle:
    """Context manager owning a Win32 HANDLE. Never opened with write access."""

    def __init__(self, path: str, access: int = 0, *, flags: int = 0):
        if access & ~GENERIC_READ:
            raise ValueError("RecoverX never opens devices with anything other than read or query access")
        k = _kernel32()
        h = k.CreateFileW(path, access, FILE_SHARE_READ | FILE_SHARE_WRITE, None, OPEN_EXISTING, flags, None)
        if h is None or h == INVALID_HANDLE_VALUE or h == (1 << 64) - 1:
            raise Win32Error(f"CreateFileW({path})", _last_error())
        self.path, self.value, self.access = path, h, access

    def close(self) -> None:
        if self.value is not None:
            _kernel32().CloseHandle(self.value)
            self.value = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def ioctl(self, code: int, in_buffer: bytes | None = None, out_size: int = 4096) -> bytes:
        import ctypes
        from ctypes import wintypes as w
        k = _kernel32()
        out = ctypes.create_string_buffer(out_size)
        returned = w.DWORD()
        inbuf = ctypes.create_string_buffer(in_buffer, len(in_buffer)) if in_buffer else None
        ok = k.DeviceIoControl(self.value, code, inbuf, len(in_buffer) if in_buffer else 0, out, out_size,
                               ctypes.byref(returned), None)
        if not ok:
            raise Win32Error(f"DeviceIoControl(0x{code:08X})", _last_error())
        return out.raw[:returned.value]

    def read_at(self, offset: int, length: int) -> bytes:
        """Positioned read. Raises Win32Error with the Windows error code."""
        import ctypes
        from ctypes import wintypes as w
        if not self.access & GENERIC_READ:
            raise ValueError("handle was opened without read access")
        k = _kernel32()
        if not k.SetFilePointerEx(self.value, offset, None, 0):
            raise Win32Error("SetFilePointerEx", _last_error())
        buf = ctypes.create_string_buffer(length)
        got = w.DWORD()
        if not k.ReadFile(self.value, buf, length, ctypes.byref(got), None):
            raise Win32Error("ReadFile", _last_error())
        return buf.raw[:got.value]


def physical_drive_path(number: int) -> str:
    if not isinstance(number, int) or number < 0 or number > 1023:
        raise ValueError("invalid physical disk number")
    return rf"\\.\PhysicalDrive{number}"


@dataclass
class StorageDescriptor:
    bus_type: str
    bus_type_code: int
    removable_media: bool
    vendor: str
    product: str
    revision: str
    serial: str


def _cstr(raw: bytes, offset: int) -> str:
    if not offset or offset >= len(raw):
        return ""
    end = raw.find(b"\x00", offset)
    return raw[offset:end if end >= 0 else len(raw)].decode("ascii", errors="replace").strip()


def parse_storage_descriptor(raw: bytes) -> StorageDescriptor:
    if len(raw) < 36:
        raise ValueError("storage descriptor too short")
    (_ver, _size, _dtype, _dmod, removable, _cq, vend, prod, rev, serial, bus, _rawlen) = \
        struct.unpack_from("<IIBBBBIIIIII", raw, 0)
    return StorageDescriptor(BUS_TYPES.get(bus, f"Bus {bus}"), bus, bool(removable), _cstr(raw, vend),
                             _cstr(raw, prod), _cstr(raw, rev), _cstr(raw, serial))


def parse_disk_extents(raw: bytes) -> list[tuple[int, int, int]]:
    """VOLUME_DISK_EXTENTS → [(disk_number, starting_offset, length)]."""
    if len(raw) < 8:
        return []
    count = struct.unpack_from("<I", raw, 0)[0]
    out = []
    for i in range(count):
        pos = 8 + i * 24
        if pos + 24 > len(raw):
            break
        disk, start, length = struct.unpack_from("<I4xqq", raw, pos)
        out.append((disk, start, length))
    return out


def parse_geometry_ex(raw: bytes) -> tuple[int, int]:
    """DISK_GEOMETRY_EX → (disk_size_bytes, bytes_per_sector)."""
    if len(raw) < 32:
        raise ValueError("geometry structure too short")
    bytes_per_sector = struct.unpack_from("<I", raw, 20)[0]
    disk_size = struct.unpack_from("<q", raw, 24)[0]
    return disk_size, bytes_per_sector


def query_disk(number: int) -> dict:
    """Identity of one physical disk using zero-access (metadata-only) handles."""
    with Handle(physical_drive_path(number), 0) as h:
        dev_type, dev_number, part = struct.unpack_from("<III", h.ioctl(IOCTL_STORAGE_GET_DEVICE_NUMBER, out_size=12))
        size, sector = parse_geometry_ex(h.ioctl(IOCTL_DISK_GET_DRIVE_GEOMETRY_EX, out_size=256))
        query = struct.pack("<II4x", 0, 0)  # StorageDeviceProperty, PropertyStandardQuery
        desc = parse_storage_descriptor(h.ioctl(IOCTL_STORAGE_QUERY_PROPERTY, query, out_size=1024))
    return {"number": dev_number, "device_type": dev_type, "size": size, "sector_size": sector,
            "bus_type": desc.bus_type, "bus_type_code": desc.bus_type_code,
            "removable_media": desc.removable_media, "vendor": desc.vendor, "product": desc.product,
            "revision": desc.revision, "serial": desc.serial}


def enumerate_physical_disks(limit: int = 64) -> list[dict]:
    disks, misses = [], 0
    for n in range(limit):
        try:
            disks.append(query_disk(n))
            misses = 0
        except Win32Error as exc:
            if exc.code in (2, 3):  # not present
                misses += 1
                if misses >= 8 and n >= 8:
                    break
                continue
            disks.append({"number": n, "error": str(exc)})
    return disks


def volume_disk_extents(volume: str) -> list[tuple[int, int, int]]:
    """volume is 'E:' or '\\\\?\\Volume{GUID}\\'. Uses a zero-access handle."""
    path = volume.rstrip("\\")
    if len(path) == 2 and path[1] == ":":
        path = "\\\\.\\" + path
    elif path.startswith("\\\\?\\"):
        path = "\\\\.\\" + path[4:]
    with Handle(path, 0) as h:
        return parse_disk_extents(h.ioctl(IOCTL_VOLUME_GET_VOLUME_DISK_EXTENTS, out_size=8 + 24 * 128))


def logical_drive_letters() -> list[str]:
    mask = _kernel32().GetLogicalDrives()
    return [f"{c}:" for i, c in enumerate(string.ascii_uppercase) if mask & (1 << i)]


def volume_info(letter: str) -> dict:
    import ctypes
    from ctypes import wintypes as w
    k = _kernel32()
    root = letter.rstrip("\\") + "\\"
    info = {"letter": letter.rstrip("\\").upper(), "drive_type": DRIVE_TYPES.get(k.GetDriveTypeW(root), "unknown"),
            "label": "", "filesystem": "", "size": None, "free": None, "serial": None}
    name, fs = ctypes.create_unicode_buffer(261), ctypes.create_unicode_buffer(261)
    serial, maxlen, flags = w.DWORD(), w.DWORD(), w.DWORD()
    if k.GetVolumeInformationW(root, name, 261, ctypes.byref(serial), ctypes.byref(maxlen), ctypes.byref(flags), fs, 261):
        info.update(label=name.value, filesystem=fs.value, serial=f"{serial.value:08X}")
    free_user, total, free_total = ctypes.c_ulonglong(), ctypes.c_ulonglong(), ctypes.c_ulonglong()
    if k.GetDiskFreeSpaceExW(root, ctypes.byref(free_user), ctypes.byref(total), ctypes.byref(free_total)):
        info.update(size=total.value, free=free_user.value)
    return info


def volume_root_of(path: str) -> str:
    """Mount point that contains path (e.g. 'E:\\' or a mounted-folder path)."""
    import ctypes
    buf = ctypes.create_unicode_buffer(1024)
    if not _kernel32().GetVolumePathNameW(os.path.abspath(path), buf, 1024):
        raise Win32Error("GetVolumePathNameW", _last_error())
    return buf.value


def volume_guid_of_root(root: str) -> str | None:
    import ctypes
    buf = ctypes.create_unicode_buffer(128)
    if not _kernel32().GetVolumeNameForVolumeMountPointW(root if root.endswith("\\") else root + "\\", buf, 128):
        return None
    return buf.value


def disks_for_path(path: str) -> set[int]:
    """Physical disk numbers backing the volume that contains path. Raises if unknown."""
    root = volume_root_of(path)
    if root.startswith("\\\\") and not root.startswith("\\\\?\\"):
        raise OSError(f"{path} is on a network share; its physical disk cannot be verified")
    guid = volume_guid_of_root(root)
    target = guid or root[:2]
    extents = volume_disk_extents(target)
    if not extents:
        raise OSError(f"Windows reported no physical disk extents for {root}")
    return {d for d, _, _ in extents}


def is_admin() -> bool:
    if not IS_WINDOWS:
        return hasattr(os, "geteuid") and os.geteuid() == 0
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def open_physical_disk_read_only(number: int) -> Handle:
    """GENERIC_READ only. Requires administrator rights on Windows."""
    return Handle(physical_drive_path(number), GENERIC_READ, flags=FILE_FLAG_SEQUENTIAL_SCAN)


def disk_length(handle: Handle) -> int:
    return struct.unpack_from("<q", handle.ioctl(IOCTL_DISK_GET_LENGTH_INFO, out_size=8))[0]


def device_number(handle: Handle) -> int:
    return struct.unpack_from("<III", handle.ioctl(IOCTL_STORAGE_GET_DEVICE_NUMBER, out_size=12))[1]


def run_elevated(executable: str, params: str, directory: str, *, show: int = 7):
    """Start a process through the UAC consent prompt (ShellExecuteExW 'runas').

    Returns a process handle the caller can wait on. The user must approve the
    prompt; a declined prompt raises Win32Error(ERROR_CANCELLED).
    """
    import ctypes
    from ctypes import wintypes as w

    class SHELLEXECUTEINFOW(ctypes.Structure):
        _fields_ = [("cbSize", w.DWORD), ("fMask", ctypes.c_ulong), ("hwnd", w.HWND),
                    ("lpVerb", w.LPCWSTR), ("lpFile", w.LPCWSTR), ("lpParameters", w.LPCWSTR),
                    ("lpDirectory", w.LPCWSTR), ("nShow", ctypes.c_int), ("hInstApp", w.HINSTANCE),
                    ("lpIDList", ctypes.c_void_p), ("lpClass", w.LPCWSTR), ("hkeyClass", w.HKEY),
                    ("dwHotKey", w.DWORD), ("hIconOrMonitor", w.HANDLE), ("hProcess", w.HANDLE)]

    info = SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = 0x00000040  # SEE_MASK_NOCLOSEPROCESS
    info.lpVerb, info.lpFile, info.lpParameters, info.lpDirectory = "runas", executable, params, directory
    info.nShow = show
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(SHELLEXECUTEINFOW)]
    shell32.ShellExecuteExW.restype = w.BOOL
    if not shell32.ShellExecuteExW(ctypes.byref(info)):
        raise Win32Error("ShellExecuteExW(runas)", _last_error())
    return ElevatedProcess(info.hProcess)


class ElevatedProcess:
    def __init__(self, handle):
        self.handle = handle

    def poll(self) -> int | None:
        import ctypes
        from ctypes import wintypes as w
        k = _kernel32()
        k.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
        k.WaitForSingleObject.restype = w.DWORD
        if self.handle is None:
            return None
        if k.WaitForSingleObject(self.handle, 0) != 0:
            return None
        code = w.DWORD()
        k.GetExitCodeProcess.argtypes = [w.HANDLE, ctypes.POINTER(w.DWORD)]
        k.GetExitCodeProcess(self.handle, ctypes.byref(code))
        return int(code.value)

    def close(self):
        if self.handle is not None:
            _kernel32().CloseHandle(self.handle)
            self.handle = None
