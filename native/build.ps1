$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
$framework = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319'
$wpf = Join-Path $framework 'WPF'
$compiler = Join-Path $framework 'csc.exe'
$references = @('PresentationCore','PresentationFramework','WindowsBase') | ForEach-Object { '/reference:' + (Join-Path $wpf ($_ + '.dll')) }
$references += @('System','System.Core','System.Xaml','System.Xml','System.Xml.Linq','System.Management','System.Web.Extensions','System.Windows.Forms','System.Drawing') | ForEach-Object { '/reference:' + $_ + '.dll' }
$source = Get-ChildItem -LiteralPath $PSScriptRoot -Filter '*.cs' | ForEach-Object FullName
$resources = @('Icons.svg','Hero.xaml','Theme.xaml') | ForEach-Object { '/resource:'+(Join-Path $PSScriptRoot $_)+','+$_ }
& $compiler /nologo /optimize+ /platform:x64 /target:winexe /codepage:65001 ("/out:"+(Join-Path $project 'RecoverX.exe')) ("/win32manifest:"+(Join-Path $PSScriptRoot 'app.manifest')) ("/win32icon:"+(Join-Path $PSScriptRoot 'RecoverX.ico')) @references @resources @source
if($LASTEXITCODE){throw 'Desktop compilation failed.'}
$tests = Join-Path $project 'validation\DesktopChecks.cs'
if(Test-Path $tests) {
    & $compiler /nologo /optimize+ /platform:x64 /target:exe /codepage:65001 ("/out:"+(Join-Path $project 'DesktopChecks.exe')) ("/reference:"+(Join-Path $project 'RecoverX.exe')) @references $tests
    if($LASTEXITCODE){throw 'Validation harness compilation failed.'}
}
