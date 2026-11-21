#!/usr/bin/env bash
# One-time desktop integration. Safe to rerun; leaves workspace and .venv untouched.
set -Eeuo pipefail
PROJECT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export PROJECT
python3 - <<'PY'
from pathlib import Path
import os
import shutil
import subprocess

root = Path(os.environ['PROJECT'])
entry = '''[Desktop Entry]
Type=Application
Version=1.0
Name=RecoverX
GenericName=Deleted File Recovery
Comment=Open the local RecoverX forensic interface
Exec=/usr/bin/python3 "{launcher}"
Path={root}
Icon={icon}
Terminal=false
Categories=Utility;Science;
StartupNotify=true
'''.format(launcher=root / 'scripts' / 'desktop_launcher.py',
           root=root, icon=root / 'assets' / 'recoverx.svg')
applications = Path.home() / '.local' / 'share' / 'applications'
applications.mkdir(parents=True, exist_ok=True)
applications_path = applications / 'recoverx.desktop'
applications_path.write_text(entry)
applications_path.chmod(0o755)
desktop = Path.home() / 'Desktop'
if desktop.is_dir():
    desktop_path = desktop / 'RecoverX.desktop'
    desktop_path.write_text(entry)
    desktop_path.chmod(0o755)
    if shutil.which('gio'):
        subprocess.run(['gio', 'set', str(desktop_path), 'metadata::trusted', 'true'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
print('RecoverX launcher installed in the applications menu' + (' and Desktop' if desktop.is_dir() else ''))
print('You can now open RecoverX using its desktop icon. The first launch may install Python packages automatically.')
PY
# Launch once after desktop integration, without requiring more terminal commands.
exec python3 "$PROJECT/scripts/desktop_launcher.py"
