"""USB storage discovery, drive-letter → physical-disk mapping and protection.

Sources (all read-only, no administrator rights needed):
  * Win32 IOCTLs on zero-access handles: disk number, size, sector size, bus
    type, vendor/product/serial (``win32.enumerate_physical_disks``).
  * IOCTL_VOLUME_GET_VOLUME_DISK_EXTENTS for every drive letter: the
    authoritative mapping of letters to physical disks (works for dynamic and
    spanned volumes, unlike the Storage PowerShell module).
  * Optional enrichment from the Storage CIM classes (MSFT_Disk/MSFT_Partition)
    for friendly names, IsSystem/IsBoot flags and partition offsets.

``build_inventory`` is a pure function so the safety policy is unit-testable
with synthetic inputs. A disk is selectable only if it is on a USB/SD/MMC bus,
has media, and is not protected for any reason.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import win32

SELECTABLE_BUSES = {"USB", "SD", "MMC"}

_CIM_SCRIPT = r"""
$ErrorActionPreference = 'SilentlyContinue'
$ns = 'root/Microsoft/Windows/Storage'
$disks = @(Get-CimInstance -Namespace $ns -ClassName MSFT_Disk | ForEach-Object {
  [pscustomobject]@{ Number=[int]$_.Number; FriendlyName=[string]$_.FriendlyName; BusType=[int]$_.BusType;
    Size=[int64]$_.Size; IsSystem=[bool]$_.IsSystem; IsBoot=[bool]$_.IsBoot; IsOffline=[bool]$_.IsOffline;
    IsReadOnly=[bool]$_.IsReadOnly; PartitionStyle=[int]$_.PartitionStyle; SerialNumber=[string]$_.SerialNumber;
    UniqueId=[string]$_.UniqueId; LogicalSectorSize=[int]$_.LogicalSectorSize } })
$parts = @(Get-CimInstance -Namespace $ns -ClassName MSFT_Partition | ForEach-Object {
  $l = ''; if ($_.DriveLetter -and [int][char]$_.DriveLetter -ne 0) { $l = [string]$_.DriveLetter }
  [pscustomobject]@{ DiskNumber=[int]$_.DiskNumber; PartitionNumber=[int]$_.PartitionNumber; DriveLetter=$l;
    Offset=[int64]$_.Offset; Size=[int64]$_.Size; IsSystem=[bool]$_.IsSystem; IsBoot=[bool]$_.IsBoot;
    GptType=[string]$_.GptType; MbrType=[int]$_.MbrType } })
