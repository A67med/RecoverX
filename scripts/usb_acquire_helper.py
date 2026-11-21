#!/usr/bin/env python3
"""Entry point for the elevated RecoverX acquisition worker.

Started only by RecoverX through the Windows UAC prompt, with ``python -I`` so
the current directory and user site-packages cannot inject modules.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from recoverx.usb.helper import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
