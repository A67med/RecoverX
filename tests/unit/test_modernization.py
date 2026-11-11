import json
import threading
from pathlib import Path
import numpy as np
import pytest
from recoverx.ml.features import FEATURE_NAMES
from recoverx.ml.selector import CartSelector
from recoverx.ml.labeling import derive_label
from recoverx.ml.evaluation import evaluate_records
from recoverx.forensic.case_store import create_case
from recoverx.models import EngineRun
from recoverx.recovery.orchestrator import run_recovery
from recoverx.reporting.exports import case_report


def test_json_predictions_match_sklearn_for_nontrivial_tree(tmp_path):
    rng=np.random.default_rng(42)
    X=rng.random((120,len(FEATURE_NAMES)))
    y=np.where(X[:,0]>.7,'tsk',np.where(X[:,1]>.5,'photorec','combined'))
    model=CartSelector.train(X,y,max_depth=5,min_samples_leaf=2)
    loaded=CartSelector.load(model.save(tmp_path,'v'))
    test=rng.random((500,len(FEATURE_NAMES)))
    assert np.array_equal(model.model.predict(test),loaded.model.predict(test))
    np.testing.assert_allclose(model.model.predict_proba(test),loaded.model.predict_proba(test))


def test_tie_epsilon_uses_registered_order():
    records={'tsk':{'recall':1,'times':[1.01]},'photorec':{'recall':1,'times':[1.0]},'combined':{'recall':1,'times':[2]}}
    assert derive_label(records,{'tolerance':0,'tie_epsilon_s':.02})['label']=='tsk'


def test_evaluation_enforces_disjoint_seed_splits(tmp_path):
    base=Path(__file__).resolve().parents[2]
    manifest=json.loads((base/'results/dataset_v1/manifest.json').read_text())
    manifest['images'][-1]['seed']=manifest['images'][0]['seed']
    path=tmp_path/'manifest.json'; path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError,match='leakage'):
        evaluate_records(base/'results/exp1',path)


def test_real_record_evaluation_preserves_test_holdout():
    base=Path(__file__).resolve().parents[2]
    model, report=evaluate_records(base/'results/exp1',base/'results/dataset_v1/manifest.json',
                                   {'max_depth':[1], 'min_samples_leaf':[4]})
    assert report['split_sizes']=={'train':60,'val':12,'test':24}
    assert not any(i.endswith(('s6','s7')) for i in model.meta['training_ids'])
    for fold in report['cross_validation']['folds']:
        assert not set(fold['train_seeds']) & set(fold['validation_seeds'])
    assert report['held_out']['per_class']['weighted avg']['support']==24


def test_precancelled_pipeline_is_persisted_without_tools(tmp_path):
    image=tmp_path/'image.img'; image.write_bytes(b'A'*2048)
    case,rec=create_case(image)
    event=threading.Event(); event.set()
    result=run_recovery(case,'combined',cancel_event=event)
    assert result['status']=='cancelled' and result['engine_runs']==[]
    assert result['source_unchanged'] and case.load()['runs'][0]['run_id']==result['run_id']
    assert json.loads((case.dir/'active_run.json').read_text())['stage']=='run_finished'
    assert 'cancelled' in case_report(case)


def test_unexpected_engine_error_is_saved(tmp_path,monkeypatch):
    image=tmp_path/'image.img'; image.write_bytes(b'A'*2048)
    case,_=create_case(image)
    monkeypatch.setattr('recoverx.recovery.orchestrator.get_engine',lambda *a:(_ for _ in ()).throw(RuntimeError('broken engine')))
    result=run_recovery(case,'tsk',analyze=False)
    assert result['status']=='failed' and 'broken engine' in result['error']
    assert result['source_unchanged'] and len(case.load()['runs'])==1


