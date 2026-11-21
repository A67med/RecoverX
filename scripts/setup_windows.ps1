# RecoverX v0.4 Windows setup, run from SETUP_WINDOWS.cmd (double-click).
# - Uses ONLY official downloads (Sleuth Kit release ZIP, verified by SHA-256) and PyPI packages.
# - Runs as the normal user: never elevates, never changes UAC/security settings,
#   never formats, mounts or writes to any disk. USB imaging asks for elevation
#   separately, only at the moment you start an acquisition.
# - Never installs WSL or a Linux distribution. Installing TestDisk inside an
#   existing WSL distribution happens only after you type Y.
param([switch]$NonInteractive, [switch]$NoShortcut)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $root
$tools = Join-Path $root 'tools'
New-Item -ItemType Directory -Path $tools -Force | Out-Null
$PyCheck = 'import sys; sys.exit(0 if (3, 11) <= sys.version_info[:2] < (3, 14) and sys.maxsize > 2**32 else 1)'

function Step([string]$text) { Write-Host ''; Write-Host "==> $text" -ForegroundColor Cyan }

function Find-Python {
    # Python 3.12 (64-bit) is the supported target; 3.11 and 3.13 also work.
    # Works with the classic py launcher and the new Python install manager.
    $checks = @(
        @{ Exe = 'py'; Extra = @('-V:3.12') }, @{ Exe = 'py'; Extra = @('-3.12') },
        @{ Exe = 'py'; Extra = @('-3.13') }, @{ Exe = 'py'; Extra = @('-3.11') },
        @{ Exe = 'python3.12'; Extra = @() }, @{ Exe = 'python'; Extra = @() }, @{ Exe = 'python3'; Extra = @() }
    )
    foreach ($check in $checks) {
        if (-not (Get-Command $check.Exe -ErrorAction SilentlyContinue)) { continue }
        try {
            $a = $check.Extra
            & $check.Exe @a -c $PyCheck 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) { return $check }
        } catch { }
    }
    Write-Host 'Python detection diagnostics:' -ForegroundColor Yellow
    try { & py list } catch { }
    try { & python --version } catch { }
    throw ('Compatible 64-bit Python not found. Install Python 3.12 (64-bit): open PowerShell and run ' +
           '"py install 3.12" (Python install manager), or download "Windows installer (64-bit)" from ' +
           'https://www.python.org/downloads/windows/ and tick "Add python.exe to PATH". Then run setup again.')
}

