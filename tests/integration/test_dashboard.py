"""Render every dashboard page headlessly with Streamlit's AppTest and assert no
exception. Runs against an empty home (fresh install) — pages must show
'Not yet measured' states, not fake data."""
from pathlib import Path

import pytest

st_testing = pytest.importorskip("streamlit.testing.v1")
APP = str(Path(__file__).resolve().parents[2] / "app.py")
PAGES = ["Overview", "Case Management", "Forensic Analysis", "Intelligent Recovery", "Recovered Files",
         "Model Training", "Benchmark Laboratory", "Evidence & Audit", "Settings & Diagnostics"]


@pytest.mark.parametrize("page", PAGES)
def test_page_renders_on_empty_install(page):
    at = st_testing.AppTest.from_file(APP, default_timeout=60)
    at.run()
    at.sidebar.radio[0].set_value(page).run()
    assert not at.exception, at.exception
    text = " ".join(m.value for m in at.markdown) + " ".join(i.value for i in at.info)
    if page in ("Recovered Files", "Benchmark Laboratory", "Model Training"):
        assert "Not yet measured" in text or "No " in text
