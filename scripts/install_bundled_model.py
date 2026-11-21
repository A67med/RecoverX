#!/usr/bin/env python3
"""Install the locally bundled trained CART model (no training required)."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from recoverx.ml.model_install import install_bundled_model

if __name__ == '__main__':
    print(f'Active CART model: {install_bundled_model()}')
