"""Launch with:  streamlit run app.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from recoverx.ui.dashboard import main  # noqa: E402

main()
