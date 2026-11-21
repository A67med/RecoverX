# RecoverX Windows setup, run from SETUP_WINDOWS.cmd. Uses ONLY official third-party downloads.
# Does not elevate privileges, format disks, mount devices, or write to source media.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $root
$tools = Join-Path $root 'tools'
New-Item -ItemType Directory -Path $tools -Force | Out-Null

function Find-Python {
    # Probe the actual interpreter via its exit status. Windows PowerShell 5.1 can
    # strip nested quotes from Python -c arguments; avoid that fragile pattern.
    $checks = @(
        @{ Exe = 'py'; Extra = @('-3.12') },
        @{ Exe = 'py'; Extra = @('-3.13') },
        @{ Exe = 'py'; Extra = @('-3.11') },
        @{ Exe = 'py'; Extra = @('-3') },
        @{ Exe = 'python'; Extra = @() },
        @{ Exe = 'python3'; Extra = @() }
    )
    foreach ($check in $checks) {
        $exe = $check.Exe
        $args = $check.Extra
        if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
        try {
            # No quoted string literals in -c: compatible with legacy PS argument passing.
            & $exe @args -c 'import sys; sys.exit(0 if (3, 11) <= sys.version_info[:2] < (3, 14) and sys.maxsize > 2**32 else 1)' 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) { return $check }
        } catch { }
    }
    Write-Host 'Python detection diagnostics:' -ForegroundColor Yellow
    try { & python --version } catch { }
    try { & python -c 'import sys; print(sys.version_info[:3]); print(sys.maxsize.bit_length())' } catch { }
    throw 'Compatible 64-bit Python not detected. Python 3.11, 3.12, or 3.13 x64 is required.'
}

function Get-OfficialZip([string]$filename, [string]$url, [string]$sha256 = '') {
    $downloadDir = Join-Path $root 'downloads'
    New-Item -ItemType Directory -Path $downloadDir -Force | Out-Null
    $archive = Join-Path $downloadDir $filename
    if (-not (Test-Path -LiteralPath $archive)) {
        Write-Host "Downloading official package: $filename"
        try {
            Invoke-WebRequest -Uri $url -OutFile $archive -UseBasicParsing -MaximumRedirection 5
        } catch {
            Remove-Item -LiteralPath $archive -Force -ErrorAction SilentlyContinue
            throw "Cannot download $filename. Download its ZIP from $url into $downloadDir and run setup again. Details: $_"
        }
    } else {
        Write-Host "Using local ZIP: $filename"
    }
    if ($sha256) {
        $hash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($hash -ne $sha256.ToLowerInvariant()) {
            throw "SHA-256 mismatch for $filename (expected $sha256; got $hash). Delete the ZIP and obtain the official release."
        }
    }
    $stream = [System.IO.File]::OpenRead($archive)
    try {
        $signature = New-Object byte[] 4
        if ($stream.Read($signature, 0, 4) -ne 4 -or $signature[0] -ne 80 -or $signature[1] -ne 75) {
            throw "Download $filename is not a ZIP. Delete it and retry."
        }
    } finally { $stream.Dispose() }
    return $archive
}

