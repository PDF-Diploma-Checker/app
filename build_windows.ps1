# Usage: .\build_windows.ps1 [base|cpu]
param([ValidateSet("base", "cpu")][string]$Variant = "base")

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Run($exe, $arguments) {
    & $exe @arguments
    if ($LASTEXITCODE -ne 0) { throw "Polecenie nie powiodlo sie: $exe $arguments" }
}

$useUv = (Get-Command uv -ErrorAction SilentlyContinue) -and (Test-Path uv.lock) -and -not $env:VIRTUAL_ENV

if ($useUv) {
    $syncArgs = @("sync", "--frozen", "--no-dev")
    if ($Variant -eq "cpu") { $syncArgs += @("--extra", "cpu") }
    Run "uv" $syncArgs
    Run "uv" @("pip", "install", "pyinstaller")
    $pyExe = "uv"
    $pyPre = @("run", "--no-sync", "python")
} else {
    Run "python" @("-m", "pip", "install", "pyinstaller")
    $pyExe = "python"
    $pyPre = @()
}

function RunPy($arguments) { Run $pyExe ($pyPre + $arguments) }

RunPy @("tools/check_imports.py")
RunPy @("-m", "PyInstaller", "--noconfirm", "DiplomaChecker.spec")

$env:QT_QPA_PLATFORM = "offscreen"
$p = Start-Process ".\dist\DiplomaChecker\DiplomaChecker.exe" -ArgumentList "--smoke-test" -Wait -PassThru
Remove-Item Env:QT_QPA_PLATFORM
if (Test-Path smoke_test.log) { Get-Content smoke_test.log }
if ($p.ExitCode -ne 0) { throw "Smoke test nie przeszedl (kod $($p.ExitCode))" }

$zip = "DiplomaChecker-windows-$Variant.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path "dist\DiplomaChecker" -DestinationPath $zip
Write-Host "Gotowe: $zip"