def test_failed_final_hash_invalidates_completed_run(tmp_path,monkeypatch):
    image=tmp_path/'image.img'; image.write_bytes(b'A'*2048)
    case,_=create_case(image)
    class MutatingEngine:
        def run(self,*args,**kwargs):
            image.write_bytes(b'B'*2048)
            return EngineRun('tsk','test','completed',str(tmp_path/'out'),.1)
    monkeypatch.setattr('recoverx.recovery.orchestrator.get_engine',lambda *a:MutatingEngine())
    result=run_recovery(case,'tsk',analyze=False)
    assert result['status']=='integrity_failed' and not result['source_unchanged']


def test_incomplete_analysis_cannot_select_only_one_engine(tmp_path,monkeypatch):
    from recoverx.forensic.filesystem_analyzer import FsAnalysis
    image=tmp_path/'image.img'; image.write_bytes(b'A'*2048)
    case,_=create_case(image)
    monkeypatch.setattr('recoverx.recovery.orchestrator.analyze_image',lambda *a,**k:FsAnalysis('partially_analyzed',2048,fs_type='FAT16'))
    class Stub:
        def run(self,*a,**k): return EngineRun('stub','test','completed',str(tmp_path/'out'),0)
    monkeypatch.setattr('recoverx.recovery.orchestrator.get_engine',lambda *a:Stub())
    result=run_recovery(case,'rule',conservative=False)
    assert result['selection']['strategy_used']=='combined'
    assert 'Incomplete' in result['selection']['safety_override']
    assert len(result['engine_runs'])==2


def test_job_registry_blocks_duplicates_and_cancel_propagates(monkeypatch):
    import recoverx.recovery.jobs as jobs
    from recoverx.exceptions import RecoverXError
    monkeypatch.setattr(jobs,'_current',None)
    def slow(case,method,*,cancel_event,progress,**kw):
        progress({'stage':'engine_started'})
        assert cancel_event.wait(3)
        return {'status':'cancelled'}
    monkeypatch.setattr(jobs,'run_recovery',slow)
    from types import SimpleNamespace
    case=SimpleNamespace(id='test')
    job=jobs.start_recovery(case,'combined')
    with pytest.raises(RecoverXError): jobs.start_recovery(case,'combined')
    job.cancel.set()
    assert job.done.wait(3)
    assert job.snapshot()['result']['status']=='cancelled'


def test_truncated_metadata_is_not_complete_analysis(tmp_path,monkeypatch):
    from recoverx.forensic.filesystem_analyzer import analyze_image
    from recoverx.models import CommandResult
    image=tmp_path/'source.img'; image.write_bytes(b'0'*2048)
    def command(args,**kwargs):
        if args[0]=='mmls': return CommandResult(args,1,'','',0,'now')
        if args[0]=='fsstat': return CommandResult(args,0,'File System Type: FAT16','',0,'now')
        return CommandResult(args,0,'r/r * 3:\tx.txt','',0,'now',output_truncated=True)
    monkeypatch.setattr('recoverx.forensic.filesystem_analyzer.run_command',command)
    result=analyze_image(image)
    assert result.status=='partially_analyzed' and result.output_truncated
    assert result.deleted_entries==[] and result.errors


def test_generator_refuses_existing_image(tmp_path):
    from recoverx.datasets.generator import build_image
    image=tmp_path/'images'/'keep.img'; image.parent.mkdir()
    image.write_bytes(b'original')
    with pytest.raises(FileExistsError):
        build_image(tmp_path,'keep','fat16','delete',0,16,'train',tmp_path)
    assert image.read_bytes()==b'original'


def test_invalid_benchmark_records_cannot_produce_claims(tmp_path):
    from recoverx.benchmarking.analysis import analyze_experiment
    (tmp_path/'labels.json').write_text(json.dumps({'labels':{},'objective':{}}))
    (tmp_path/'test_runs.jsonl').write_text(json.dumps({'image_id':'x','method':'cart','repeat':0,'status':'failed','source_unchanged':True,'recall':0})+'\n')
    with pytest.raises(ValueError,match='failed'):
        analyze_experiment(tmp_path)