$pagefiles = @(Get-CimInstance -ClassName Win32_PageFileUsage | ForEach-Object { [string]$_.Name })
ConvertTo-Json -Compress -Depth 4 -InputObject ([pscustomobject]@{ disks=$disks; partitions=$parts; pagefiles=$pagefiles })
"""


@dataclass
class VolumeInfo:
    letter: str
    filesystem: str = ""
    label: str = ""
    size: int | None = None
    free: int | None = None
    drive_type: str = "unknown"
    offset: int | None = None


@dataclass
class DiskInfo:
    number: int
    name: str
    bus_type: str
    size: int
    sector_size: int = 512
    serial: str = ""
    unique_id: str = ""
    vendor: str = ""
    product: str = ""
    removable_media: bool = False
    is_system: bool = False
    is_boot: bool = False
    partition_style: str = "unknown"
    volumes: list[VolumeInfo] = field(default_factory=list)
    partitions: list[dict] = field(default_factory=list)
    protected_reasons: list[str] = field(default_factory=list)
    is_usb: bool = False

    @property
    def selectable(self) -> bool:
        return self.is_usb and not self.protected_reasons

    @property
    def letters(self) -> list[str]:
        return [v.letter for v in self.volumes]

    def identity(self) -> dict:
        """Fields that must match exactly immediately before acquisition."""
        return {"number": self.number, "size": self.size, "serial": self.serial, "bus_type": self.bus_type,
                "sector_size": self.sector_size, "vendor": self.vendor, "product": self.product}

    def label(self) -> str:
        letters = ", ".join(self.letters) or "no drive letter"
        return f"{self.name} · {human_size(self.size)} · Disk {self.number} · {letters}"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["selectable"] = self.selectable
        return d


def human_size(n: int | None) -> str:
    if n is None:
        return "unknown"
    value = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1000 or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1000
    return f"{n} B"


PARTITION_STYLES = {0: "RAW", 1: "MBR", 2: "GPT"}


def protected_paths() -> list[str]:
    """Locations whose disks must never be acquisition sources."""
    paths = [os.environ.get("SystemDrive", "C:") + "\\", os.environ.get("SystemRoot", r"C:\Windows"),
             os.environ.get("ProgramFiles", r"C:\Program Files"), sys.executable, sys.prefix,
             str(Path(__file__).resolve()), os.environ.get("LOCALAPPDATA", ""), os.environ.get("TEMP", "")]
    home = os.environ.get("RECOVERX_HOME")
    if home:
        paths.append(home)
    return [p for p in paths if p]


def build_inventory(raw_disks: list[dict], letter_extents: dict[str, list[tuple[int, int, int]]],
                    volumes: dict[str, dict], cim: dict | None,
                    protected_disk_numbers: dict[int, list[str]]) -> list[DiskInfo]:
    """Combine raw facts into DiskInfo records and apply the protection policy.

    protected_disk_numbers maps disk number → reasons (system drive, Windows
    folder, page file, RecoverX installation/workspace, …).
    """
    cim = cim or {}
    cim_disks = {int(d.get("Number", -1)): d for d in cim.get("disks") or [] if isinstance(d, dict)}
    cim_parts: dict[int, list[dict]] = {}
    for p in cim.get("partitions") or []:
        if isinstance(p, dict):
            cim_parts.setdefault(int(p.get("DiskNumber", -1)), []).append(p)
    out: list[DiskInfo] = []
    for raw in raw_disks:
        n = raw.get("number")
        if not isinstance(n, int):
            continue
        if raw.get("error"):
            out.append(DiskInfo(n, f"Disk {n}", "Unknown", 0, protected_reasons=[f"Cannot query disk: {raw['error']}"]))
            continue
        c = cim_disks.get(n, {})
        bus = raw.get("bus_type") or win32.BUS_TYPES.get(int(c.get("BusType", 0) or 0), "Unknown")
        name = (c.get("FriendlyName") or " ".join(x for x in (raw.get("vendor"), raw.get("product")) if x)
                or f"Disk {n}").strip()
        info = DiskInfo(number=n, name=name, bus_type=bus, size=int(raw.get("size") or 0),
                        sector_size=int(raw.get("sector_size") or c.get("LogicalSectorSize") or 512),
                        serial=(raw.get("serial") or c.get("SerialNumber") or "").strip(),
                        unique_id=c.get("UniqueId") or "", vendor=raw.get("vendor") or "",
                        product=raw.get("product") or "", removable_media=bool(raw.get("removable_media")),
                        is_system=bool(c.get("IsSystem")), is_boot=bool(c.get("IsBoot")),
                        partition_style=PARTITION_STYLES.get(int(c.get("PartitionStyle", -1) or 0), "unknown")
                        if c else "unknown")
        info.is_usb = bus in SELECTABLE_BUSES
        for letter, extents in sorted(letter_extents.items()):
            for disk, start, _length in extents:
                if disk == n:
                    v = volumes.get(letter, {})
                    info.volumes.append(VolumeInfo(letter=letter, filesystem=v.get("filesystem") or "",
                                                   label=v.get("label") or "", size=v.get("size"),
                                                   free=v.get("free"), drive_type=v.get("drive_type") or "unknown",
                                                   offset=start))
                    break
        for p in sorted(cim_parts.get(n, []), key=lambda x: int(x.get("Offset") or 0)):
            info.partitions.append({"number": int(p.get("PartitionNumber") or 0), "offset": int(p.get("Offset") or 0),
                                    "size": int(p.get("Size") or 0), "letter": p.get("DriveLetter") or "",
                                    "is_system": bool(p.get("IsSystem")), "is_boot": bool(p.get("IsBoot")),
                                    "gpt_type": p.get("GptType") or "", "mbr_type": int(p.get("MbrType") or 0)})
            if p.get("IsSystem") or p.get("IsBoot"):
                info.is_system = info.is_system or bool(p.get("IsSystem"))
                info.is_boot = info.is_boot or bool(p.get("IsBoot"))
        if not info.partitions:
            info.partitions = [{"number": i + 1, "offset": v.offset, "size": v.size, "letter": v.letter}
                               for i, v in enumerate(sorted(info.volumes, key=lambda v: v.offset or 0))]
        reasons = info.protected_reasons
        if info.is_system:
            reasons.append("Windows system disk (contains the EFI/system partition)")
        if info.is_boot:
            reasons.append("Windows boot disk")
        reasons.extend(r for r in protected_disk_numbers.get(n, []) if r not in reasons)
        if not info.is_usb:
            reasons.append(f"Not a removable USB device (bus: {bus}) — internal and other storage is protected")
        if info.size <= 0:
            reasons.append("No media present or size unavailable")
        out.append(info)
    return sorted(out, key=lambda d: (not d.selectable, not d.is_usb, d.number))


def _cim_snapshot(timeout: float = 25) -> dict | None:
    try:
        r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                            "-Command", _CIM_SCRIPT], capture_output=True, text=True, timeout=timeout,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if r.returncode != 0 or not r.stdout.strip():
            return None
        data = json.loads(r.stdout)
        return data if isinstance(data, dict) else None
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return None


def _protected_disk_map(letter_extents, extra_paths=()) -> dict[int, list[str]]:
    reasons: dict[int, list[str]] = {}
    labels = {
        (os.environ.get("SystemDrive", "C:") + "\\"): "Hosts the Windows system drive",
        os.environ.get("SystemRoot", r"C:\Windows"): "Hosts the Windows folder",
        sys.executable: "Hosts the running Python/RecoverX installation",
        str(Path(__file__).resolve()): "Hosts the RecoverX program files",
    }
    for p in protected_paths():
        labels.setdefault(p, "Hosts RecoverX workspace or temporary files")
    for p in extra_paths:
        labels.setdefault(str(p), "Hosts the selected output folder")
    for path, why in labels.items():
        try:
            for d in win32.disks_for_path(path):
                reasons.setdefault(d, [])
                if why not in reasons[d]:
                    reasons[d].append(why)
        except OSError:
            continue
    return reasons


def list_devices(*, extra_protected_paths=(), include_cim: bool = True) -> list[DiskInfo]:
    """Live device inventory. Windows only; raises OSError elsewhere."""
    if not win32.IS_WINDOWS:
        raise OSError("USB device discovery is implemented for Windows. On Linux use the unmounted-device capture.")
    raw = win32.enumerate_physical_disks()
    letters = win32.logical_drive_letters()
    extents, volumes = {}, {}
    for letter in letters:
        try:
            info = win32.volume_info(letter)
        except OSError:
            continue
        if info["drive_type"] in ("network", "cdrom", "no_root"):
            continue
        volumes[letter] = info
        try:
            extents[letter] = win32.volume_disk_extents(letter)
        except OSError:
            continue
    cim = _cim_snapshot() if include_cim else None
    protected = _protected_disk_map(extents, extra_protected_paths)
    for pf in (cim or {}).get("pagefiles") or []:
        try:
            for d in win32.disks_for_path(str(pf)):
                protected.setdefault(d, []).append("Hosts a Windows page file")
        except OSError:
            pass
    return build_inventory(raw, extents, volumes, cim, protected)


def find_disk(number: int, devices: list[DiskInfo]) -> DiskInfo | None:
    return next((d for d in devices if d.number == number), None)


def identity_mismatch(expected: dict, current: DiskInfo | None) -> str | None:
    """Return a human-readable reason when the live disk is not the confirmed one."""
    if current is None:
        return "The selected disk is no longer connected. Refresh the device list."
    live = current.identity()
    for key in ("number", "size", "serial", "bus_type", "sector_size", "vendor", "product"):
        if str(expected.get(key, "")) != str(live.get(key, "")):
            return (f"Disk identity changed ({key}: confirmed {expected.get(key)!r}, now {live.get(key)!r}). "
                    "Windows may have renumbered disks. Refresh and confirm again.")
    if not current.selectable:
        return "The disk is now protected: " + "; ".join(current.protected_reasons)
    return None