function Get-OfficialZip([string]$filename, [string]$url, [string]$sha256) {
    $downloadDir = Join-Path $root 'downloads'
    New-Item -ItemType Directory -Path $downloadDir -Force | Out-Null
    $archive = Join-Path $downloadDir $filename
    if (-not (Test-Path -LiteralPath $archive)) {
        Write-Host "Downloading official package: $filename"
        try {
            [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
            (New-Object System.Net.WebClient).DownloadFile($url, $archive)
        }
        catch {
            Remove-Item -LiteralPath $archive -Force -ErrorAction SilentlyContinue
            throw "Cannot download $filename. Download it from $url into $downloadDir and run setup again. Details: $_"
        }
    } else { Write-Host "Using local ZIP: $filename" }
    $sha = [System.Security.Cryptography.SHA256]::Create()
    $fs = [System.IO.File]::OpenRead($archive)
    try { $hash = -join ($sha.ComputeHash($fs) | ForEach-Object { $_.ToString('x2') }) } finally { $fs.Dispose(); $sha.Dispose() }
    if ($hash -ne $sha256.ToLowerInvariant()) {
        throw "SHA-256 mismatch for $filename (expected $sha256; got $hash). Delete the ZIP and obtain the official release."
    }
    return $archive
}

function Install-Tsk {
    $dest = Join-Path $tools 'tsk'
    if (Test-Path -LiteralPath (Join-Path $dest 'tsk_recover.exe')) { return }
    # SHA-256 of the official Sleuth Kit 4.15.0 Windows release ZIP (also recorded by the Scoop bucket).
    $zip = Get-OfficialZip 'sleuthkit-4.15.0-win32.zip' `
        'https://github.com/sleuthkit/sleuthkit/releases/download/sleuthkit-4.15.0/sleuthkit-4.15.0-win32.zip' `
        'c2ebab8105b893d97bd8ce35b88e01985e2a106efc97f03adf95840a631b20ce'
    $temp = Join-Path $env:TEMP ('RecoverX_' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $temp -Force | Out-Null
    try {
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        [System.IO.Compression.ZipFile]::ExtractToDirectory($zip, $temp)
        $exe = Get-ChildItem -Path $temp -Filter 'tsk_recover.exe' -File -Recurse | Select-Object -First 1
        if ($null -eq $exe) { throw 'tsk_recover.exe was not found inside the Sleuth Kit ZIP' }
        New-Item -ItemType Directory -Path $dest -Force | Out-Null
        Copy-Item -Path (Join-Path $exe.DirectoryName '*') -Destination $dest -Recurse -Force  # EXEs + DLLs together
    } finally { Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue }
}

function Test-Tsk {
    foreach ($name in @('tsk_recover.exe', 'mmls.exe', 'fsstat.exe', 'fls.exe')) {
        $p = Join-Path $tools "tsk\$name"
        if (-not (Test-Path -LiteralPath $p)) { throw "Required Sleuth Kit program missing: $name" }
    }
    $out = & (Join-Path $tools 'tsk\tsk_recover.exe') -V 2>&1 | Out-String
    if ($out -notmatch 'ver\s+[\d.]+') {
        throw ("tsk_recover.exe is installed but did not run correctly. Output: $out`n" +
               'Install the Microsoft Visual C++ Redistributable (x86) from https://aka.ms/vs/17/release/vc_redist.x86.exe and retry.')
    }
    Write-Host ("Sleuth Kit OK: " + ($out.Trim() -split "`n")[0]) -ForegroundColor Green
}

function Test-PhotoRec {
    $wsl = Join-Path $env:SystemRoot 'System32\wsl.exe'
    if (-not (Test-Path -LiteralPath $wsl)) {
        Write-Warning 'WSL is not installed. PhotoRec carving is unavailable; TSK recovery still works.'
        Write-Host '  To enable PhotoRec yourself: run "wsl --install -d Ubuntu-24.04" in an administrator PowerShell, reboot,'
        Write-Host '  finish the Ubuntu first-run (create a normal user), then run SETUP_WINDOWS.cmd again.'
        return
    }
    $probe = 'test $(id -u) -ne 0 || exit 77; command -v photorec >/dev/null || exit 3; photorec /version | head -n 3'
    $out = & $wsl --exec /bin/sh -c $probe 2>&1 | Out-String
    $code = $LASTEXITCODE
    if ($code -eq 0) { Write-Host ('PhotoRec (WSL) OK: ' + (($out -replace "`0", '').Trim() -split "`n")[0]) -ForegroundColor Green; return }
    if ($code -eq 77) {
        Write-Warning 'The default WSL distribution logs in as root. RecoverX runs PhotoRec only as a normal Linux user.'
        Write-Host '  Create a normal user in Ubuntu and make it the default user, then run setup again.'
        return
    }
    if ($code -eq 3) {
        Write-Warning 'TestDisk/PhotoRec is not installed in the default WSL distribution.'
        if ($NonInteractive) { Write-Host '  Install it with: wsl -u root apt-get install -y testdisk'; return }
        $answer = Read-Host 'Install the "testdisk" package (contains PhotoRec) in your default WSL distribution now? [y/N]'
        if ($answer -match '^(y|yes)$') {
            & $wsl -u root --exec /bin/sh -c 'apt-get update && apt-get install -y testdisk'
            if ($LASTEXITCODE -eq 0) { Write-Host 'TestDisk installed in WSL.' -ForegroundColor Green }
            else { Write-Warning 'TestDisk installation failed. Install it manually: wsl -u root apt-get install -y testdisk' }
        } else { Write-Host '  Skipped. Install it later with: wsl -u root apt-get install -y testdisk' }
        return
    }
    Write-Warning ("WSL did not respond correctly (exit $code). PhotoRec is unavailable until WSL works. Output: " + ($out -replace "`0", '').Trim())
}

try {
    Write-Host '=============================================================='
    Write-Host '   RecoverX v0.4 for Windows - one-time setup'
    Write-Host '   No disk is formatted, mounted or modified by this setup.'
    Write-Host '=============================================================='
    if ($root.Length -gt 110) {
        Write-Warning "The RecoverX folder path is long ($($root.Length) characters): $root"
        Write-Warning 'If installation fails with path errors, move the folder to a short path such as C:\RecoverX.'
    }
    Step 'Finding 64-bit Python 3.12'
    $py = Find-Python
    $pyArgs = $py.Extra
    $ver = & $py.Exe @pyArgs -c 'import sys, platform; print(platform.python_version(), platform.architecture()[0])'
    Write-Host "Using: $($py.Exe) $($pyArgs -join ' ')  ($ver)"

    Step 'Installing The Sleuth Kit 4.15.0 (official ZIP, SHA-256 verified)'
    Install-Tsk
    Test-Tsk

    Step 'Preparing the private Python environment (.venv)'
    $venv = Join-Path $root '.venv'
    $pyLocal = Join-Path $venv 'Scripts\python.exe'
    $healthy = $false
    if (Test-Path -LiteralPath $pyLocal) {
        & $pyLocal -c $PyCheck 2>$null
        $healthy = $LASTEXITCODE -eq 0
        if ($healthy) { & $pyLocal -m pip --version 2>$null | Out-Null; $healthy = $LASTEXITCODE -eq 0 }
    }
    if (-not $healthy) {
        if (Test-Path -LiteralPath $venv) {
            $backup = '.venv.broken-' + [guid]::NewGuid().ToString('N').Substring(0, 8)
            Rename-Item -LiteralPath $venv -NewName $backup
            Write-Host "Existing unusable environment kept as $backup (you may delete it)."
        }
        & $py.Exe @pyArgs -m venv $venv
        if ($LASTEXITCODE -ne 0) { throw 'Could not create the Python environment' }
    }
    Step 'Installing RecoverX Python dependencies'
    $constraints = Join-Path $root 'constraints-windows.txt'
    $pipArgs = @('-m', 'pip', 'install', '--disable-pip-version-check', '-r', (Join-Path $root 'requirements-windows.txt'))
    if (Test-Path -LiteralPath $constraints) { $pipArgs += @('-c', $constraints) }
    & $pyLocal @pipArgs
    if ($LASTEXITCODE -ne 0 -and (Test-Path -LiteralPath $constraints)) {
        Write-Warning 'Tested package versions could not be installed; retrying with the newest compatible versions.'
        & $pyLocal -m pip install --disable-pip-version-check -r (Join-Path $root 'requirements-windows.txt')
    }
    if ($LASTEXITCODE -ne 0) { throw 'Could not install required Python packages (check your internet connection).' }
    & $pyLocal -c 'import recoverx, streamlit, sklearn, pandas, reportlab, PIL; print(recoverx.__version__)'
    if ($LASTEXITCODE -ne 0) { throw 'RecoverX could not be imported after installation.' }

    Step 'Activating the bundled CART model (JSON, validated)'
    $env:RECOVERX_HOME = Join-Path $env:LOCALAPPDATA 'RecoverX'
    & $pyLocal (Join-Path $root 'scripts\install_bundled_model.py')
    if ($LASTEXITCODE -ne 0) { Write-Warning 'CART model activation failed. Rule-v1 and all fixed strategies remain available.' }

    Step 'Checking PhotoRec through WSL (optional)'
    Test-PhotoRec

    Step 'Creating the desktop shortcut'
    $desktop = [Environment]::GetFolderPath('Desktop')
    if ($NoShortcut) { Write-Host 'Skipped (-NoShortcut).' }
    elseif ($desktop -and (Test-Path -LiteralPath $desktop)) {
        $shell = New-Object -ComObject WScript.Shell
        $shortcut = $shell.CreateShortcut((Join-Path $desktop 'RecoverX.lnk'))
        $shortcut.TargetPath = (Join-Path $root 'START_RECOVERX_WINDOWS.cmd')
        $shortcut.WorkingDirectory = $root
        $shortcut.Description = 'RecoverX - Quick Recovery'
        $shortcut.IconLocation = (Join-Path $root 'assets\recoverx.ico') + ',0'
        $shortcut.WindowStyle = 7
        $shortcut.Save()
        Write-Host "Desktop shortcut: $desktop\RecoverX.lnk"
    }
    Write-Host ''
    Write-Host 'SUCCESS: RecoverX is ready. Double-click the RecoverX desktop icon or START_RECOVERX_WINDOWS.cmd.' -ForegroundColor Green
    exit 0
} catch {
    Write-Host ''
    Write-Host "SETUP ERROR: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host 'No drives were formatted or changed by this installer.'
    exit 1
}
