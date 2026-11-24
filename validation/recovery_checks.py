"""Exercise the released engines on ordinary files only. Run with the packaged Python."""
import hashlib
import json
from pathlib import Path
import random
import shutil
import struct
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import zlib
from make_fixture import fat32_fixture
from partitions import layout
from scan import scan, plan

HERE=Path(__file__).resolve().parent
SAMPLE=HERE/'sample/three-deleted.img'
ORIGINALS=json.loads((HERE/'sample/original-hashes.json').read_text())
OUT=Path(sys.argv.pop(1)).resolve() if len(sys.argv)>1 else Path(tempfile.mkdtemp(prefix='RecoverX-validation-'))
OUT.mkdir(parents=True,exist_ok=True)
MEASURED=[]

def make_gpt(source,target,sector=4096,repeat=2):
    payload=source.read_bytes()[1048576:]
    size=(len(payload)+sector-1)//sector
    first=256
    starts=[first+i*(size+40) for i in range(repeat)]
    count=starts[-1]+size+40
    buf=bytearray(count*sector)
    buf[450]=0xee
    struct.pack_into('<II',buf,454,1,count-1);buf[510:512]=b'\x55\xaa'
    entries=bytearray(128*128)
    for i,start in enumerate(starts):
        pos=i*128
        entries[pos:pos+16]=bytes.fromhex('a2a0d0ebe5b9334487c068b6b72699c7')
        entries[pos+16:pos+32]=bytes([i+1])*16
        struct.pack_into('<QQ',entries,pos+32,start,start+size-1)
        buf[start*sector:start*sector+len(payload)]=payload
    def header(current,other,entries_lba):
        h=bytearray(92);h[:8]=b'EFI PART'
        struct.pack_into('<IIIIQQQQ',h,8,0x10000,92,0,0,current,other,8,count-8)
        h[56:72]=bytes(range(16))
        struct.pack_into('<QIII',h,72,entries_lba,128,128,zlib.crc32(entries))
        struct.pack_into('<I',h,16,zlib.crc32(h));return h
    array_sectors=(len(entries)+sector-1)//sector
    backup=count-1-array_sectors
    buf[2*sector:2*sector+len(entries)]=entries
    buf[backup*sector:backup*sector+len(entries)]=entries
    buf[sector:sector+92]=header(1,count-1,2)
    buf[(count-1)*sector:(count-1)*sector+92]=header(count-1,1,backup)
    target.write_bytes(buf)
    return [s*sector for s in starts]

