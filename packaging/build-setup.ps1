param([Parameter(Mandatory=$true)][string]$Archive,[Parameter(Mandatory=$true)][string]$Destination)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
& $compiler /nologo /optimize+ /target:winexe /platform:x64 /reference:Microsoft.CSharp.dll /reference:System.Windows.Forms.dll /reference:System.IO.Compression.dll ("/win32manifest:"+(Join-Path $root 'native\app.manifest')) ("/win32icon:"+(Join-Path $root 'native\RecoverX.ico')) ("/resource:"+(Resolve-Path -LiteralPath $Archive).Path+",payload.zip") ("/out:"+[IO.Path]::GetFullPath($Destination)) (Join-Path $PSScriptRoot 'Setup.cs')
if($LASTEXITCODE){throw 'Setup compilation failed.'}
