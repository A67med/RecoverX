import hashlib
import json
import os
import sys
import threading
import pytest

from recoverx.engines.sleuthkit_engine import SleuthKitEngine
from recoverx.engines.photorec_engine import PhotoRecEngine
from recoverx.exceptions import ModelError, RecoverXError, UnsafePathError
from recoverx.forensic.case_store import create_case, open_case
from recoverx.forensic.image_validator import ensure_safe_output
from recoverx.forensic.storage import operation_lock
from recoverx.ml.features import FEATURE_NAMES, validate_features
from recoverx.ml.selector import CartSelector
from recoverx.models import EngineRun
from recoverx.process import run_command
from recoverx.recovery.orchestrator import run_recovery
from recoverx.reporting.exports import csv_inventory


def test_output_may_not_contain_evidence(tmp_path):
    image=tmp_path/'evidence.img'
    image.write_bytes(b'x')
    with pytest.raises(UnsafePathError):
        ensure_safe_output(tmp_path,image)


@pytest.mark.parametrize('value',[float('nan'),float('inf'),-1])
def test_nonfinite_or_negative_features_rejected(value):
    features=dict.fromkeys(FEATURE_NAMES,0.0)
    features['image_mb']=value
    with pytest.raises(ValueError):
        validate_features(features)


def test_subprocess_permission_error_is_recorded(tmp_path):
    tool=tmp_path/'not-executable'
    tool.write_text('no')
    tool.chmod(0o600)
    result=run_command([str(tool)])
    assert not result.ok and 'unable to start' in result.stderr


def test_large_stdout_stderr_are_drained_and_bounded():
    result=run_command([sys.executable,'-c',"import sys; sys.stdout.write('a'*2000000); sys.stderr.write('b'*2000000)"],max_output_bytes=2048)
    assert result.ok and result.output_truncated
    assert len(result.stdout)==len(result.stderr)==2048


def test_precancel_does_not_launch_process(tmp_path):
    marker=tmp_path/'marker'
    event=threading.Event(); event.set()
    result=run_command([sys.executable,'-c',f"open({str(marker)!r},'w').close()"],cancel_event=event)
    assert result.cancelled and not marker.exists()


def test_inventory_skips_symlinks_fifos_and_hardlinks(tmp_path):
    root=tmp_path/'outputs'; root.mkdir()
    secret=tmp_path/'secret'; secret.write_text('private')
    (root/'symlink').symlink_to(secret)
    (root/'dir-link').symlink_to(tmp_path,target_is_directory=True)
    os.link(secret,root/'hardlink')
    os.mkfifo(root/'pipe')
    (root/'good').write_text('recovered')
    run=EngineRun('tsk','test','completed',str(root),0.0)
    files=SleuthKitEngine().inventory(root,run)
    assert [f.recovered_name for f in files]==['good']
    assert run.warnings and run.status=='incomplete'


def test_changed_source_blocks_before_engine_lookup(tmp_path,monkeypatch):
    image=tmp_path/'evidence.img'; image.write_bytes(b'A'*4096)
    case,_=create_case(image)
    image.write_bytes(b'B'*4096)
    def forbidden(*args):
        raise AssertionError('engine must never be selected for altered evidence')
    monkeypatch.setattr('recoverx.recovery.orchestrator.get_engine',forbidden)
    result=run_recovery(case,'combined')
    assert result['status']=='blocked' and not result['source_unchanged']
    assert result['engine_runs']==[] and case.load()['runs'][0]['status']=='blocked'


def test_case_lock_prevents_concurrent_run_and_releases(tmp_path):
    image=tmp_path/'evidence.img'; image.write_bytes(b'A'*4096)
    case,_=create_case(image)
    with operation_lock(case.dir):
        with pytest.raises(RecoverXError,match='already active'):
            run_recovery(case,'tsk')
    with operation_lock(case.dir):
        pass


def test_case_symlink_escape_rejected(tmp_path):
    cases=tmp_path/'cases'; cases.mkdir()
    other=tmp_path/'outside'; other.mkdir()
    (other/'case.json').write_text('{}')
    (cases/'escape').symlink_to(other,target_is_directory=True)
    with pytest.raises(ValueError):
        open_case('escape',cases_dir=cases)


def make_model(tmp_path):
    model=CartSelector.train([[0.0]*len(FEATURE_NAMES),[1.0]*len(FEATURE_NAMES)],['tsk','photorec'],max_depth=2,min_samples_leaf=1)
    return model.save(tmp_path,'v1')


def test_legacy_pickle_never_loaded(tmp_path):
    directory=make_model(tmp_path)
    (directory/'model.json').unlink()
    (directory/'model.joblib').write_bytes(b'not safe to deserialize')
    with pytest.raises(ModelError,match='Legacy'):
        CartSelector.load(directory)


def test_tampered_model_digest_rejected(tmp_path):
    directory=make_model(tmp_path)
    with (directory/'model.json').open('a') as f: f.write(' ')
    with pytest.raises(ModelError,match='digest'):
        CartSelector.load(directory)


def test_cyclic_model_rejected_even_with_updated_digest(tmp_path):
    directory=make_model(tmp_path)
    doc=json.loads((directory/'model.json').read_text())
    doc['nodes'][0]['left']=0
    data=json.dumps(doc).encode(); (directory/'model.json').write_bytes(data)
    meta=json.loads((directory/'meta.json').read_text())
    meta['model_sha256']=hashlib.sha256(data).hexdigest()
    (directory/'meta.json').write_text(json.dumps(meta))
    with pytest.raises(ModelError,match='branching'):
        CartSelector.load(directory)


def test_csv_neutralizes_formulas():
    result=csv_inventory([{'name':' =HYPERLINK("bad")','hash':'abc','size':4}])
    import csv,io
    row=next(csv.DictReader(io.StringIO(result)))
    assert row['name'].startswith("' ") and row['hash']=='abc' and row['size']=='4'


def test_photorec_never_silently_ignores_offset(tmp_path,monkeypatch):
    image=tmp_path/'disk.img'; image.write_bytes(b'0'*4096)
    monkeypatch.setattr(PhotoRecEngine,'preflight',lambda *a:None)
    monkeypatch.setattr(PhotoRecEngine,'version',lambda *a:'test')
    result=PhotoRecEngine().run(image,tmp_path/'output',sector_offset=1)
    assert result.status=='blocked' and 'offset' in result.error and not result.commands


@pytest.mark.parametrize('bad',[{}, {'deleted':[{'id':'x','sha256':'bad'}]}, {'deleted':'no'}])
def test_invalid_ground_truth_never_starts_recovery(tmp_path,bad):
    from recoverx.recovery.orchestrator import validate_ground_truth
    if bad=={}:
        validate_ground_truth(bad)
    else:
        with pytest.raises(ValueError): validate_ground_truth(bad)


def test_unsupported_container_rejected(tmp_path):
    from recoverx.forensic.image_validator import validate_image
    from recoverx.exceptions import ImageValidationError
    path=tmp_path/'case.E01'; path.write_bytes(b'EVF'+b'0'*100)
    with pytest.raises(ImageValidationError,match='Unsupported'):
        validate_image(path)


def test_hashing_rejects_symlink_and_fifo_without_blocking(tmp_path):
    from recoverx.forensic.hashing import sha256_file
    source=tmp_path/'real'; source.write_bytes(b'evidence')
    link=tmp_path/'link'; link.symlink_to(source)
    fifo=tmp_path/'pipe'; os.mkfifo(fifo)
    for path in (link,fifo):
        with pytest.raises(OSError): sha256_file(path)
