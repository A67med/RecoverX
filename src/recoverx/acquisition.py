"""Opt-in read-only image capture of an unmounted non-system Linux device.

Capture uses the exact OS block device selected by the examiner, with a
separate destination on the analysis machine. This is not a write blocker or
an evidentiary chain-of-custody certification. Never auto-unmount or format.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from uuid import uuid4

from .config import get_settings


class AcquisitionError(Exception):
    pass


def _mounted(node: dict) -> bool:
    return bool(node.get('mountpoint')) or any(bool(p) for p in (node.get('mountpoints') or []))


def parse_candidates(payload: dict) -> list[dict]:
    """Exclude whole system disks when *any* descendant is mounted.

    Only unmounted whole disks and their unmounted partitions are candidates;
    this deliberately also excludes removable media currently mounted by a
    file manager. Device selection requires explicit user review.
    """
    out = []

    def has_mount(node):
        return _mounted(node) or any(has_mount(c) for c in node.get('children') or [])

    for disk in payload.get('blockdevices') or []:
        if disk.get('type') != 'disk' or has_mount(disk):
            continue
        if not str(disk.get('path', '')).startswith('/dev/'):
            continue
        # Prefer selecting a filesystem partition over the parent disk;
        # full-disk capture remains an explicit option when relevant.
        nodes = list(disk.get('children') or []) + [disk]
        for item in nodes:
            if item.get('type') not in ('disk', 'part') or _mounted(item):
                continue
            path = item.get('path')
            size = int(item.get('size') or 0)
            if path and str(path).startswith('/dev/') and size > 0:
                out.append({'path': str(path), 'size': size, 'type': item['type'],
                            'fstype': item.get('fstype') or 'unknown'})
    return out


def candidate_devices() -> list[dict]:
    if os.name != 'posix':
        raise AcquisitionError('Device capture is only supported on Linux.')
    p = subprocess.run(['lsblk', '--json', '--bytes', '-p',
                        '-o', 'PATH,NAME,TYPE,SIZE,FSTYPE,MOUNTPOINTS'],
                       capture_output=True, text=True, timeout=15)
    if p.returncode:
        raise AcquisitionError(f'Cannot inspect local disks: {p.stderr.strip()}')
    return parse_candidates(json.loads(p.stdout))


def capture_device(device: str) -> Path:
    """Require GUI privilege elevation; read source and write a new .img only.

    Checks candidates immediately before launching the privileged read.
    No shell is involved, no automount, no formatting, no device writes.
    """
    selected = next((c for c in candidate_devices() if c['path'] == device), None)
    if selected is None:
        raise AcquisitionError('Device is no longer a safe, unmounted non-system candidate. Refresh the list.')
    pkexec = shutil.which('pkexec')
    if not pkexec:
        raise AcquisitionError('pkexec (polkit) is not available. Install policykit-1 to use GUI device capture.')
    dest_dir = get_settings().ensure().home / 'real-evidence'
    dest_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    dest_dir.chmod(0o700)
    if shutil.disk_usage(dest_dir).free < selected['size'] + 64 * 1024 * 1024:
        raise AcquisitionError('Not enough free space for this disk image and a 64 MiB safety margin.')
    stem = Path(device).name.replace('/', '_')
    name = f'{stem}-{time.strftime("%Y%m%d-%H%M%S")}-{uuid4().hex[:6]}.img'
    dest = dest_dir / name
    command = [pkexec, '/usr/bin/dd', f'if={device}', f'of={dest}', 'bs=4M',
               'iflag=fullblock', 'conv=excl,fsync', 'status=none']
    try:
        result = subprocess.run(command, capture_output=True, text=True,
                                timeout=3600, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        if dest.exists():
            dest.unlink()
        raise AcquisitionError(f'Image capture failed: {exc}') from exc
    if result.returncode != 0:
        if dest.exists():
            dest.unlink()
        raise AcquisitionError(f'Capture cancelled or failed: {result.stderr.strip()[:350]}')
    if not dest.is_file() or dest.stat().st_size != selected['size']:
        raise AcquisitionError('Output size differs from selected device size; do not use this incomplete image.')
    # Some polkit environments use a restrictive umask for root-created files.
    # Make the image readable by the unprivileged forensic app if needed;
    # the destination directory itself is private to the logged-in user.
    if not os.access(dest, os.R_OK):
        grant = subprocess.run([pkexec, '/usr/bin/chmod', '0644', str(dest)],
                               capture_output=True, text=True, timeout=120)
        if grant.returncode != 0 or not os.access(dest, os.R_OK):
            raise AcquisitionError('Image copied, but cannot be read without a separate administrator permission change: '
                                   + str(dest))
    return dest
