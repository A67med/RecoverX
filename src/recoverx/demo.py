"""Generate one locally controlled FAT16 test image for a safe product demo.

No real removable media, disks, or user documents are touched. The synthetic
image is stored under the RecoverX workspace, never over an existing dataset.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

from .config import get_settings
from .datasets.generator import generate_dataset, ground_truth_for, validate_dataset
from .forensic.case_store import Case, create_case


def create_demo_case(*, progress=None) -> tuple[Case, dict]:
    root = get_settings().ensure().datasets_dir / f"demo-{uuid.uuid4().hex[:10]}"
    # FAT16 uses userspace tools, avoiding root/loop mounts.
    try:
        dataset = generate_dataset(root, seeds=range(1), filesystems=("fat16",),
                                   scenarios=("delete",), sizes_mb=(48,),
                                   progress=progress or (lambda _line: None))
        problems = validate_dataset(root)
        if problems:
            raise RuntimeError("Demo dataset validation failed: " + "; ".join(problems))
        image_entry = dataset["images"][0]
        image = root / image_entry["image_file"]
        gt = root / f"gt_{image_entry['image_id']}.json"
        gt.write_text(json.dumps(ground_truth_for(image_entry), indent=2))
        case, rec = create_case(image, label="Safe demo - FAT16 deleted files",
                                notes="Synthetic demo image generated locally by RecoverX.",
                                examiner="RecoverX demo")
        rec["demo_ground_truth_path"] = str(gt)
        rec["demo_dataset_dir"] = str(root)
        case.save(rec)
        case.event("demo_case_created", ground_truth=str(gt), dataset=str(root))
        return case, rec
    except Exception:
        # Never delete partially generated evidence silently; leave it for inspection.
        raise
