"""Construct an MBR + FAT32 disk image entirely in ordinary files. Never uses a device."""
from pathlib import Path
import hashlib
import json
import math
import struct

def fat32_fixture(folder, originals, partition_start=2048):
    folder.mkdir(parents=True, exist_ok=True)
    ss, reserved, fat_sectors, clusters = 512, 32, 520, 66558
    volume_sectors = reserved + fat_sectors * 2 + clusters
    disk = bytearray((partition_start+volume_sectors)*ss)
    part = memoryview(disk)[partition_start*ss:]
    disk[446+4] = 0x0c
    struct.pack_into('<II',disk,454,partition_start,volume_sectors)
    disk[510:512] = b'\x55\xaa'
    part[:11]=b'\xeb\x58\x90RECOVERX'
    struct.pack_into('<HBHBHHBHHHII',part,11,ss,1,reserved,2,0,0,0xf8,0,63,255,partition_start,volume_sectors)
    struct.pack_into('<IHHIHH',part,36,fat_sectors,0,0,2,1,6)
    part[64]=0x80
    part[66]=0x29
    struct.pack_into('<I',part,67,0x7458434d)
    part[71:90]=b'RX FIXTURE FAT32   '
    part[510:512]=b'\x55\xaa'
    part[6*ss:7*ss]=part[:ss]
    struct.pack_into('<I',part,ss,0x41615252)
    struct.pack_into('<III',part,ss+484,0x61417272,clusters-1,3)
    part[2*ss-2:2*ss]=b'\x55\xaa'
    for start in [reserved, reserved+fat_sectors]:
        struct.pack_into('<III',part,start*ss,0x0ffffff8,0xffffffff,0x0fffffff)
    data = (reserved+2*fat_sectors)*ss
    cluster = 10
    deleted = []
    for i,f in enumerate(sorted(originals.iterdir())):
        if not f.is_file():
            continue
        content = f.read_bytes()
        entry = data+i*32
        name = f.stem.upper().ljust(8)[:8]+f.suffix[1:].upper().ljust(3)[:3]
        part[entry:entry+11]=name.encode('ascii')
        part[entry]=0xe5
        part[entry+11]=0x20
        struct.pack_into('<H',part,entry+20,cluster>>16)
        struct.pack_into('<HI',part,entry+26,cluster&65535,len(content))
        offset=data+(cluster-2)*ss
        part[offset:offset+len(content)]=content
        cluster+=math.ceil(len(content)/ss)+16
        deleted.append({'id':f.name,'sha256':hashlib.sha256(content).hexdigest(),'size':len(content)})
    (folder/'three-deleted.img').write_bytes(disk)
    (folder/'original-hashes.json').write_text(json.dumps({'deleted':deleted}, indent=2))

if __name__=='__main__':
    here = Path(__file__).resolve().parent
    fat32_fixture(here/'sample', here/'originals')
