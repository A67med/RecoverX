<#
.SYNOPSIS
  Provision the dependencies of the RecoverX native Windows desktop (Recovery Studio)
  from official upstream sources, verify every download against a pinned SHA-256,
  and build RecoverX.exe.

.DESCRIPTION
  Creates, next to the source tree (all are git-ignored):
    runtime\        CPython 3.12.7 embeddable (x64) + pytsk3 20260715 (cp312, win_amd64)
    tools\tsk\      The Sleuth Kit 4.15.0 Windows binaries (official release ZIP, bin\)
    tools\photorec\ PhotoRec 7.2 (official TestDisk 7.2 win64 build) unless a native
                    MinGW build (see docs\BUILD_WINDOWS_DESKTOP.txt) is already present
    vendor-source\  Corresponding upstream source archives (GPL source availability)
    RecoverX.exe, DesktopChecks.exe   built with the .NET Framework 4.8 C# compiler

  Nothing is executed from a download before its hash has been verified.
  Re-running is safe: verified files already present are reused.

.PARAMETER SkipBuild
  Provision dependencies only; do not compile the WPF desktop.
#>
[CmdletBinding()]
param([switch]$SkipBuild)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$downloads = Join-Path $root 'downloads'
New-Item -ItemType Directory -Force $downloads | Out-Null

# name, URL, SHA-256 (pinned 2026-11-24 from the official publishers)
$artifacts = @(
  @{ Name='python-3.12.7-embed-amd64.zip'; Url='https://www.python.org/ftp/python/3.12.7/python-3.12.7-embed-amd64.zip';
     Sha='0d57bb6cb078b74d23dbfe91f77d6780d45bed328911609f1f7ee2ba1606bf44' },
  @{ Name='pytsk3-20260715-cp312-cp312-win_amd64.whl'; Url='https://files.pythonhosted.org/packages/cp312/p/pytsk3/pytsk3-20260715-cp312-cp312-win_amd64.whl';
     Sha='65c739093ac447cdd81dbaabac9b000140bf84f52e7536cda5e975c665c20eb7' },
  @{ Name='sleuthkit-4.15.0-win32.zip'; Url='https://github.com/sleuthkit/sleuthkit/releases/download/sleuthkit-4.15.0/sleuthkit-4.15.0-win32.zip';
     Sha='c2ebab8105b893d97bd8ce35b88e01985e2a106efc97f03adf95840a631b20ce' },
  @{ Name='sleuthkit-4.15.0.tar.gz'; Url='https://github.com/sleuthkit/sleuthkit/releases/download/sleuthkit-4.15.0/sleuthkit-4.15.0.tar.gz';
     Sha='3a8c1e7d18a9b81f3e5e8aa78313974aceaafc6e051d636bc92cd7168286eca9' },
  @{ Name='testdisk-7.2.win64.zip'; Url='https://www.cgsecurity.org/testdisk-7.2.win64.zip';
     Sha='e97e203ce77b6b1a3a37d01beccf069dc6c4632b579ffbb82ae739cdda229f38' },
  @{ Name='testdisk-7.2.tar.bz2'; Url='https://www.cgsecurity.org/testdisk-7.2.tar.bz2';
     Sha='f8343be20cb4001c5d91a2e3bcd918398f00ae6d8310894a5a9f2feb813c283f' }
)

function Get-Verified($a) {
  $file = Join-Path $downloads $a.Name
  if ((Test-Path $file) -and ((Get-FileHash $file -Algorithm SHA256).Hash.ToLower() -eq $a.Sha)) { return $file }
  $url = $a.Url
  if ($a.Name -like 'pytsk3-*') {
    # Resolve the exact wheel URL from PyPI's JSON API (the CDN path contains a content hash).
    $meta = Invoke-RestMethod 'https://pypi.org/pypi/pytsk3/20260715/json'
    $url = ($meta.urls | Where-Object { $_.filename -eq $a.Name }).url
    if (-not $url) { throw "PyPI does not list $($a.Name)" }
  }
  Write-Host "Downloading $($a.Name)"
  Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile "$file.part"
  $hash = (Get-FileHash "$file.part" -Algorithm SHA256).Hash.ToLower()
  if ($hash -ne $a.Sha) { Remove-Item "$file.part"; throw "SHA-256 mismatch for $($a.Name): $hash" }
  Move-Item -Force "$file.part" $file
  return $file
}

function Expand-Into($zip, $dest) {
  $tmp = Join-Path $downloads ('x-' + [IO.Path]::GetRandomFileName())
  $copy = "$tmp.zip"; Copy-Item $zip $copy
  Expand-Archive -LiteralPath $copy -DestinationPath $tmp -Force
  Remove-Item $copy
  return $tmp
}

$files = @{}
foreach ($a in $artifacts) { $files[$a.Name] = Get-Verified $a }

# 1. Embedded CPython + pytsk3
$runtime = Join-Path $root 'runtime'
if (-not (Test-Path (Join-Path $runtime 'python.exe'))) {
  New-Item -ItemType Directory -Force $runtime | Out-Null
  Expand-Archive -LiteralPath $files['python-3.12.7-embed-amd64.zip'] -DestinationPath $runtime -Force
}
if (-not (Get-ChildItem $runtime -Filter 'pytsk3*.pyd' -ErrorAction SilentlyContinue)) {
  $x = Expand-Into $files['pytsk3-20260715-cp312-cp312-win_amd64.whl'] $runtime
  Copy-Item -Recurse -Force (Join-Path $x '*') $runtime
  Remove-Item -Recurse -Force $x
}
# Import paths of the desktop worker (relative to runtime\); no site-packages, no user site.
Set-Content -Encoding ascii -Path (Join-Path $runtime 'python312._pth') -Value @('python312.zip', '.', '../src', '../desktop', '../validation')

# 2. The Sleuth Kit (official Windows binaries)
$tsk = Join-Path $root 'tools\tsk'
if (-not (Test-Path (Join-Path $tsk 'tsk_recover.exe'))) {
  $x = Expand-Into $files['sleuthkit-4.15.0-win32.zip'] $tsk
  New-Item -ItemType Directory -Force $tsk | Out-Null
  Copy-Item -Force (Join-Path $x 'sleuthkit-4.15.0-win32\bin\*') $tsk
  Remove-Item -Recurse -Force $x
}

# 3. PhotoRec: keep a native MinGW build if present, else the official win64 build
$pr = Join-Path $root 'tools\photorec'
if (-not ((Test-Path (Join-Path $pr 'photorec.exe')) -or (Test-Path (Join-Path $pr 'photorec_win.exe')))) {
  $x = Expand-Into $files['testdisk-7.2.win64.zip'] $pr
  New-Item -ItemType Directory -Force $pr | Out-Null
  Copy-Item -Recurse -Force (Join-Path $x 'testdisk-7.2\*') $pr
  Remove-Item -Recurse -Force $x
}

# 4. Corresponding source archives
$vs = Join-Path $root 'vendor-source'
New-Item -ItemType Directory -Force $vs | Out-Null
Copy-Item -Force $files['sleuthkit-4.15.0.tar.gz'], $files['testdisk-7.2.tar.bz2'] $vs

# 5. Build the WPF desktop and its validation harness
if (-not $SkipBuild) { & (Join-Path $root 'native\build.ps1') }

Write-Host 'RecoverX desktop dependencies are provisioned and verified.' -ForegroundColor Green