function Extract-Tools([string]$archive, [string]$exeName, [string]$destDir) {
    $temp = Join-Path $env:TEMP ("RecoverX_" + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $temp -Force | Out-Null
    try {
        Write-Host "Installing $exeName (no executables are run during extraction)..."
        Expand-Archive -LiteralPath $archive -DestinationPath $temp -Force
        $exe = Get-ChildItem -Path $temp -Filter $exeName -File -Recurse | Select-Object -First 1
        if ($null -eq $exe) { throw "$exeName was not found inside $archive" }
        New-Item -ItemType Directory -Path $destDir -Force | Out-Null
        # Keep EXE and dependent DLLs in the same directory.
        Copy-Item -Path (Join-Path $exe.DirectoryName '*') -Destination $destDir -Recurse -Force
        if (-not (Test-Path -LiteralPath (Join-Path $destDir $exeName))) {
            throw "Could not install $exeName"
        }
    } finally {
        Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue
    }
}

try {
    Write-Host '=========================================================='
    Write-Host '  RecoverX Windows Quick Recovery - one-time setup'
    Write-Host '=========================================================='
    $py = Find-Python
    $pyExe = $py.Exe
    $pyArgs = $py.Extra
    Write-Host "Using Python: $pyExe $($pyArgs -join ' ')"

    $tskExe = Join-Path $tools 'tsk\tsk_recover.exe'
    if (-not (Test-Path -LiteralPath $tskExe)) {
        # SHA256 from ScoopInstaller official bucket for Sleuth Kit 4.15.0, 2026.
        $tsk = Get-OfficialZip 'sleuthkit-4.15.0-win32.zip' `
            'https://github.com/sleuthkit/sleuthkit/releases/download/sleuthkit-4.15.0/sleuthkit-4.15.0-win32.zip' `
            'c2ebab8105b893d97bd8ce35b88e01985e2a106efc97f03adf95840a631b20ce'
        Extract-Tools $tsk 'tsk_recover.exe' (Join-Path $tools 'tsk')
    }

    foreach ($name in @('tsk_recover.exe','mmls.exe','fsstat.exe','fls.exe')) {
        if (-not (Test-Path -LiteralPath (Join-Path $tools "tsk\$name"))) {
            throw "Required TSK program missing: $name"
        }
    }

    $venv = Join-Path $root '.venv'
    $pyLocal = Join-Path $venv 'Scripts\python.exe'
    $healthy = $false
    if (Test-Path -LiteralPath $pyLocal) {
        & $pyLocal -c 'import sys; sys.exit(0 if (3, 11) <= sys.version_info[:2] < (3, 14) and sys.maxsize > 2**32 else 1)'
        $healthy = $LASTEXITCODE -eq 0
    }
    if (-not $healthy) {
        if (Test-Path -LiteralPath $venv) {
            $backup = '.venv.broken-' + [guid]::NewGuid().ToString('N')
            Rename-Item -LiteralPath $venv -NewName $backup
            Write-Host "Existing environment saved as $backup"
        }
        Write-Host 'Creating the private Python environment...'
        & $pyExe @pyArgs -m venv $venv
        if ($LASTEXITCODE -ne 0) { throw 'Could not create Python environment' }
    }
    Write-Host 'Installing the original RecoverX Python dependencies...'
    & $pyLocal -m pip install --disable-pip-version-check -r (Join-Path $root 'requirements-windows.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Could not install required Python packages' }

    $env:RECOVERX_HOME = Join-Path $env:LOCALAPPDATA "RecoverX"
    & $pyLocal (Join-Path $root "scripts/install_bundled_model.py")
    if ($LASTEXITCODE -ne 0) { Write-Warning "JSON CART activation failed. Rule-v1 remains available." }

    $desktop = [Environment]::GetFolderPath('Desktop')
    if ($desktop -and (Test-Path -LiteralPath $desktop)) {
        $shell = New-Object -ComObject WScript.Shell
        $shortcut = $shell.CreateShortcut((Join-Path $desktop 'RecoverX.lnk'))
        $shortcut.TargetPath = (Join-Path $root 'START_RECOVERX_WINDOWS.cmd')
        $shortcut.WorkingDirectory = $root
        $shortcut.Description = 'RecoverX Windows Quick Recovery'
        $shortcut.IconLocation = (Join-Path $root 'assets\recoverx.ico')
        $shortcut.Save()
        Write-Host "Desktop shortcut created: $desktop\RecoverX.lnk"
    }
    Write-Host 'SUCCESS: Windows setup finished. Double-click START_RECOVERX_WINDOWS.cmd or RecoverX desktop shortcut.'
    exit 0
} catch {
    Write-Host ''
    Write-Host "SETUP ERROR: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host 'No drives were formatted or changed by this installer.'
    exit 1
}
