"""Render the v0.4 Quick Recovery page and every advanced tool headlessly with AppTest.

Runs against an empty home (fresh install): pages must show empty states, never fake data.
"""
from pathlib import Path

import pytest

st_testing = pytest.importorskip("streamlit.testing.v1")
APP = str(Path(__file__).resolve().parents[2] / "app.py")
ADVANCED = ["Overview", "Case Management", "Forensic Analysis", "Intelligent Recovery", "Recovered Files",
            "Model Training", "Benchmark Laboratory", "Evidence & Audit", "Settings & Diagnostics"]


def _app():
    return st_testing.AppTest.from_file(APP, default_timeout=90)


@pytest.fixture(autouse=True)
def no_live_devices(monkeypatch):
    # Device discovery reads real hardware on Windows; the UI tests use an empty inventory.
    from recoverx.usb import devices
    monkeypatch.setattr(devices, "list_devices", lambda **kw: [])


def text_of(at) -> str:
    return " ".join(m.value for m in at.markdown) + " ".join(c.value for c in at.caption)


def test_quick_recovery_is_the_only_main_workflow():
    at = _app().run()
    assert not at.exception, at.exception
    assert len(at.sidebar) == 0 or not list(at.sidebar.radio)
    page = text_of(at)
    for step in ("Select source", "Recovery method", "Choose output folder", "Start recovery", "Recovery results"):
        assert step in page
    labels = [o for o in next(r for r in at.radio if r.key == "rx_method").options]
    assert labels == ["Smart Recovery", "TSK only", "PhotoRec only", "TSK + PhotoRec",
                      "Automatic (CART only)", "Automatic (rule-v1 only)"]
    assert "No results yet" in page
    start = next(b for b in at.button if b.key == "rx_start")
    assert start.disabled  # no source selected and no authorization yet


@pytest.mark.parametrize("page", ADVANCED)
def test_advanced_tools_render_on_empty_install(page):
    at = _app().run()
    next(t for t in at.toggle if t.key == "rx_advanced").set_value(True).run()
    next(s for s in at.selectbox if s.key == "rx_advanced_page").set_value(page).run()
    assert not at.exception, at.exception
    text = " ".join(m.value for m in at.markdown) + " ".join(i.value for i in at.info)
    if page in ("Recovered Files", "Benchmark Laboratory", "Model Training"):
        assert "Not yet measured" in text or "No " in text


def test_image_source_validates_path_and_enables_start(tmp_path):
    img = tmp_path / "usb-copy.img"
    img.write_bytes(b"\x00" * 4096)
    at = _app().run()
    at.session_state["rx_source"] = "Disk image file"
    at.run()
    next(t for t in at.text_input if t.key == "quick_img").set_value(str(img)).run()
    next(t for t in at.text_input if t.key == "rx_output").set_value(str(tmp_path / "out")).run()
    next(c for c in at.checkbox if c.key == "rx_authorized").check().run()
    assert not at.exception, at.exception
    method = next(r for r in at.radio if r.key == "rx_method")
    method.set_value("tsk").run()
    start = next(b for b in at.button if b.key == "rx_start")
    from recoverx.diagnostics import run_diagnostics
    tsk_ok = any(e["engine"] == "tsk" and e["available"] for e in run_diagnostics()["engines"])
    assert start.disabled is (not tsk_ok)


def test_results_follow_selected_previous_case(tmp_path, monkeypatch):
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
    at = _app()
    at.session_state['quick_last_case_id'] = a.id
    at.session_state['rx_source'] = 'Disk image file'
    at.session_state['rx_image_mode'] = 'Image from a previous case'
    at.session_state['rx_case'] = b.id
    at.run()
    assert not at.exception, at.exception
    page = " ".join(m.value for m in at.markdown)
    assert b.id in page and a.id not in page
    assert "No recoverable deleted files" in page or "no recoverable deleted files" in page


def test_usb_flow_requires_explicit_confirmation_dialog(tmp_path, monkeypatch):
    """A (synthetic) USB device can be selected; Start opens the identity confirmation, nothing starts before it."""
    from recoverx.usb import devices
    from recoverx import workflow
    fake = devices.build_inventory([{"number": 3, "size": 8_000_000_000, "sector_size": 512, "bus_type": "USB",
                                     "vendor": "Generic", "product": "Flash Disk", "serial": "XYZ"}],
                                   {"G:": [(3, 1048576, 7_999_000_000)]}, {"G:": {"filesystem": "FAT32", "label": "PHOTOS"}},
                                   None, {})
    monkeypatch.setattr(devices, "list_devices", lambda **kw: fake)
    import recoverx.usb.imaging as imaging
    monkeypatch.setattr(imaging.win32, "disks_for_path", lambda p: {0})
    monkeypatch.setattr(imaging.win32, "IS_WINDOWS", True)  # exercise the Windows UI path on any OS
    started = []
    monkeypatch.setattr(workflow, "start_quick_job", lambda **kw: started.append(kw))
    import recoverx.ui.quick_app as qa
    monkeypatch.setattr(qa, "start_quick_job", lambda **kw: started.append(kw))
    at = _app()
    at.session_state["rx_output"] = str(tmp_path / "out")
    at.run()
    assert not at.exception, at.exception
    disk_radio = next(r for r in at.radio if r.key == "rx_disk")
    assert disk_radio.value == 3
    next(c for c in at.checkbox if c.key == "rx_authorized").check().run()
    start = next(b for b in at.button if b.key == "rx_start")
    assert not start.disabled and "Image USB drive" in start.label
    start.click().run()
    assert not at.exception, at.exception
    assert not started  # the dialog must be confirmed first
    page = " ".join(m.value for m in at.markdown)
    assert "PhysicalDrive3" in page and "XYZ" in page
