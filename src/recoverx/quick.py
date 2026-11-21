"""Safe, repeatable, single-action recovery workflow for local disk images.

No writes to the evidence: case metadata and outputs are saved separately.
The selected strategy is executed by the same tested orchestrator as the
advanced UI, preserving hash checks and event logs.
"""
from __future__ import annotations

from pathlib import Path

from .forensic.case_store import create_case, open_case
from .ml.selector import latest_model_dir
from .config import get_settings
from .recovery.orchestrator import run_recovery


def guided_recovery(*, image_path: str | None = None, case_id: str | None = None,
                    authorized: bool = False, label: str = '', examiner: str = '',
                    method: str = 'cart', progress=None) -> tuple[dict, dict]:
    """Create/open a case, analyze evidence, recover and save results.

    Returns (latest case record, run). A new image requires explicit
    authorization confirmation. Existing cases retain their original hash.
    """
    if bool(image_path) == bool(case_id):
        raise ValueError('Supply exactly one: image_path OR case_id')
    if image_path:
        if not authorized:
            raise ValueError('Authorization confirmation is required for new evidence.')
        case, _ = create_case(image_path, label=label or Path(image_path).stem,
                              examiner=examiner, notes='Created by Quick Recovery')
    else:
        case = open_case(str(case_id))
    if method not in ('cart', 'rule', 'tsk', 'photorec', 'combined', 'smart'):
        raise ValueError('Invalid quick recovery method')
    run = run_recovery(case, method, model_dir=latest_model_dir(get_settings().models_dir),
                       analyze=True, progress=progress, conservative=method != 'smart')
    return case.load(), run
