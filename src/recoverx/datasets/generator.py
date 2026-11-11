"""Controlled ground-truth corpus generator (spec §8).

Builds small raw disk images with known files, deletes some of them, and records
what was *observed* (physical extents, fragmentation, overwrite overlap) rather
than what was intended.

Filesystems / procedures (documented limitations):
  * ext4  — files written, deleted and overwritten through the real Linux kernel
            via a loop mount. Extents measured with `filefrag -v` before deletion.
  * fat16 / fat32 — this environment's kernel has no vfat driver, so FAT images
            are manipulated with mtools (userspace FAT implementation: mcopy/mdel).
            Extents measured with TSK `istat` before deletion. mtools deletion is
            not identical to Windows or Linux-kernel FAT deletion.
Scenarios:
  delete      — N files written, ~40% deleted.
  overwrite   — as delete, then new random files written after deletion; the
                overlap between their extents and each target's old extents is
                measured (overwritten_fraction).
  format      — files written, some deleted, then the filesystem is recreated
                with mkfs (quick format; data blocks untouched, metadata lost).
                Every user file becomes a target.
  fragmented  — keeper/spacer files alternated, remaining free space filled,
                spacers deleted, targets written into the holes and then
                deleted. Fragmentation is only claimed where extents show >1 run.
Source file *contents* are deterministic per seed; image bytes are not
byte-identical across regenerations (timestamps, volume IDs)."""
from __future__ import annotations

import errno
import io
import json
import os
import random
import re
import shutil
import subprocess
import tempfile
import zipfile
from contextlib import contextmanager
from pathlib import Path

from PIL import Image

from ..forensic.hashing import sha256_bytes, sha256_file

GENERATOR_VERSION = "1.0"
FILESYSTEMS = ("fat16", "fat32", "ext4")
SCENARIOS = ("delete", "overwrite", "format", "fragmented")
FILE_TYPES = ("png", "jpg", "pdf", "txt", "zip")
WORDS = ("forensic evidence cluster sector inode metadata carve recover hash allocate journal "
         "partition volume signature header footer fragment timestamp examiner custody").split()


