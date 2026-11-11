import shutil
from pathlib import Path
import pytest
from recoverx.forensic.case_store import create_case,build_manifest
from recoverx.recovery.orchestrator import run_recovery
from tests.conftest import needs_tools


@needs_tools
def test_conservative_automatic_runs_both_with_exact_hashes(fat_fixture):
    case,_=create_case(fat_fixture['image'])
    result=run_recovery(case,'rule',ground_truth=fat_fixture['gt'])
    assert result['selection']['strategy_used']=='combined'
    assert result['selection']['recommended']=='tsk'
    assert result['metrics']['recall']==1 and result['source_unchanged']
    assert result['status']=='completed'
    assert {e['engine'] for e in result['engine_runs']}=={'tsk','photorec'}
    manifest=build_manifest(case)
    assert manifest['runs'][0]['settings']['conservative']
    assert manifest['runs'][0]['selection']['safety_override']


@needs_tools
def test_partitioned_image_uses_tsk_offset_and_whole_carving(fat_fixture,tmp_path):
    import struct
    disk=tmp_path/'partitioned.img'
    offset=2048
    sectors=fat_fixture['image'].stat().st_size//512
    mbr=bytearray(512)
    mbr[446:462]=struct.pack('<B3sB3sII',0,b'\0'*3,0x06,b'\0'*3,offset,sectors)
    mbr[510:512]=b'\x55\xaa'
    with disk.open('wb') as out, fat_fixture['image'].open('rb') as source:
        out.write(mbr); out.seek(offset*512); shutil.copyfileobj(source,out)
    case,_=create_case(disk)
    result=run_recovery(case,'combined',ground_truth=fat_fixture['gt'])
    assert result['source_unchanged'] and result['metrics']['recall']==1
    tsk=next(e for e in result['engine_runs'] if e['engine']=='tsk')
    assert '-o' in tsk['commands'][0]['args'] and '2048' in tsk['commands'][0]['args']
    pr=next(e for e in result['engine_runs'] if e['engine']=='photorec')
    assert 'freespace' not in pr['commands'][0]['args'][-1]
    assert result['warnings']


@needs_tools
@pytest.mark.parametrize('page',['Overview','Intelligent Recovery','Recovered Files','Evidence & Audit','Forensic Analysis'])
def test_populated_dashboard_has_no_exceptions(fat_fixture,page):
    from streamlit.testing.v1 import AppTest
    case,_=create_case(fat_fixture['image'])
    run_recovery(case,'combined',ground_truth=fat_fixture['gt'])
    app=str(Path(__file__).resolve().parents[2]/'app.py')
    at=AppTest.from_file(app,default_timeout=60).run()
    at.sidebar.radio[0].set_value(page).run()
    assert not at.exception
