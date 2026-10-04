param([ValidateSet("", "cpu", "gpu")][string]$Variant = "")
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}

switch ($Variant) {
    ""    { uv sync }
    "cpu" { uv sync --extra cpu --reinstall-package llama-cpp-python }
    "gpu" { $env:CMAKE_ARGS = "-DGGML_CUDA=on"; uv sync --extra gpu --reinstall-package llama-cpp-python }
}

$env:LTP_PATH = "$env:APPDATA\DiplomaChecker\LanguageTool"
uv run python -c "from language_tool_python.download_lt import download_lt; download_lt('6.6')"
