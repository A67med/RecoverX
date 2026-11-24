"""Build upstream PhotoRec's scripted, console-free MinGW-w64 Windows CLI.
Usage: python build_photorec.py <unpacked-testdisk-7.2> <build-folder> <output.exe>
Requires x86_64-w64-mingw32 GCC, zlib and libjpeg-turbo development libraries.
"""
import concurrent.futures
from pathlib import Path
import re
import subprocess
import sys
from photorec_port import adapt

source, build, target = map(lambda arg: Path(arg).resolve(), sys.argv[1:])
build.mkdir(exist_ok=True, parents=True)
flags = """TESTDISK_LSB ENABLE_DFXML STDC_HEADERS HAVE_VSNPRINTF HAVE_SETJMP_H HAVE_ATEXIT HAVE_ATOLL HAVE_CHDIR HAVE_CHMOD
HAVE_DIRENT_H HAVE_DUP2 HAVE_ERRNO_H HAVE_FCNTL_H HAVE_FSEEKO HAVE_FTELLO HAVE_FTRUNCATE
HAVE_GETCWD HAVE_INTTYPES_H HAVE_IO_H HAVE_JPEGLIB_H HAVE_LIBJPEG HAVE_LIBZ HAVE_LOCALE_H
HAVE_MALLOC_H HAVE_MEMCHR HAVE_MEMSET HAVE_MKDIR HAVE_SETLOCALE HAVE_SIGNAL_H
HAVE_SNPRINTF HAVE_STDARG_H HAVE_STDINT_H HAVE_STDIO_H HAVE_STDLIB_H HAVE_STRCASECMP
HAVE_STRCHR HAVE_STRDUP HAVE_STRERROR HAVE_STRINGS_H HAVE_STRING_H HAVE_STRNCASECMP
HAVE_STRRCHR HAVE_STRSTR HAVE_STRTOL HAVE_STRTOUL HAVE_STRTOULL HAVE_SYS_STAT_H
HAVE_SYS_TIME_H HAVE_SYS_TYPES_H HAVE_TIME_H HAVE_UNISTD_H HAVE_UTIME HAVE_UTIME_H
HAVE_WINDOWS_H HAVE_WINDEF_H HAVE_WINBASE_H HAVE_WINIOCTL_H HAVE_ZLIB_H"""
config = ''.join('#define '+flag+' 1\n' for flag in flags.split()) + '''
#define VERSION "7.2"
#define TESTDISKDATE "February 2024"
#define PACKAGE "testdisk"
#define PACKAGE_VERSION "7.2"
#define _FILE_OFFSET_BITS 64
'''
if not (build/'config.h').exists() or (build/'config.h').read_text() != config:
    (build/'config.h').write_text(config)
(build/'win-head.h').write_text('#include <windows.h>\n#undef IN\n#undef OUT\n#undef uuid_t\n#define HAVE_VSNPRINTF 1\n#include <setjmp.h>\n')
make = (source/'src/Makefile.am').read_text().replace('\\\n',' ')
variables = dict(re.findall(r'^(\w+)\s*=\s*(.*)$',make,re.M))
def expand(name):
    return re.sub(r'\$\((\w+)\)', lambda m: expand(m[1]),variables[name])
files = expand('photorec_C_SOURCES').split()
def compile_one(filename):
    obj = build/(filename+'.o')
    unit=source/'src'/filename
    if filename in ('filegen.c','phrecn.c'):
        adjusted=adapt(filename,unit.read_text())
        unit=build/filename
        if not unit.exists() or unit.read_text()!=adjusted:
            unit.write_text(adjusted)
    if obj.exists() and obj.stat().st_mtime >= max(unit.stat().st_mtime, (build/'config.h').stat().st_mtime):
        return
    command = ['gcc','-O2','-std=gnu11','-D_FILE_OFFSET_BITS=64','-DHAVE_CONFIG_H','-include',str(build/'win-head.h'),'-I',str(build),'-I',str(source/'src'),'-c',str(unit),'-o',str(obj)]
    res = subprocess.run(command, capture_output=True, text=True)
    if res.returncode:
        raise RuntimeError(filename+'\n'+res.stderr)
with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
    list(pool.map(compile_one, files))
rsp = build/'objects.rsp'
rsp.write_text('\n'.join('"'+(build/(f+'.o')).as_posix()+'"' for f in files))
subprocess.run(['gcc','-s','-static','@'+str(rsp),'-ljpeg','-lz','-ladvapi32','-lws2_32','-o',str(target)],check=True)





