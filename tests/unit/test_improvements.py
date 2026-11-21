"""Regression tests for the presentation/demo-ready safety and usability fixes.

Do not require system recovery tools. Real TSK/PhotoRec integration tests are
still in tests/integration/ and are marked blocked if prerequisites are absent.
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

import pytest

from recoverx.exceptions import EvidenceIntegrityError
from recoverx.forensic.case_store import create_case
from recoverx.ml.model_install import bundled_model_dir, install_bundled_model
from recoverx.ml.selector import CartSelector
from recoverx.models import EngineRun, RecoveredFile
from recoverx.recovery.orchestrator import run_recovery
from recoverx.reporting.pdf_report import generate_case_pdf


def case_with_image(tmp_path):
    image = tmp_path / 'evidence.img'
    image.write_bytes(b'original-disk-data' * 40)
    return image, create_case(image)[0]


def test_changed_evidence_blocks_before_invoking_any_engine(tmp_path, monkeypatch):
    image, case = case_with_image(tmp_path)
    image.write_bytes(b'CHANGED' + image.read_bytes()[7:])

    def forbidden(*args, **kwargs):
        raise AssertionError('forensic engine invoked despite changed evidence')

    monkeypatch.setattr('recoverx.recovery.orchestrator.get_engine', forbidden)
    with pytest.raises(EvidenceIntegrityError, match='does not match'):
        run_recovery(case, 'tsk')
    rec = case.load()
    assert rec['status'] == 'evidence_changed'
    assert rec['last_hash_check']['unchanged'] is False
    assert rec['runs'] == []
    assert {'evidence_check_failed', 'run_blocked'} <= {x['event'] for x in case.events()}


def test_missing_baseline_blocks_recovery(tmp_path):
    img = tmp_path / 'data.img'
    img.write_bytes(b'evidence')
    case, _rec = create_case(img, compute_hash=False)
    with pytest.raises(EvidenceIntegrityError, match='No initial'):
        run_recovery(case, 'tsk')
    assert case.load()['status'] == 'evidence_not_baselined'


def test_missing_evidence_records_failure(tmp_path):
    image, case = case_with_image(tmp_path)
    image.unlink()
    with pytest.raises(EvidenceIntegrityError, match='cannot be read'):
        run_recovery(case, 'tsk')
    assert case.load()['status'] == 'evidence_unavailable'


def test_start_timestamp_and_progress_are_per_run(tmp_path, monkeypatch):
    _image, case = case_with_image(tmp_path)
    initial_creation = datetime.fromisoformat(case.load()['created_at'])
    time.sleep(.015)

    class FakeEngine:
        def run(self, img, output_dir, *, sector_offset, timeout, run_id):
            return EngineRun(engine='tsk', run_id=run_id, status='completed',
                             output_dir=str(output_dir), elapsed_s=0.001)

    monkeypatch.setattr('recoverx.recovery.orchestrator.get_engine', lambda _name: FakeEngine())
    events = []
    run = run_recovery(case, 'tsk', progress=events.append)
    assert run['status'] == 'completed'
    assert datetime.fromisoformat(run['started_at']) >= initial_creation
    assert run['started_at'] != case.load()['created_at']
    assert run['source_unchanged'] is True
    assert events[0].startswith('Checking') and events[-1].startswith('Finished')


def test_pdf_export_has_case_data_and_preserves_no_file_content(tmp_path):
    fitz = pytest.importorskip('fitz')  # optional PDF renderer, not required by RecoverX
    _image, case = case_with_image(tmp_path)
    rec = case.load()
    rec['label'] = '<b>demo & test</b>'
    case.save(rec)
    pdf = generate_case_pdf(case)
    assert pdf.startswith(b'%PDF-') and len(pdf) > 2500
    doc = fitz.open(stream=pdf, filetype='pdf')
    contents = '\n'.join(page.get_text() for page in doc)
    assert case.id in contents
    assert 'No recovery runs' in contents
    assert 'chain of custody' in contents
    assert 'demo & test' in contents


def test_pdf_includes_run_and_engine_metadata(tmp_path, monkeypatch):
    fitz = pytest.importorskip('fitz')  # optional test-only renderer
    _image, case = case_with_image(tmp_path)

    class FakeEngine:
        def run(self, img, output_dir, *, sector_offset, timeout, run_id):
            return EngineRun(engine='tsk', run_id=run_id, status='completed',
                             output_dir=str(output_dir), elapsed_s=.001)

    monkeypatch.setattr('recoverx.recovery.orchestrator.get_engine', lambda *_: FakeEngine())
    run = run_recovery(case, 'tsk')
    contents = '\n'.join(p.get_text() for p in fitz.open(stream=generate_case_pdf(case), filetype='pdf'))
    assert run['run_id'] in contents
    assert 'completed' in contents
    assert 'Recovered outputs: 0' in contents


def test_pdf_lists_recovered_names_and_hashes(tmp_path, monkeypatch):
    fitz = pytest.importorskip('fitz')
    _image, case = case_with_image(tmp_path)
    target_hash = 'abcd' * 16

    class FakeEngine:
        def run(self, img, output_dir, *, sector_offset, timeout, run_id):
            f = RecoveredFile(recovery_id=run_id+'-1', engine='tsk', run_id=run_id,
                              recovered_name='restored-sample.txt', relative_path='files/restored-sample.txt',
                              size=16, sha256=target_hash, extension='.txt', detected_type='text/plain')
            return EngineRun(engine='tsk', run_id=run_id, status='completed',
                             output_dir=str(output_dir), elapsed_s=.001, files=[f])

    monkeypatch.setattr('recoverx.recovery.orchestrator.get_engine', lambda *_: FakeEngine())
    run_recovery(case, 'tsk')
    report = fitz.open(stream=generate_case_pdf(case), filetype='pdf')
    content = '\n'.join(p.get_text() for p in report)
    assert 'restored-sample.txt' in content
    assert 'ground_truth_unavailable' in content


def test_bundled_model_installs_independently_of_archived_paths(tmp_path):
    from sklearn.exceptions import InconsistentVersionWarning
    import warnings
    assert bundled_model_dir() is not None
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', InconsistentVersionWarning)
        path = install_bundled_model()
        model = CartSelector.load(path)
    assert model.meta['version'].startswith('cart-')
    assert path.parent.name == 'models'
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', InconsistentVersionWarning)
        assert path.exists() and path == install_bundled_model()


def test_demo_case_writes_gt_and_case_record(tmp_path, monkeypatch):
    from recoverx import demo

    def fake_generate(root, **_kwargs):
        (root / 'images').mkdir(parents=True)
        (root / 'images/fat16-delete-s0.img').write_bytes(b'evidence')
        return {'images': [{'image_id':'fat16-delete-s0',
                            'image_file':'images/fat16-delete-s0.img',
                            'deleted':[{'id':'target-a','sha256':'abcd'}],
                            'allocated':[]}]}

    monkeypatch.setattr(demo, 'generate_dataset', fake_generate)
    monkeypatch.setattr(demo, 'validate_dataset', lambda *_: [])
    case, rec = demo.create_demo_case()
    assert case.record_path.exists()
    assert Path(rec['demo_dataset_dir']).parent.name == 'datasets'
    assert json.loads(Path(rec['demo_ground_truth_path']).read_text())['deleted'][0]['id'] == 'target-a'
    assert 'demo_case_created' in [e['event'] for e in case.events()]
