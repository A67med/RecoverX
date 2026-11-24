"""Package the Windows Recovery Studio (after scripts/windows/provision_desktop.ps1).

The ZIP holds exactly what the installed desktop needs: the built executables,
the provisioned runtime and recovery tools, the application and worker source,
the archived CART model, validation material, licences and the corresponding
upstream source archives. Development-only material (tests, research records,
downloads, Streamlit launchers) is excluded. A SHA-256 manifest of every file is
embedded as RecoverX/FILE-HASHES.sha256.

usage: runtime\\python.exe -B packaging\\make_zip.py C:\\build\\RecoverX-Windows-x64.zip
"""
from pathlib import Path
import hashlib
import sys
import zipfile

root = Path(__file__).resolve().parents[1]
target = Path(sys.argv[1]).resolve()
if root in target.parents or target.exists():
    raise SystemExit('Choose a new ZIP outside the source folder.')

INCLUDE = ['RecoverX.exe', 'DesktopChecks.exe', 'Run validation.cmd', 'LICENSE', 'THIRD_PARTY_NOTICES.md',
           'README.md', 'runtime', 'tools', 'vendor-source', 'licenses', 'desktop', 'src', 'config',
           'validation', 'native', 'packaging', 'docs/BUILD_WINDOWS_DESKTOP.txt', 'docs/VALIDATION_RC1.txt',
           'docs/USB_HARDWARE_TEST.txt', 'research/results/exp1/models']
missing = [p for p in ('RecoverX.exe', 'runtime/python.exe', 'tools/tsk/tsk_recover.exe') if not (root / p).exists()]
if missing:
    raise SystemExit('Provision and build first (scripts/windows/provision_desktop.ps1); missing: ' + ', '.join(missing))

entries = []
for item in INCLUDE:
    base = root / item
    files = [base] if base.is_file() else sorted(p for p in base.rglob('*') if p.is_file())
    for f in files:
        rel = f.relative_to(root)
        if '__pycache__' in rel.parts or f.suffix == '.pyc' or rel.as_posix().startswith('validation/evidence/'):
            continue
        entries.append((f, rel.as_posix()))

with zipfile.ZipFile(target, 'x', zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as z:
    manifest = []
    for f, name in entries:
        z.write(f, 'RecoverX/' + name)
        with f.open('rb') as stream:
            manifest.append(hashlib.file_digest(stream, 'sha256').hexdigest() + '  ' + name)
    z.writestr('RecoverX/FILE-HASHES.sha256', '\n'.join(manifest) + '\n')
with zipfile.ZipFile(target) as z:
    if z.testzip() is not None:
        raise SystemExit('Archive verification failed.')
print(target, len(entries), 'files plus manifest')
