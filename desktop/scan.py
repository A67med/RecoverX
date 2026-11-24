"""RecoverX Desktop scan worker. Its only source is the private case image."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import threading
import time
from dataclasses import asdict

from recoverx.config import PROJECT_ROOT
from recoverx.engines.photorec_engine import PhotoRecEngine
from recoverx.engines.sleuthkit_engine import SleuthKitEngine
from recoverx.forensic.filesystem_analyzer import FsAnalysis, DeletedEntry
from recoverx.ml.features import extract_features
from recoverx.ml.policy import rule_select
from recoverx.models import utcnow
from recoverx.recovery.integrity import canonical_view, apply_ground_truth, recovery_metrics
from partitions import layout

MODEL = PROJECT_ROOT/'research/results/exp1/models/cart-20261030-193546'
METHODS = ('smart','tsk','photorec','combined','cart','rule')
CHUNK = 4 * 1024**2

def check(cancel):
    if cancel.is_set():
        raise InterruptedError("Scan stopped. The case contains the completed work.")

def digest(path, cancel):
    h=hashlib.sha256()
    with path.open('rb') as f:
        while data := f.read(CHUNK):
            check(cancel)
            h.update(data)
    return h.hexdigest()

def features(image, span, spans, cancel):
    import pytsk3 as t
    a=FsAnalysis('analysis_completed',image.stat().st_size,partitions=spans if span.start else [])
    try:
        fs=t.FS_Info(t.Img_Info(str(image)),offset=span.start)
    except OSError:
        return extract_features(a), 'Filesystem metadata unavailable'
    a.fs_type={t.TSK_FS_TYPE_NTFS:'NTFS',t.TSK_FS_TYPE_FAT32:'FAT32',t.TSK_FS_TYPE_FAT16:'FAT16',
               t.TSK_FS_TYPE_EXT4:'Ext4', t.TSK_FS_TYPE_EXFAT:'exFAT',t.TSK_FS_TYPE_FAT12:'FAT12'}.get(fs.info.ftype,'Other')
    queue=[(fs.info.root_inum,'')]
    seen=set()
    while queue:
        inode,parent=queue.pop()
        if inode in seen:
            continue
        seen.add(inode)
        try:
            directory=fs.open_dir(inode=inode)
        except OSError:
            continue
        for f in directory:
            check(cancel)
            n,m=f.info.name,f.info.meta
            if not n or not n.name or n.name in (b'.',b'..') or not m:
                continue
            name=n.name.decode('utf-8','replace')
            path=parent+name
            if m.type in (t.TSK_FS_META_TYPE_DIR,t.TSK_FS_META_TYPE_VIRT_DIR):
                queue.append((m.addr,path+'/'))
            elif m.type==t.TSK_FS_META_TYPE_REG:
                if n.flags & t.TSK_FS_NAME_FLAG_UNALLOC:
                    a.deleted_entries.append(DeletedEntry(str(m.addr),path,m.size,bool(m.flags & t.TSK_FS_META_FLAG_ALLOC),'r/r'))
                elif not path.startswith('$'):
                    a.allocated_files+=1
    return extract_features(a), a.fs_type

def cart_predict(values):
    tree=json.loads((MODEL/'portable-tree.json').read_text())
    index=0
    while tree['left'][index] != -1:
        feature=tree['names'][tree['feature'][index]]
        index=(tree['left'] if values[feature]<=tree['threshold'][index] else tree['right'])[index]
    return tree['label'][index]

def plan(method, values):
    if method in ('cart','smart'):
        try:
            return cart_predict(values),'CART · cart-20261030-193546'
        except (OSError, KeyError, IndexError, ValueError):
            if method=='cart':
                raise ValueError("The packaged CART model is unavailable.")
            method='rule'
    if method=='rule':
        choice,reason=rule_select(values)
        return choice,'rule-v1 · '+reason
    return method, 'Fixed method'

def slice_image(image, span, target, cancel, tell):
    with image.open('rb') as src, target.open('xb') as dst:
        src.seek(span.start)
        done=0
        while done<span.size:
            check(cancel)
            data=src.read(min(CHUNK,span.size-done))
            if not data:
                raise IOError("Incomplete image while reading a partition.")
            dst.write(data)
            done+=len(data)
            tell('Preparing partition for signature scan',done,span.size)

def candidate_updates(out, name, stage, finished, notify):
    while not finished.wait(4):
        count=0
        for base in ([out/'files'] if name=='tsk' else out.glob('recup.*')):
            for _, _, names in os.walk(base):
                if finished.is_set():
                    return
                count+=sum(n!='report.xml' for n in names)
                if count>=5000:
                    break
            if count>=5000:
                break
        if not finished.is_set():
            detail='5,000+ staged files' if count>=5000 else str(count)+' staged files'
            notify({'stage':stage+' · '+detail,'done':0,'total':0})

def scan(case, method, sector, known, cancel, notify):
    case=case.resolve()
    image=case/'evidence.img'
    if method not in METHODS or not image.is_file():
        raise ValueError("Choose a supported method and a completed case image.")
    start=time.monotonic()
    report={'version':'1.0.0-rc1','started':utcnow(),'method':method,'logical_sector_size':sector,
            'runs':[],'decisions':[],'warnings':[],'status':'in_progress','files':[]}
    acq=case/'acquisition.json'
    if acq.exists():
        report['acquisition']=json.loads(acq.read_text(encoding='utf-8-sig'))
    files=[]
    paths={}
    def tell(msg,done=0,total=0):
        check(cancel)
        notify({'stage':msg,'done':done,'total':total})
    def event(kind,**values):
        with (case/'events.jsonl').open('a',encoding='utf-8') as f:
            f.write(json.dumps({'time':utcnow(),'event':kind,**values})+'\n')
    try:
        event('scan-start', method=method)
        tell('Verifying the saved image')
        sha=digest(image,cancel)
        report['image_sha256']=sha
        expected=report.get('acquisition',{}).get('sha256')
        if expected and sha.lower()!=expected.lower():
            raise ValueError("The saved image failed acquisition hash verification.")
        spans=layout(image,sector)
        report['partitions']=[asdict(s) for s in spans]
        for i,span in enumerate(spans,1):
            tell('Reading '+span.label)
            values={}
            if method in ('smart','rule','cart'):
                values,fs=features(image,span,spans,cancel)
            else:
                fs='Not profiled'
            choice,reason=plan(method,values)
            decision={'partition':i,'filesystem':fs,'features':values,'choice':choice,'reason':reason}
            report['decisions'].append(decision)
            pending=['tsk','photorec'] if choice=='combined' else [choice]
            for engine in pending:
                check(cancel)
                out=case/('partition-%02d'%i)/engine
                evidence=image
                temp=None
                tell(('Following deleted file records' if engine=='tsk' else 'Searching for file signatures')+' · '+span.label)
                if engine=='tsk':
                    adapter=SleuthKitEngine()
                    adapter.sector_size=sector
                else:
                    adapter=PhotoRecEngine(script='partition_none,wholespace,search')
                    if span.start or span.size!=image.stat().st_size:
                        if shutil.disk_usage(case).free<span.size+64*1024**2:
                            raise IOError("Insufficient space for the partition and its recovered files.")
                        temp=case/('slice-%02d.dd'%i)
                        try:
                            slice_image(image,span,temp,cancel,tell)
                        except BaseException:
                            temp.unlink(missing_ok=True)
                            raise
                        evidence=temp
                    tell('Searching for file signatures · '+span.label)
                adapter.required_free_bytes=64*1024**2
                event('engine-start',engine=engine,partition=i,start_byte=span.start)
                finished=threading.Event()
                monitor=threading.Thread(target=candidate_updates,args=(out,engine,engine.upper(),finished,notify),daemon=True)
                monitor.start()
                try:
                    run=adapter.run(evidence,out,sector_offset=span.start//sector if engine=='tsk' else 0,
                                    timeout=7*24*3600,cancel_event=cancel)
                finally:
                    finished.set()
                    monitor.join()
                    if temp and temp.exists():
                        temp.unlink()
                row=run.to_dict()
                row['source_start_byte']=span.start
                row['source_length']=span.size
                row['partition']=i
                report['runs'].append(row)
                for f in run.files:
                    paths[f.recovery_id]=(out/f.relative_path).relative_to(case).as_posix()
                    files.append(f)
                event('engine-end',engine=engine,status=run.status,files=len(run.files))
                check(cancel)
                if run.status!='completed':
                    report['warnings'].append(engine.upper()+' · '+str(run.error or run.status))
                if method=='smart' and len(pending)==1 and (run.status!='completed' or not run.files):
                    other='tsk' if engine=='photorec' else 'photorec'
                    pending.append(other)
                    decision['fallback']=other
                    event('fallback',engine=other,reason=run.status if run.status!='completed' else 'zero candidates')
        report['status']='completed' if not report['warnings'] else 'partial'
        if not any(r['status']=='completed' for r in report['runs']):
            report['status']='failed'
    except InterruptedError as exc:
        report['status']='cancelled'
        report['warnings'].append(str(exc))
    except Exception as exc:
        report['status']='failed'
        report['warnings'].append(str(exc))
    finally:
        apply_ground_truth(files,known)
        report['metrics']=recovery_metrics(files,known)
        by_id={f.recovery_id:f for f in files}
        for row in canonical_view(files):
            ordered=sorted((by_id[x] for x in row['outputs']),key=lambda f: f.engine!='tsk')
            f=ordered[0]
            report['files'].append({'name':f.recovered_name,'path':paths[f.recovery_id],'size':f.size,
                                    'sha256':f.sha256,'engine':' + '.join(row['engines']),
                                    'integrity':f.integrity_state,'reference':f.ground_truth_id,
                                    'detected_type':f.detected_type})
        report['finished']=utcnow()
        report['seconds']=round(time.monotonic()-start,3)
        (case/'report.tmp').write_text(json.dumps(report,indent=2),encoding='utf-8')
        (case/'report.tmp').replace(case/'report.json')
        event('scan-end',status=report['status'],seconds=report['seconds'])
    return report

if __name__=='__main__':
    # utf-8-sig: the WPF host may prefix a BOM when the console code page is UTF-8
    req=json.loads(sys.stdin.buffer.readline().decode('utf-8-sig'))
    stop=threading.Event()
    def listen():
        sys.stdin.readline()  # Cancel line or parent pipe closure
        stop.set()
    threading.Thread(target=listen,daemon=True).start()
    def emit(row):
        print(json.dumps(row),flush=True)
    result=scan(Path(req['case']),req['method'],int(req['sector']),req.get('known'),stop,emit)
    sys.exit(1 if result['status']=='failed' else 0)

