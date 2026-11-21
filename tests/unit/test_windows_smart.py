"""The Windows simple UI uses exactly the original orchestrator plus smart fallback."""
from __future__ import annotations

from pathlib import Path

from recoverx.forensic.case_store import create_case
from recoverx.forensic.filesystem_analyzer import FsAnalysis
from recoverx.models import EngineRun, RecoveredFile
from recoverx.recovery import orchestrator as core


def test_smart_tries_second_engine_after_zero_outputs(tmp_path, monkeypatch):
    monkeypatch.setenv('RECOVERX_HOME', str(tmp_path / 'work'))
    img = tmp_path / 'disk.img'
    img.write_bytes(b'\x00' * 2048)
    case, _ = create_case(img)
    monkeypatch.setattr(core, 'analyze_image', lambda image: FsAnalysis(status='filesystem_not_detected', image_size=2048))
    outputs = []

    class StubEngine:
        def __init__(self, name):
            self.name = name

        def run(self, image, output_dir, *, run_id, **kwargs):
            outputs.append(self.name)
            output_dir.mkdir(parents=True, exist_ok=True)
            files = []
            if self.name == 'tsk':
                (output_dir / 'files').mkdir()
                (output_dir / 'files' / 'restored.pdf').write_bytes(b'%PDF-demo')
                files.append(RecoveredFile(run_id + '-0000', self.name, run_id,
                                           'restored.pdf', 'files/restored.pdf', 9, 'abc', 'pdf', 'pdf'))
            return EngineRun(self.name, run_id, 'completed', str(output_dir), 0.01, files=files)

    monkeypatch.setattr(core, 'get_engine', lambda name: StubEngine(name))
    run = core.run_recovery(case, 'smart')
    assert outputs == ['photorec', 'tsk']
    assert run['selection']['strategy_used'] == 'combined'
    assert 'no files' in run['selection']['fallback']
    assert run['status'] == 'completed'
    assert run['metrics']['outputs'] == 1
    assert run['source_unchanged']
    assert len(case.load()['runs']) == 1
    assert any(e['event'] == 'smart_fallback' for e in case.events())


def test_smart_does_not_run_second_engine_after_nonempty_first(tmp_path, monkeypatch):
    monkeypatch.setenv('RECOVERX_HOME', str(tmp_path / 'work'))
    img = tmp_path / 'disk.img'
    img.write_bytes(b'\x00' * 2048)
    case, _ = create_case(img)
    monkeypatch.setattr(core, 'analyze_image', lambda image: FsAnalysis(status='filesystem_not_detected', image_size=2048))
    calls = []

    class StubEngine:
        def __init__(self, name):
            self.name = name

        def run(self, image, output_dir, *, run_id, **kwargs):
            calls.append(self.name)
            output_dir.mkdir(parents=True, exist_ok=True)
            f = RecoveredFile(run_id + '-0000', self.name, run_id, 'test.jpg', 'recup.1/test.jpg', 100, 'abcd', 'jpg', 'jpeg')
            return EngineRun(self.name, run_id, 'completed', str(output_dir), 0.01, files=[f])

    monkeypatch.setattr(core, 'get_engine', lambda name: StubEngine(name))
    run = core.run_recovery(case, 'smart')
    assert calls == ['photorec']
    assert run['selection']['strategy_used'] == 'photorec'
    assert run['source_unchanged']


def test_original_explicit_strategy_methods_preserved():
    assert core._select('tsk', None, None)['strategy_used'] == 'tsk'
    assert core._select('combined', None, None)['strategy_used'] == 'combined'