class ReleaseChecks(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='run-',dir=OUT)
        self.addCleanup(self.temp.cleanup)
        self.case=Path(self.temp.name)
        self.img=self.case/'evidence.img'
        self.stop=threading.Event()
    def execute(self,method='smart',sector=512,known=ORIGINALS):
        return scan(self.case,method,sector,known,self.stop,lambda e:None)
    def fixed(self,method,expected):
        shutil.copyfile(SAMPLE,self.img)
        initial=hashlib.sha256(self.img.read_bytes()).hexdigest()
        report=self.execute(method)
        self.assertEqual(report['status'],'completed',report['warnings'])
        self.assertEqual([r['engine'] for r in report['runs']],expected)
        self.assertEqual(report['metrics']['outputs'],3*len(expected))
        self.assertEqual(report['metrics']['exact_recovered'],3)
        self.assertEqual(report['metrics']['unrecovered'],0)
        self.assertEqual(hashlib.sha256(self.img.read_bytes()).hexdigest(),initial)
        self.assertEqual({f['sha256'] for f in report['files']},{f['sha256'] for f in ORIGINALS['deleted']})
        self.assertEqual(report['partitions'][0]['start'],1048576)
        MEASURED.append({'method':method,'engines':expected,'seconds':report['seconds'],'metrics':report['metrics'],
                         'image_sha256':initial,'hashes':[{'original':f['reference'],'sha256':f['sha256']} for f in report['files']]})
    def test_tsk_only(self):self.fixed('tsk',['tsk'])
    def test_photorec_only(self):self.fixed('photorec',['photorec'])
    def test_combined(self):self.fixed('combined',['tsk','photorec'])
    def test_smart(self):self.fixed('smart',['photorec'])
    def test_cart(self):self.fixed('cart',['photorec'])
    def test_rule(self):self.fixed('rule',['tsk'])
    def test_fallback_on_no_signatures(self):
        src=self.case/'original';src.mkdir()
        (src/'SECRET.BIN').write_bytes(random.Random(4785).randbytes(287))
        fixture=self.case/'fixture';fat32_fixture(fixture,src)
        shutil.copy(fixture/'three-deleted.img',self.img)
        r=self.execute(known=json.loads((fixture/'original-hashes.json').read_text()))
        self.assertEqual([a['engine'] for a in r['runs']],['photorec','tsk'])
        self.assertEqual(r['metrics']['exact_recovered'],1);self.assertEqual(r['decisions'][0]['fallback'],'tsk')
    def test_cart_missing(self):
        f={'fs_detected':0}
        with patch('scan.cart_predict',side_effect=FileNotFoundError):
            self.assertEqual(plan('smart',f)[0],'photorec')
            with self.assertRaises(ValueError):plan('cart',f)
    def test_two_gpt_partitions(self):
        starts=make_gpt(SAMPLE,self.img,512)
        r=self.execute('combined')
        self.assertEqual(r['status'],'completed',r['warnings']);self.assertEqual(len(r['runs']),4)
        self.assertEqual([run['source_start_byte'] for run in r['runs']],sorted(starts*2))
        self.assertEqual(r['metrics']['outputs'],12);self.assertEqual(r['metrics']['exact_recovered'],3)
    def test_4kn_partition_bounds_and_carving(self):
        starts=make_gpt(SAMPLE,self.img,4096,1)
        self.assertEqual(layout(self.img,4096)[0].start,starts[0])
        r=self.execute('photorec',4096);self.assertEqual(r['metrics']['exact_recovered'],3,r['warnings'])
        with self.assertRaises(ValueError):layout(self.img,512)
    def test_partitionless(self):
        self.img.write_bytes(SAMPLE.read_bytes()[1048576:])
        r=self.execute('combined');self.assertEqual(r['metrics']['exact_recovered'],3);self.assertEqual(r['runs'][0]['source_start_byte'],0)
    def test_invalid_gpt_checksum(self):
        make_gpt(SAMPLE,self.img,4096,1)
        with self.img.open('r+b') as f:f.seek(4096+16);f.write(bytes(4))
        with self.assertRaisesRegex(ValueError,'checksum'):layout(self.img,4096)
    def test_mbr_outside_image(self):
        buf=bytearray(4096);buf[450]=0x0c;struct.pack_into('<II',buf,454,10,1000);buf[510:512]=b'\x55\xaa'
        self.img.write_bytes(buf)
        r=self.execute();self.assertEqual(r['status'],'failed');self.assertEqual(r['runs'],[])
    def test_ebr_loop(self):
        buf=bytearray(64*512)
        for i in [0,1]:buf[i*512+510:i*512+512]=b'\x55\xaa'
        buf[450]=15;struct.pack_into('<II',buf,454,1,63)
        buf[512+466]=15;struct.pack_into('<II',buf,512+470,0,32)
        self.img.write_bytes(buf)
        with self.assertRaisesRegex(ValueError,'chain'):layout(self.img,512)
    def test_incomplete_hash(self):
        shutil.copy(SAMPLE,self.img)
        (self.case/'acquisition.json').write_text(json.dumps({'sha256':'0'*64}))
        r=self.execute();self.assertEqual(r['status'],'failed');self.assertEqual(r['runs'],[])
    def test_cancel(self):
        shutil.copy(SAMPLE,self.img);self.stop.set()
        r=self.execute();self.assertEqual(r['status'],'cancelled');self.assertEqual(r['runs'],[])
    def test_no_known_hashes(self):
        shutil.copy(SAMPLE,self.img)
        r=self.execute('tsk',known=None);self.assertFalse(r['metrics']['ground_truth'])
        self.assertEqual({f['integrity'] for f in r['files']},{'ground_truth_unavailable'})

if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ReleaseChecks))
    (OUT/'engine-checks.json').write_text(json.dumps({'python':sys.version,'checks':result.testsRun,'errors':len(result.errors),
        'failures':len(result.failures),'success':result.wasSuccessful(),'measured_runs':MEASURED,'hardware_tests':0},indent=2))
    sys.exit(0 if result.wasSuccessful() else 1)
