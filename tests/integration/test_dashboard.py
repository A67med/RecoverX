"""Render every dashboard page headlessly with Streamlit's AppTest and assert no
exception. Runs against an empty home (fresh install) — pages must show
'Not yet measured' states, not fake data."""
from pathlib import Path

import pytest

st_testing = pytest.importorskip("streamlit.testing.v1")
APP = str(Path(__file__).resolve().parents[2] / "app.py")
PAGES = ["Quick Recovery", "Overview", "Case Management", "Forensic Analysis", "Intelligent Recovery", "Recovered Files",
         "Model Training", "Benchmark Laboratory", "Evidence & Audit", "Settings & Diagnostics"]


@pytest.mark.parametrize("page", PAGES)
def test_page_renders_on_empty_install(page):
    at = st_testing.AppTest.from_file(APP, default_timeout=60)
    at.run()
    if page != 'Quick Recovery' and not at.sidebar.checkbox[0].value:
        at.sidebar.checkbox[0].set_value(True).run()
    at.sidebar.radio[0].set_value(page).run()
    assert not at.exception, at.exception
    text = " ".join(m.value for m in at.markdown) + " ".join(i.value for i in at.info)
    if page in ("Recovered Files", "Benchmark Laboratory", "Model Training"):
        assert "Not yet measured" in text or "No " in text


def test_quick_results_follow_selected_case(tmp_path, monkeypatch):
    from recoverx.forensic.case_store import create_case
    from recoverx.models import EngineRun
    from recoverx.recovery import orchestrator

    class EmptyEngine:
        def run(self, image, output_dir, *, run_id, **kwargs):
            return EngineRun('tsk', run_id, 'completed', str(output_dir), 0.0)

    monkeypatch.setattr(orchestrator, 'get_engine', lambda name: EmptyEngine())
    fixture = tmp_path / 'image.img'
    fixture.write_bytes(b'fixture')
    a, _ = create_case(fixture, label='Case A')
    b, _ = create_case(fixture, label='Case B')
    orchestrator.run_recovery(a, 'tsk', analyze=False)
    orchestrator.run_recovery(b, 'tsk', analyze=False)
    at = st_testing.AppTest.from_file(APP, default_timeout=60)
    at.session_state['quick_last_case_id'] = a.id
    at.run()
    next(w for w in at.radio if w.label == 'Source').set_value('Existing case').run()
    cases = next(w for w in at.selectbox if w.label == 'Existing case')
    cases.set_value(f'{b.id} — Case B').run()
    assert not at.exception
    assert any(str(b.runs_dir()) in element.value for element in at.code)
    assert not any(str(a.runs_dir()) in element.value for element in at.code)
