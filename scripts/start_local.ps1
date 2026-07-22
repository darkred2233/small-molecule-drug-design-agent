param(
    [int]$Port = 8000
)

$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    throw "Project virtual environment is missing. Run scripts\\install_local_tools.ps1 first."
}
Set-Location $root
$env:PYTHONPATH = Join-Path $root 'src'
& $python -m uvicorn medagent.api.app:create_app --factory --host 127.0.0.1 --port $Port
