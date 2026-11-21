"""Offline safety and workflow tests for one-click additions."""

import pytest

from recoverx.acquisition import AcquisitionError, parse_candidates, capture_device
from recoverx import acquisition
from recoverx import quick
from recoverx.forensic.case_store import create_case, open_case


def test_candidates_exclude_system_disk_and_mounted_media():
    devices = {'blockdevices': [
        {'type': 'disk', 'path': '/dev/sdb', 'size': 80 * 2**30, 'children': [
            {'type': 'part', 'path': '/dev/sdb1', 'size': 80 * 2**30,
             'mountpoints': ['/'], 'children': []}]},
        {'type': 'disk', 'path': '/dev/sda', 'size': 2 * 2**30, 'children': [
            {'type': 'part', 'path': '/dev/sda1', 'size': 2 * 2**30,
             'mountpoints': [None], 'fstype': 'vfat'}]},
        {'type': 'disk', 'path': '/dev/sdc', 'size': 4 * 2**30, 'children': [
            {'type': 'part', 'path': '/dev/sdc1', 'size': 4 * 2**30,
             'mountpoints': ['/media/drive'], 'fstype': 'vfat'}]},
    ]}
    candidates = parse_candidates(devices)
    assert [x['path'] for x in candidates] == ['/dev/sda1', '/dev/sda']


def test_capture_refuses_disk_not_on_allowlist(monkeypatch):
    monkeypatch.setattr(acquisition, 'candidate_devices', lambda: [
        {'path': '/dev/sda1', 'size': 1234}])
    with pytest.raises(AcquisitionError, match='no longer a safe'):
        capture_device('/dev/sdb1')


def test_capture_requires_polkit(monkeypatch):
    monkeypatch.setattr(acquisition, 'candidate_devices', lambda: [
        {'path': '/dev/sda1', 'size': 1234}])
    monkeypatch.setattr(acquisition.shutil, 'which', lambda name: None)
    with pytest.raises(AcquisitionError, match='pkexec'):
        capture_device('/dev/sda1')


def test_guided_recovery_requires_exactly_one_source():
    with pytest.raises(ValueError, match='exactly one'):
        quick.guided_recovery()
    with pytest.raises(ValueError, match='exactly one'):
        quick.guided_recovery(image_path='/a', case_id='b')
    with pytest.raises(ValueError, match='Authorization'):
        quick.guided_recovery(image_path='/a')


def test_guided_recovery_reuses_record_and_returns_analysis(tmp_path, monkeypatch):
    img = tmp_path / 'evidence.img'
    img.write_bytes(b'forensic bytes are immutable')
    cases = tmp_path / 'cases'
    case, first = create_case(img, cases_dir=cases)
    monkeypatch.setattr(quick, 'open_case', lambda cid: open_case(cid, cases_dir=cases))
    monkeypatch.setattr(quick, 'run_recovery', lambda obj, method, **kwargs: {
        'run_id': 'R001', 'finished_at': '2026-11-14T10:00:00Z',
        'analysis': {'status': 'analysis_completed', 'deleted_entries': []},
        'features': {'n_deleted_named': 0}
    })
    rec, run = quick.guided_recovery(case_id=case.id, method='cart')
    assert run['analysis']['status'] == 'analysis_completed'
    assert run['features']['n_deleted_named'] == 0
    assert rec['image_sha256_initial'] == first['image_sha256_initial']
    assert run['run_id'] == 'R001'
