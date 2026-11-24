"""Bounded MBR/EBR/GPT byte ranges for both engines, including 4Kn media."""
from dataclasses import dataclass
import struct
import zlib

@dataclass(frozen=True)
class Span:
    start: int
    size: int
    label: str

def layout(image, sector):
    if sector not in (512, 1024, 2048, 4096):
        raise ValueError("Unsupported logical sector size.")
    length = image.stat().st_size
    with image.open('rb') as src:
        def read(offset, size):
            if offset < 0 or offset + size > length:
                raise ValueError("Partition metadata extends outside the image.")
            src.seek(offset)
            value = src.read(size)
            if len(value) != size:
                raise ValueError("Incomplete partition metadata.")
            return value
        if length < 512:
            raise ValueError("The image is smaller than a disk sector.")
        boot = read(0,512)
        def entries(block):
            return [(block[i+4], *struct.unpack_from('<II',block,i+8)) for i in range(446,510,16)]
        table = entries(boot)
        if boot[510:] != b'\x55\xaa' or not any(t and n for t,_,n in table):
            return [Span(0,length,'Whole image')]
        # Boot sectors without a partition table may contain executable boot code here.
        if boot[:1] in (b'\xeb',b'\xe9') and (boot[3:11] in (b'NTFS    ',b'EXFAT   ') or
                (struct.unpack_from('<H',boot,11)[0] in (512,1024,2048,4096) and boot[16] in (1,2))):
            return [Span(0,length,'Volume')]
        spans=[]
        def add(start, sectors, name):
            if start <= 0 or sectors <= 0 or (start+sectors)*sector > length:
                raise ValueError("A partition extends outside the image. Check the logical sector size.")
            spans.append(Span(start*sector,sectors*sector,name))
        if any(t==0xee for t,_,_ in table):
            hdr=bytearray(read(sector,sector))
            if hdr[:8]!=b'EFI PART':
                raise ValueError("The GPT header is missing. Check the image sector size.")
            hsize,crc=struct.unpack_from('<II',hdr,12)
            hdr[16:20]=bytes(4)
            if not 92<=hsize<=sector or zlib.crc32(hdr[:hsize])!=crc:
                raise ValueError("The GPT header checksum failed.")
            lba,count,width,crc=struct.unpack_from('<QIII',hdr,72)
            if not 0<count<=16384 or not 128<=width<=4096 or count*width>16*1024**2:
                raise ValueError("Invalid GPT entry array.")
            array=read(lba*sector,count*width)
            if zlib.crc32(array)!=crc:
                raise ValueError("The GPT partition array checksum failed.")
            for i in range(count):
                entry=array[i*width:(i+1)*width]
                if any(entry[:16]):
                    start,end=struct.unpack_from('<QQ',entry,32)
                    add(start,end-start+1,'GPT partition '+str(i+1))
        else:
            extended=(5,15,133)
            for i,(typ,start,count) in enumerate(table,1):
                if not typ or not count:
                    continue
                if typ not in extended:
                    add(start,count,'MBR partition '+str(i))
                    continue
                base=node=start
                seen=set()
                while node:
                    if node in seen or len(seen)>256 or not base<=node<base+count:
                        raise ValueError("Invalid extended partition chain.")
                    seen.add(node)
                    record=read(node*sector,512)
                    if record[510:]!=b'\x55\xaa':
                        raise ValueError("Invalid extended partition signature.")
                    first,link,*_=entries(record)
                    if first[0] and first[2]:
                        if node+first[1]+first[2]>base+count:
                            raise ValueError("Logical partition exceeds its container.")
                        add(node+first[1],first[2],'Logical partition '+str(len(seen)))
                    node=base+link[1] if link[0] in extended and link[2] else 0
        spans.sort(key=lambda p:p.start)
        if any(a.start+a.size>b.start for a,b in zip(spans,spans[1:])):
            raise ValueError("Overlapping partitions cannot be scanned safely.")
        return spans or [Span(0,length,'Whole image')]
