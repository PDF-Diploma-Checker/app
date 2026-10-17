# Usage: .\build_windows.ps1 [base|cpu|gpu|all]
#   base - no AI libraries (rule-based analysis only)
#   cpu  - base + torch (CPU wheels), llama-cpp-python, sentence-transformers
#   gpu  - same as cpu, but torch with CUDA and llama-cpp-python built with CUDA
#          (needs the CUDA Toolkit: `nvcc` must be on PATH, plus Visual Studio Build Tools; the zip is several GB)
#   all  - base, cpu and gpu, one after another
# Every variant gets its own environment (.venv-build-<variant>) and its own output folder
# (dist\<variant>), so the variants never mix and your development venv is left alone.
param([ValidateSet("base", "cpu", "gpu", "all")][string]$Variant = "base")

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Run($exe, $arguments) {
    & $exe @arguments
    if ($LASTEXITCODE -ne 0) { throw "Polecenie nie powiodlo sie: $exe $arguments" }
}

$haveUv = [bool](Get-Command uv -ErrorAction SilentlyContinue) -and (Test-Path uv.lock)
if ($Variant -eq "all" -and -not $haveUv) {
    throw "'all' wymaga uv i uv.lock (osobne srodowisko dla kazdego wariantu). Zbuduj warianty osobno."
}
if (($Variant -eq "gpu" -or $Variant -eq "all") -and -not (Get-Command nvcc -ErrorAction SilentlyContinue)) {
    throw "Wariant gpu wymaga CUDA Toolkit (brak 'nvcc' w PATH): llama-cpp-python jest kompilowany z CUDA. Zainstaluj toolkit albo zbuduj tylko base/cpu."
}

function Build-Variant($name) {
    Write-Host ""
    Write-Host "=== Wariant: $name ==="

    if ($haveUv) {
        $venv = ".venv-build-$name"
        # an activated dev venv must not leak into the build
        Remove-Item Env:VIRTUAL_ENV -ErrorAction SilentlyContinue
        $env:UV_PROJECT_ENVIRONMENT = $venv
        # llama-cpp-python is compiled from source and uv's wheel cache does not know about CMAKE_ARGS:
        # drop a cached build, otherwise a CUDA-less wheel could be reused for gpu (or the other way round).
        if (-not (Test-Path $venv) -and ($name -eq "cpu" -or $name -eq "gpu")) {
            & uv cache clean llama-cpp-python
        }
        # "uv sync" is exact: packages that are not part of this variant (e.g. CUDA torch) are removed.
        $syncArgs = @("sync", "--frozen", "--no-dev")
        if ($name -eq "cpu") { $syncArgs += @("--extra", "cpu") }
        if ($name -eq "gpu") { $syncArgs += @("--extra", "gpu"); $env:CMAKE_ARGS = "-DGGML_CUDA=on" }
        try {
            Run "uv" $syncArgs
        } finally {
            Remove-Item Env:CMAKE_ARGS -ErrorAction SilentlyContinue
        }
        $python = Join-Path $PSScriptRoot "$venv\Scripts\python.exe"
        Run "uv" @("pip", "install", "--python", $python, "pyinstaller")
    } else {
        # No uv: builds with whatever is installed in the current Python environment.
        Run "python" @("-m", "pip", "install", "pyinstaller")
        $python = "python"
    }

    if ($name -eq "gpu") {
        & $python -c "import sys, llama_cpp; sys.exit(0 if llama_cpp.llama_supports_gpu_offload() else 1)"
        if ($LASTEXITCODE -ne 0) {
            throw "llama-cpp-python w tym srodowisku jest zbudowany BEZ CUDA. Usun .venv-build-gpu, wykonaj 'uv cache clean llama-cpp-python' i uruchom ponownie."
        }
    }

    Run $python @("tools/check_imports.py")
    Run $python @("-m", "PyInstaller", "--noconfirm", "--distpath", "dist\$name", "--workpath", "build\$name", "DiplomaChecker.spec")

    if (Test-Path smoke_test.log) { Remove-Item smoke_test.log }
    $env:QT_QPA_PLATFORM = "offscreen"
    $p = Start-Process ".\dist\$name\DiplomaChecker\DiplomaChecker.exe" -ArgumentList "--smoke-test" -Wait -PassThru
    Remove-Item Env:QT_QPA_PLATFORM
    if (Test-Path smoke_test.log) { Get-Content smoke_test.log }
    if ($p.ExitCode -ne 0) { throw "Smoke test nie przeszedl (kod $($p.ExitCode))" }

    $zip = "DiplomaChecker-windows-$name.zip"
    if (Test-Path $zip) { Remove-Item $zip }
    # Compress-Archive in Windows PowerShell 5.1 fails above 2 GB; the tar that ships with Windows 10+ does not.
    if (Get-Command tar -ErrorAction SilentlyContinue) {
        Run "tar" @("-a", "-c", "-f", $zip, "-C", "dist\$name", "DiplomaChecker")
    } else {
        Compress-Archive -Path "dist\$name\DiplomaChecker" -DestinationPath $zip
    }
    $zipMb = [math]::Round((Get-Item $zip).Length / 1MB)
    Write-Host "Gotowe: $zip ($zipMb MB)"
}

if ($Variant -eq "all") {
    Build-Variant "base"
    Build-Variant "cpu"
    Build-Variant "gpu"
} else {
    Build-Variant $Variant
}