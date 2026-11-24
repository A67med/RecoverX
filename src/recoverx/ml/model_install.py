"""Evaluate the bundled synthetic records and activate a JSON CART model."""
from pathlib import Path

from ..config import PROJECT_ROOT, get_settings
from ..exceptions import ModelError
from ..forensic.storage import operation_lock
from .evaluation import evaluate_records
from .selector import CartSelector


def bundled_model_dir() -> Path | None:
    records = PROJECT_ROOT / "research" / "results" / "exp1"
    return records if (records / "features.jsonl").is_file() else None


def install_bundled_model() -> Path:
    records = bundled_model_dir()
    if records is None:
        raise ModelError("Bundled evaluation records are missing")
    models = get_settings().ensure().models_dir
    version = "cart-20261121-v030"
    target = models / version
    with operation_lock(models, ".model-install.lock"):
        if not target.exists():
            model, _ = evaluate_records(records, PROJECT_ROOT / "research/datasets/dataset_v1/manifest.json")
            model.save(models, version)
        CartSelector.load(target)
    return target
