"""Central paths and settings. Override the data root with RECOVERX_HOME."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    home: Path

    @property
    def cases_dir(self) -> Path:
        return self.home / "cases"

    @property
    def datasets_dir(self) -> Path:
        return self.home / "datasets"

    @property
    def models_dir(self) -> Path:
        return self.home / "models"

    @property
    def experiments_dir(self) -> Path:
        return self.home / "experiments"

    def ensure(self) -> "Settings":
        for p in (self.cases_dir, self.datasets_dir, self.models_dir, self.experiments_dir):
            p.mkdir(parents=True, exist_ok=True)
        return self


def get_settings() -> Settings:
    home = Path(os.environ.get("RECOVERX_HOME", PROJECT_ROOT / "workspace")).resolve()
    return Settings(home=home)


# Default engine timeouts (seconds). Configurable per call.
TSK_TIMEOUT = int(os.environ.get("RECOVERX_TSK_TIMEOUT", "600"))
PHOTOREC_TIMEOUT = int(os.environ.get("RECOVERX_PHOTOREC_TIMEOUT", "1800"))