def _run(args: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(args, check=True, capture_output=True, text=True, **kw)


# ---------------------------------------------------------------- content
def make_content(ftype: str, size: int, rng: random.Random) -> bytes:
    if ftype in ("png", "jpg", "pdf"):
        bpp = {"png": 3.0, "jpg": 1.6, "pdf": 1.6}[ftype]
        w = max(16, int((size / bpp) ** 0.5))
        h = max(16, int(size / bpp / w))
        img = Image.frombytes("RGB", (w, h), rng.randbytes(w * h * 3))
        buf = io.BytesIO()
        fmt = {"png": "PNG", "jpg": "JPEG", "pdf": "PDF"}[ftype]
        kw = {"quality": 90} if ftype in ("jpg", "pdf") else {}
        if ftype == "pdf":
            from datetime import datetime, timezone
            kw.update(creationDate=datetime(2024, 1, 1, tzinfo=timezone.utc).timetuple(),
                      modDate=datetime(2024, 1, 1, tzinfo=timezone.utc).timetuple())
        img.save(buf, format=fmt, **kw)
        return buf.getvalue()
    if ftype == "txt":
        lines, total = [], 0
        while total < size:
            line = " ".join(rng.choice(WORDS) for _ in range(rng.randint(6, 14))) + f" {rng.getrandbits(32):08x}\n"
            lines.append(line)
            total += len(line)
        return "".join(lines).encode()
    if ftype == "zip":
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as z:
            for i in range(rng.randint(1, 4)):
                info = zipfile.ZipInfo(f"member{i}.bin", date_time=(2024, 1, 1, 0, 0, 0))
                z.writestr(info, rng.randbytes(max(1024, size // 3)))
        return buf.getvalue()
    if ftype == "bin":
        return rng.randbytes(size)
    raise ValueError(ftype)


def merge_ranges(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    out: list[list[int]] = []
    for off, ln in sorted(ranges):
        if out and off <= out[-1][0] + out[-1][1]:
            out[-1][1] = max(out[-1][1], off + ln - out[-1][0])
        else:
            out.append([off, ln])
    return [(a, b) for a, b in out]


def overlap_bytes(a: list[tuple[int, int]], b: list[tuple[int, int]]) -> int:
    tot = 0
    for ao, al in a:
        for bo, bl in b:
            tot += max(0, min(ao + al, bo + bl) - max(ao, bo))
    return tot


# ---------------------------------------------------------------- builders
class FatImage:
    """FAT image manipulated with mtools (no mount)."""

    def __init__(self, path: Path, fs: str, size_mb: int, tmp: Path):
        self.path, self.fs, self.size_mb, self.tmp = path, fs, size_mb, tmp

    def create(self):
        with open(self.path, "xb") as f:
            f.truncate(self.size_mb * 2**20)
        self._mkfs()

    def _mkfs(self):
        _run(["mkfs.vfat", "-F", "16" if self.fs == "fat16" else "32", str(self.path)])

    def reformat(self):
        self._mkfs()

    @contextmanager
    def session(self):
        yield self

    def write(self, name: str, data: bytes) -> bool:
        src = self.tmp / name
        src.write_bytes(data)
        r = subprocess.run(["mcopy", "-o", "-i", str(self.path), str(src), f"::{name}"],
                           capture_output=True, text=True)
        src.unlink()
        if r.returncode != 0:
            subprocess.run(["mdel", "-i", str(self.path), f"::{name}"], capture_output=True)
            return False
        return True

    def delete(self, name: str):
        _run(["mdel", "-i", str(self.path), f"::{name}"])

    def extents(self, name: str) -> list[tuple[int, int]]:
        out = _run(["fls", "-p", str(self.path)]).stdout
        m = re.search(rf"^r/r (\d+):\t{re.escape(name)}$", out, re.M)
        if not m:
            raise RuntimeError(f"{name} not found by fls")
        ist = _run(["istat", str(self.path), m.group(1)]).stdout
        # istat pads the final cluster with "0" placeholders; sector 0 is the boot
        # sector and never part of file data, so it is dropped.
        sectors = [int(x) for x in re.findall(r"\d+", ist.split("Sectors:", 1)[1]) if int(x) > 0]
        return merge_ranges([(s * 512, 512) for s in sectors])


class Ext4Image:
    """ext4 image manipulated through the kernel via a loop mount."""

    def __init__(self, path: Path, fs: str, size_mb: int, tmp: Path):
        self.path, self.fs, self.size_mb, self.tmp = path, fs, size_mb, tmp
        self.mnt = tmp / "mnt"
        self.mnt.mkdir(exist_ok=True)

    def create(self):
        with open(self.path, "xb") as f:
            f.truncate(self.size_mb * 2**20)
        self._mkfs()

    def _mkfs(self):
        # -m 0: no root-reserved blocks (the generator runs as root, reserved
        # blocks would otherwise silently absorb writes); nodiscard keeps old data
        _run(["mkfs.ext4", "-q", "-F", "-m", "0", "-E", "nodiscard", str(self.path)])

    def reformat(self):
        self._mkfs()

    @contextmanager
    def session(self):
        _run(["mount", "-o", "loop", str(self.path), str(self.mnt)])
        try:
            if not os.path.ismount(self.mnt):
                raise RuntimeError("loop mount did not take effect; refusing to write")
            yield self
        finally:
            subprocess.run(["sync"])
            _run(["umount", str(self.mnt)])

    def _target(self, name: str) -> Path:
        if not os.path.ismount(self.mnt):  # hard guard: never write onto the host disk
            raise RuntimeError("image not mounted; refusing to write")
        if "/" in name or name.startswith("."):
            raise ValueError(name)
        return self.mnt / name

    def write(self, name: str, data: bytes) -> bool:
        p = self._target(name)
        try:
            with open(p, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            return True
        except OSError as e:
            if e.errno != errno.ENOSPC:
                raise
            p.unlink(missing_ok=True)
            return False

    def delete(self, name: str):
        self._target(name).unlink()
        subprocess.run(["sync"])

    def extents(self, name: str) -> list[tuple[int, int]]:
        out = _run(["filefrag", "-v", str(self._target(name))]).stdout
        bs = int(re.search(r"blocks? of (\d+) bytes", out).group(1))
        ranges = []
        for m in re.finditer(r"^\s*\d+:\s+\d+\.\.\s*\d+:\s+(\d+)\.\.\s*(\d+):", out, re.M):
            a, b = int(m.group(1)), int(m.group(2))
            ranges.append((a * bs, (b - a + 1) * bs))
        return merge_ranges(ranges)


def _builder(fs: str, path: Path, size_mb: int, tmp: Path):
    return (Ext4Image if fs == "ext4" else FatImage)(path, fs, size_mb, tmp)


# ---------------------------------------------------------------- scenarios
def _file_plan(rng: random.Random, n: int, small: bool = False) -> list[tuple[str, int]]:
    plan = []
    for _ in range(n):
        t = rng.choice(FILE_TYPES)
        band = rng.choices(["s", "m", "l"], weights=[4, 4, 2 if not small else 0])[0]
        size = {"s": rng.randint(8_000, 64_000), "m": rng.randint(64_000, 400_000),
                "l": rng.randint(400_000, 1_500_000)}[band]
        plan.append((t, size))
    return plan


def _fill(b, rng, prefix: str, cap: int) -> list[dict]:
    """Fill free space with allocated filler files until the FS reports full.
    Bounded by `cap` bytes total so a misconfiguration can never fill the host."""
    written, out, chunk, i = 0, [], 4 * 2**20, 0
    while chunk >= 512 and written < cap:
        name = f"{prefix}{i:03d}.bin"
        data = make_content("bin", min(chunk, cap - written), rng)
        if b.write(name, data):
            out.append({"name": name, "sha256": sha256_bytes(data), "size": len(data)})
            written += len(data)
            i += 1
        else:
            chunk //= 4
    return out


def build_image(out_dir: Path, image_id: str, fs: str, scenario: str, seed: int, size_mb: int,
                split: str, tmp_root: Path) -> dict:
    from ..forensic.image_validator import safe_identifier
    safe_identifier(image_id)
    if fs not in FILESYSTEMS or scenario not in SCENARIOS or not 8 <= size_mb <= 4096:
        raise ValueError("Unsupported synthetic image configuration")
    if (out_dir / "images" / f"{image_id}.img").exists() or (out_dir / "reference" / image_id).exists():
        raise FileExistsError("Refusing to overwrite an existing synthetic image or its reference data")
    rng = random.Random(f"{image_id}|{seed}")
    img_path = out_dir / "images" / f"{image_id}.img"
    ref_dir = out_dir / "reference" / image_id
    ref_dir.mkdir(parents=True, exist_ok=True)
    img_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(dir=tmp_root))
    b = _builder(fs, img_path, size_mb, tmp)
    b.create()

    files: dict[str, dict] = {}       # name -> record
    targets: list[str] = []
    overwriters: list[str] = []
    procedure: list[str] = []
    seen_hashes: set[str] = set()

    def add(name: str, ftype: str, size: int) -> bool:
        data = make_content(ftype, size, rng)
        h = sha256_bytes(data)
        if h in seen_hashes:
            return False
        if not b.write(name, data):
            return False
        seen_hashes.add(h)
        files[name] = {"name": name, "type": ftype, "size": len(data), "sha256": h, "_data": data}
        return True

    with b.session():
        if scenario in ("delete", "overwrite", "format"):
            plan = _file_plan(rng, rng.randint(10, 18))
            for i, (t, s) in enumerate(plan):
                add(f"f{i:02d}.{t}", t, s)
            names = list(files)
            k = max(2, round(len(names) * (0.3 if scenario == "format" else 0.4)))
            chosen = rng.sample(names, k)
            for n in chosen:
                files[n]["extents"] = b.extents(n)
            for n in chosen:
                b.delete(n)
            targets = chosen
            procedure.append(f"wrote {len(names)} files; deleted {k}")
            if scenario == "overwrite":
                del_bytes = sum(files[n]["size"] for n in chosen)
                budget = int(del_bytes * rng.uniform(0.3, 0.7))
                j = 0
                while budget > 0:
                    sz = min(budget, rng.randint(20_000, 300_000))
                    nm = f"new{j:02d}.bin"
                    if not add(nm, "bin", sz):
                        break
                    overwriters.append(nm)
                    budget -= sz
                    j += 1
                procedure.append(f"wrote {len(overwriters)} random files ({sum(files[n]['size'] for n in overwriters)} B) after deletion")
                for n in overwriters:
                    files[n]["extents"] = b.extents(n)
        elif scenario == "fragmented":
            n_pairs = rng.randint(6, 10)
            spacers = []
            for i in range(n_pairs):
                t = rng.choice(FILE_TYPES)
                add(f"keep{i:02d}.{t}", t, rng.randint(20_000, 80_000))
                sp = f"sp{i:02d}.bin"
                if add(sp, "bin", rng.randint(48_000, 96_000)):
                    spacers.append(sp)
            filler = _fill(b, rng, "fill", cap=size_mb * 2**20)
            for fr in filler:
                files[fr["name"]] = {**fr, "type": "bin"}
            for sp in spacers:
                b.delete(sp)
                files.pop(sp)
            hole = sum(1 for _ in spacers)
            procedure.append(f"{n_pairs} keeper/spacer pairs, {len(filler)} filler files, {hole} spacers deleted")
            for i in range(rng.randint(2, 3)):
                t = rng.choice(["png", "jpg", "pdf", "zip", "txt"])
                if add(f"tgt{i:02d}.{t}", t, rng.randint(110_000, 200_000)):
                    targets.append(f"tgt{i:02d}.{t}")
            for n in targets:
                files[n]["extents"] = b.extents(n)
            for n in targets:
                b.delete(n)
            procedure.append(f"wrote {len(targets)} targets into holes, then deleted them")
        else:
            raise ValueError(scenario)

    if scenario == "format":
        b.reformat()
        procedure.append("recreated filesystem with mkfs (quick format)")
        targets = [n for n in files]

    # observed conditions
    deleted = []
    for n in targets:
        r = files[n]
        ext = r.get("extents")
        ow = None
        if overwriters and ext:
            new_ext = merge_ranges([e for o in overwriters for e in files[o]["extents"]])
            ow = round(overlap_bytes(ext, new_ext) / max(1, sum(l for _, l in ext)), 4)
        (ref_dir / n).write_bytes(r["_data"])
        deleted.append({"id": f"{image_id}/{n}", "name": n, "type": r["type"], "size": r["size"],
                        "sha256": r["sha256"], "extents": ext,
                        "fragments": len(ext) if ext else None,
                        "fragmented": (len(ext) > 1) if ext else None,
                        "overwritten_fraction": ow})
    allocated = [] if scenario == "format" else [
        {"name": n, "sha256": r["sha256"], "size": r["size"]} for n, r in files.items() if n not in targets]
    shutil.rmtree(tmp, ignore_errors=True)
    return {
        "image_id": image_id, "image_file": str(img_path.relative_to(out_dir)), "fs": fs,
        "scenario": scenario, "seed": seed, "split": split, "size_mb": size_mb,
        "image_sha256": sha256_file(img_path), "generator_version": GENERATOR_VERSION,
        "procedure": procedure,
        "deletion_tool": "linux-kernel (loop mount)" if fs == "ext4" else "mtools (mdel)",
        "deleted": deleted, "allocated": allocated,
        "observed": {
            "n_targets": len(deleted),
            "n_fragmented_targets": sum(1 for d in deleted if d["fragmented"]),
            "n_overwritten_targets": sum(1 for d in deleted if (d["overwritten_fraction"] or 0) > 0),
        },
        "provenance": "custom synthetic/controlled image generated by RecoverX (not a public corpus)",
    }


SPLITS = {"train": range(0, 5), "val": range(5, 6), "test": range(6, 8)}


def split_of(seed: int) -> str:
    for s, r in SPLITS.items():
        if seed in r:
            return s
    raise ValueError(seed)


def generate_dataset(out_dir: Path, *, seeds=range(8), filesystems=FILESYSTEMS, scenarios=SCENARIOS,
                     sizes_mb=(48, 96), progress=print) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp_root = out_dir / "_tmp"
    tmp_root.mkdir(exist_ok=True)
    manifests = []
    for seed in seeds:
        for fs in filesystems:
            for sc in scenarios:
                image_id = f"{fs}-{sc}-s{seed}"
                size = random.Random(f"size|{image_id}").choice(sizes_mb)
                m = build_image(out_dir, image_id, fs, sc, seed, size, split_of(seed), tmp_root)
                manifests.append(m)
                progress(f"{image_id}: {m['observed']}")
    shutil.rmtree(tmp_root, ignore_errors=True)
    ds = {"dataset_version": GENERATOR_VERSION, "splits": {k: list(v) for k, v in SPLITS.items()},
          "images": manifests}
    (out_dir / "manifest.json").write_text(json.dumps(ds, indent=1))
    return ds


def validate_dataset(out_dir: Path, rehash_images: bool = True) -> list[str]:
    """Independent manifest validation. Returns a list of problems (empty = valid)."""
    problems = []
    ds = json.loads((out_dir / "manifest.json").read_text())
    ids, split_by_id = set(), {}
    for m in ds["images"]:
        iid = m["image_id"]
        if iid in ids:
            problems.append(f"duplicate image id {iid}")
        ids.add(iid)
        split_by_id[iid] = m["split"]
        if m["split"] != split_of(m["seed"]):
            problems.append(f"{iid}: split does not match seed")
        img = out_dir / m["image_file"]
        if not img.exists():
            problems.append(f"{iid}: image missing")
        elif rehash_images and sha256_file(img) != m["image_sha256"]:
            problems.append(f"{iid}: image hash mismatch")
        hashes = [d["sha256"] for d in m["deleted"]]
        if len(set(hashes)) != len(hashes):
            problems.append(f"{iid}: duplicate ground-truth contents")
        if set(hashes) & {a["sha256"] for a in m["allocated"]}:
            problems.append(f"{iid}: target content also allocated")
        for d in m["deleted"]:
            ref = out_dir / "reference" / iid / d["name"]
            if not ref.exists() or sha256_file(ref) != d["sha256"]:
                problems.append(f"{iid}: reference file mismatch {d['name']}")
    seeds_per_split: dict[str, set] = {}
    for m in ds["images"]:
        seeds_per_split.setdefault(m["split"], set()).add(m["seed"])
    splits = list(seeds_per_split.values())
    for i in range(len(splits)):
        for j in range(i + 1, len(splits)):
            if splits[i] & splits[j]:
                problems.append("seed shared across splits")
    return problems


def ground_truth_for(manifest_entry: dict) -> dict:
    return {"deleted": [{"id": d["id"], "sha256": d["sha256"]} for d in manifest_entry["deleted"]],
            "allocated": [{"sha256": a["sha256"]} for a in manifest_entry["allocated"]]}
