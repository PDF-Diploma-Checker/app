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

function Get-CudaArchitectures {
    # machine code for Pascal to Ada (plus Blackwell when nvcc knows it) and PTX that newer cards compile at run time
    $archs = "61-real;70-real;75-real;80-real;86-real;89-real"
    $release = [regex]::Match((& nvcc --version | Out-String), "release (\d+)\.(\d+)")
    if ($release.Success -and ([int]$release.Groups[1].Value * 100 + [int]$release.Groups[2].Value) -ge 1208) {
        $archs += ";120-real"
    }
    return "$archs;89-virtual"
}

function Copy-CudaRuntime($llamaLib) {
    # ggml-cuda.dll loads cudart/cublas by name. Without its own copies it takes whatever CUDA is on the user's
    # PATH (an older toolkit crashes it) or fails on a computer without a toolkit. The copies come from the toolkit
    # it was compiled with and sit next to it, in the folder llama_cpp puts first on PATH.
    $bin = Split-Path (Get-Command nvcc).Source
    $dlls = @(Get-ChildItem -Path (Join-Path $bin "*"), (Join-Path $bin "x64\*") -Include "cudart64_*.dll", "cublas64_*.dll", "cublasLt64_*.dll" -File -ErrorAction SilentlyContinue)
    if ($dlls.Count -lt 3) { throw "Nie znaleziono bibliotek cudart/cublas/cublasLt CUDA Toolkit w $bin." }
    $dlls | Copy-Item -Destination $llamaLib -Force
    Write-Host "Biblioteki CUDA dolaczone do llama_cpp: $($dlls.Name -join ', ')"
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
        # GGML_NATIVE=OFF + a fixed instruction set: by default llama.cpp is compiled for the CPU of the build machine
        # (AVX-512 on many of them), and the model then crashes on a user's CPU without it (0xc000001d, illegal
        # instruction). AVX2/FMA/F16C runs on practically every x86-64 CPU since ~2015.
        $cpuFlags = "-DGGML_NATIVE=OFF -DGGML_AVX=ON -DGGML_AVX2=ON -DGGML_FMA=ON -DGGML_F16C=ON"
        if ($name -eq "cpu") { $syncArgs += @("--extra", "cpu"); $env:CMAKE_ARGS = $cpuFlags }
        # GGML_CUDA_NO_VMM: without it ggml-cuda.dll links nvcuda.dll (the NVIDIA driver) directly, so llama_cpp cannot
        # even be imported on a computer without an NVIDIA driver - a build machine without a GPU (GitHub Actions)
        # or a user who installed the gpu variant on another card. With it the driver is loaded at run time by cudart.
        if ($name -eq "gpu") { $syncArgs += @("--extra", "gpu"); $env:CMAKE_ARGS = "-DGGML_CUDA=on -DGGML_CUDA_NO_VMM=ON -DGGML_NATIVE=OFF -DCMAKE_CUDA_ARCHITECTURES=$(Get-CudaArchitectures)" }
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
        # without an NVIDIA card (GitHub Actions) there is no device to offload to; check_cuda_archs below still
        # fails when ggml-cuda.dll is missing
        if ($LASTEXITCODE -ne 0 -and (Get-Command nvidia-smi -ErrorAction SilentlyContinue)) {
            throw "llama-cpp-python w tym srodowisku jest zbudowany BEZ CUDA. Usun .venv-build-gpu, wykonaj 'uv cache clean llama-cpp-python' i uruchom ponownie."
        }
        $llamaLib = & $python -c "import llama_cpp, os; print(os.path.join(os.path.dirname(llama_cpp.__file__), 'lib'))"
        # Without an architecture list llama.cpp is compiled for the GPU of this machine only, and the detailed mode
        # crashes on every other card (also with 0 layers on the GPU).
        & $python tools/check_cuda_archs.py (Join-Path $llamaLib "ggml-cuda.dll")
        if ($LASTEXITCODE -ne 0) {
            throw "ggml-cuda.dll nie ma kodu dla popularnych kart. Usun .venv-build-gpu, wykonaj 'uv cache clean llama-cpp-python' i uruchom ponownie."
        }
        Copy-CudaRuntime $llamaLib
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