param([string]$OutputDirectory = $PSScriptRoot)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$vswherePath = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
$compilerRoot = & $vswherePath -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (!$compilerRoot) { throw 'MSVC x64 Build Tools are required.' }
$buildOutput = [System.IO.Path]::GetFullPath($OutputDirectory)
[System.IO.Directory]::CreateDirectory($buildOutput) | Out-Null
$buildCommand = 'call "{0}\Common7\Tools\VsDevCmd.bat" -arch=amd64 -host_arch=amd64 >nul && cl.exe /nologo /std:c++17 /utf-8 /W4 /WX /EHsc /O2 /MT /LD /Fo"{1}\\" /Fe"{1}\WindowDockDesktop.dll" "{2}\filter.cpp" "{2}\bridge.cpp" "{2}\recycle.cpp" /link shell32.lib ole32.lib user32.lib comctl32.lib uuid.lib' -f $compilerRoot, $buildOutput, $PSScriptRoot
Push-Location -LiteralPath $buildOutput
try {
    & cmd.exe /d /s /c $buildCommand
    if ($LASTEXITCODE -ne 0) { throw 'Native desktop component build failed.' }
} finally {
    Pop-Location
}
