[CmdletBinding()]
param(
    [switch]$SkipPythonPackages,
    [switch]$InstallWsl
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $root ".venv\Scripts\python.exe"
$local = Join-Path $root ".local"
$downloads = Join-Path $local "downloads"
$tools = Join-Path $local "tools"
$envs = Join-Path $local "envs"
$failures = [System.Collections.Generic.List[string]]::new()

function Invoke-InstallStep {
    param([string]$Name, [scriptblock]$Action)
    try {
        Write-Host "[local-tools] $Name"
        & $Action
        if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) { throw "exit code $LASTEXITCODE" }
    } catch {
        $failures.Add("${Name}: $($_.Exception.Message)")
        Write-Warning "[local-tools] $Name failed: $($_.Exception.Message)"
    }
}

function Ensure-Venv {
    param([string]$Path)
    $venvPython = Join-Path $Path "Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $venvPython)) {
        & $python -m venv $Path
        if ($LASTEXITCODE -ne 0) { throw "unable to create virtual environment at $Path" }
    }
    return $venvPython
}

function Ensure-SourceArchive {
    param([string]$Url, [string]$Destination, [string]$ExpectedEntry)
    $expected = Join-Path $Destination $ExpectedEntry
    if (Test-Path -LiteralPath $expected) {
        Write-Host "[local-tools] reusing existing source: $Destination"
        return
    }
    if (Test-Path -LiteralPath $Destination) {
        Remove-Item -LiteralPath $Destination -Recurse -Force
    }
    $repository = $Url -replace '^https://github.com/', '' -replace '\.git$', ''
    $metadata = Invoke-RestMethod -Uri "https://api.github.com/repos/$repository" -Headers @{"User-Agent"="MedAgent-local-installer"}
    $archiveUrl = "https://api.github.com/repos/$repository/zipball/$($metadata.default_branch)"
    $archive = Join-Path $downloads "$($metadata.name)-$($metadata.default_branch).zip"
    $expanded = Join-Path $downloads "$($metadata.name)-expanded"
    Invoke-WebRequest -Uri $archiveUrl -Headers @{"User-Agent"="MedAgent-local-installer"} -OutFile $archive -TimeoutSec 60
    New-Item -ItemType Directory -Force -Path $expanded | Out-Null
    Expand-Archive -LiteralPath $archive -DestinationPath $expanded -Force
    $source = Get-ChildItem -LiteralPath $expanded -Directory | Select-Object -First 1
    if (-not $source) { throw "GitHub archive contains no source directory: $archiveUrl" }
    Move-Item -LiteralPath $source.FullName -Destination $Destination
    if (-not (Test-Path -LiteralPath $expected)) { throw "source archive lacks ${ExpectedEntry}: $archiveUrl" }
}

if (-not (Test-Path -LiteralPath $python)) {
    & py -3.11 -m venv (Join-Path $root ".venv")
}
New-Item -ItemType Directory -Force -Path $downloads, $tools, $envs | Out-Null

if (-not $SkipPythonPackages) {
    Invoke-InstallStep "project Python packages" {
        & $python -m pip install --upgrade pip
        & $python -m pip install -e "${root}.[dev,chem,rag]"
    }
}

Invoke-InstallStep "AutoDock Vina Windows binary" {
    $vinaRoot = Join-Path $tools "vina"
    $vinaExe = Join-Path $vinaRoot "vina.exe"
    if (-not (Test-Path -LiteralPath $vinaExe)) {
        $release = Invoke-RestMethod -Uri "https://api.github.com/repos/ccsb-scripps/AutoDock-Vina/releases/latest" -Headers @{"User-Agent"="MedAgent-local-installer"}
        $asset = @($release.assets | Where-Object { $_.name -match "(?i)(windows|win).*(zip|exe)$" }) | Select-Object -First 1
        if (-not $asset) { throw "the latest Vina release has no Windows archive" }
        $archive = Join-Path $downloads $asset.name
        Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $archive
        New-Item -ItemType Directory -Force -Path $vinaRoot | Out-Null
        if ($archive.EndsWith(".zip")) {
            $expanded = Join-Path $downloads "vina-expanded"
            New-Item -ItemType Directory -Force -Path $expanded | Out-Null
            Expand-Archive -LiteralPath $archive -DestinationPath $expanded -Force
            $candidate = Get-ChildItem -LiteralPath $expanded -Recurse -File -Filter "vina.exe" | Select-Object -First 1
            if (-not $candidate) { throw "Vina archive does not contain vina.exe" }
            Copy-Item -LiteralPath $candidate.FullName -Destination $vinaExe -Force
        } else {
            Copy-Item -LiteralPath $archive -Destination $vinaExe -Force
        }
    }
    & $vinaExe --version
}

Invoke-InstallStep "Open Babel isolated runtime" {
    $chemtools = Join-Path $envs "chemtools"
    $chemPython = Ensure-Venv $chemtools
    & $chemPython -m pip install --upgrade pip
    & $chemPython -m pip install --only-binary=:all: "openbabel-wheel>=3.1.1.22"
    $obabel = Join-Path $chemtools "Scripts\obabel.exe"
    if (-not (Test-Path -LiteralPath $obabel)) { throw "openbabel-wheel did not provide obabel.exe" }
    & $obabel -V
}

Invoke-InstallStep "AiZynthFinder isolated runtime" {
    $aizynth = Join-Path $envs "aizynthfinder"
    $aizynthPython = Ensure-Venv $aizynth
    & $aizynthPython -m pip install --upgrade pip
    & $aizynthPython -m pip install --prefer-binary aizynthfinder
    & $aizynthPython -m aizynthfinder.interfaces.aizynthcli --help
}

Invoke-InstallStep "AutoGrow4 source and isolated runtime" {
    $autogrowRoot = Join-Path $tools "AutoGrow4"
    Ensure-SourceArchive "https://github.com/durrantlab/autogrow4.git" $autogrowRoot "RunAutogrow.py"
    $autogrowPython = Ensure-Venv (Join-Path $envs "autogrow4")
    & $autogrowPython -m pip install --upgrade pip
    $requirements = Join-Path $autogrowRoot "requirements.txt"
    if (Test-Path -LiteralPath $requirements) {
        & $autogrowPython -m pip install --prefer-binary -r $requirements
    } else {
        & $autogrowPython -m pip install --prefer-binary numpy pandas scipy matplotlib rdkit
    }
    & $autogrowPython (Join-Path $autogrowRoot "RunAutogrow.py") --help
}

Invoke-InstallStep "TargetDiff source checkout" {
    Ensure-SourceArchive "https://github.com/guanjq/targetdiff.git" (Join-Path $tools "TargetDiff") "scripts\sample_for_pdb.py"
}

if ($InstallWsl) {
    Invoke-InstallStep "Ubuntu WSL runtime for GNINA and TargetDiff" {
        $ubuntu = (& wsl --list --quiet 2>$null | Where-Object { $_.Trim() -match "^Ubuntu" } | Select-Object -First 1)
        if (-not $ubuntu) {
            & wsl --install --distribution Ubuntu --no-launch
            Write-Warning "Ubuntu has been requested. A Windows restart may be required before GNINA and TargetDiff can be installed in WSL."
        }
    }
}

& $python (Join-Path $root "scripts\check_local_tools.py") --json
if ($failures.Count) {
    Write-Warning "[local-tools] incomplete steps:`n$($failures -join "`n")"
    exit 1
}
