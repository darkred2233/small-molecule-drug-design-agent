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
    param(
        [string]$Url,
        [string]$Destination,
        [string]$ExpectedEntry,
        [string]$Ref = ""
    )
    $expected = Join-Path $Destination $ExpectedEntry
    $refMarker = Join-Path $Destination ".medagent-source-ref"
    $refMatches = -not $Ref -or (
        (Test-Path -LiteralPath $refMarker) -and
        ((Get-Content -Raw -LiteralPath $refMarker).Trim() -eq $Ref)
    )
    if ((Test-Path -LiteralPath $expected) -and $refMatches) {
        Write-Host "[local-tools] reusing existing source: $Destination"
        return
    }
    if (Test-Path -LiteralPath $Destination) {
        Remove-Item -LiteralPath $Destination -Recurse -Force
    }
    $repository = $Url -replace '^https://github.com/', '' -replace '\.git$', ''
    $metadata = Invoke-RestMethod -Uri "https://api.github.com/repos/$repository" -Headers @{"User-Agent"="MedAgent-local-installer"}
    $archiveRef = if ($Ref) { $Ref } else { $metadata.default_branch }
    $archiveUrl = "https://api.github.com/repos/$repository/zipball/$archiveRef"
    $archive = Join-Path $downloads "$($metadata.name)-$($archiveRef -replace '[^A-Za-z0-9._-]', '_').zip"
    $expanded = Join-Path $downloads "$($metadata.name)-expanded"
    Invoke-WebRequest -Uri $archiveUrl -Headers @{"User-Agent"="MedAgent-local-installer"} -OutFile $archive -TimeoutSec 60
    if (Test-Path -LiteralPath $expanded) {
        Remove-Item -LiteralPath $expanded -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $expanded | Out-Null
    Expand-Archive -LiteralPath $archive -DestinationPath $expanded -Force
    $source = Get-ChildItem -LiteralPath $expanded -Directory | Select-Object -First 1
    if (-not $source) { throw "GitHub archive contains no source directory: $archiveUrl" }
    Move-Item -LiteralPath $source.FullName -Destination $Destination
    if (-not (Test-Path -LiteralPath $expected)) { throw "source archive lacks ${ExpectedEntry}: $archiveUrl" }
    if ($Ref) { Set-Content -LiteralPath $refMarker -Value $Ref -Encoding ascii }
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
    $vinaVersion = "1.2.7"
    $vinaRoot = Join-Path $tools "vina"
    $vinaExe = Join-Path $vinaRoot "vina.exe"
    if (-not (Test-Path -LiteralPath $vinaExe)) {
        $release = Invoke-RestMethod -Uri "https://api.github.com/repos/ccsb-scripps/AutoDock-Vina/releases/tags/v$vinaVersion" -Headers @{"User-Agent"="MedAgent-local-installer"}
        $assetName = "vina_${vinaVersion}_win.exe"
        $asset = @($release.assets | Where-Object { $_.name -eq $assetName }) | Select-Object -First 1
        if (-not $asset) { throw "Vina release v$vinaVersion lacks $assetName" }
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
    & $chemPython -m pip install --only-binary=:all: "openbabel-wheel==3.1.1.23"
    $obabel = Join-Path $chemtools "Scripts\obabel.exe"
    if (-not (Test-Path -LiteralPath $obabel)) { throw "openbabel-wheel did not provide obabel.exe" }
    & $obabel -V
}

Invoke-InstallStep "AiZynthFinder isolated runtime" {
    $aizynth = Join-Path $envs "aizynthfinder"
    $aizynthPython = Ensure-Venv $aizynth
    & $aizynthPython -m pip install --upgrade pip
    & $aizynthPython -m pip install --prefer-binary "aizynthfinder==4.4.1"
    & $aizynthPython -m aizynthfinder.interfaces.aizynthcli --help

    $aizynthData = Join-Path $root "data\aizynthfinder"
    $requiredData = @(
        "config.yml",
        "uspto_model.onnx",
        "uspto_templates.csv.gz",
        "uspto_ringbreaker_model.onnx",
        "uspto_ringbreaker_templates.csv.gz",
        "uspto_filter_model.onnx",
        "zinc_stock.hdf5"
    )
    $missingData = $requiredData | Where-Object {
        $candidate = Join-Path $aizynthData $_
        -not (Test-Path -LiteralPath $candidate -PathType Leaf) -or
        (Get-Item -LiteralPath $candidate).Length -eq 0
    }
    if ($missingData) {
        New-Item -ItemType Directory -Force -Path $aizynthData | Out-Null
        & $aizynthPython -m aizynthfinder.tools.download_public_data $aizynthData
        if ($LASTEXITCODE -ne 0) { throw "unable to download AiZynthFinder public model data" }
    }
    $stillMissing = $requiredData | Where-Object {
        $candidate = Join-Path $aizynthData $_
        -not (Test-Path -LiteralPath $candidate -PathType Leaf) -or
        (Get-Item -LiteralPath $candidate).Length -eq 0
    }
    if ($stillMissing) {
        throw "AiZynthFinder public model data is incomplete: $($stillMissing -join ', ')"
    }
}

Invoke-InstallStep "AutoGrow4 source" {
    $autogrowRoot = Join-Path $tools "AutoGrow4"
    Ensure-SourceArchive "https://github.com/durrantlab/autogrow4.git" $autogrowRoot "RunAutogrow.py" "v4.0.3"
    & $python (Join-Path $root "scripts\patch_autogrow4.py") --root $autogrowRoot
    if ($LASTEXITCODE -ne 0) { throw "unable to apply MedAgent AutoGrow4 extensions" }
}

Invoke-InstallStep "TargetDiff source checkout" {
    Ensure-SourceArchive "https://github.com/guanjq/targetdiff.git" `
        (Join-Path $tools "TargetDiff") "scripts\sample_for_pocket.py" `
        "142f1eb7178480d435fe0b8cb95a99beb48997c7"
}

if ($InstallWsl) {
    Invoke-InstallStep "Ubuntu WSL runtimes for GNINA, TargetDiff, and AutoGrow4" {
        $ubuntu = (& wsl --list --quiet 2>$null | Where-Object { $_.Trim() -match "^Ubuntu" } | Select-Object -First 1)
        if (-not $ubuntu) {
            & wsl --install --distribution Ubuntu --no-launch
            Write-Warning "Ubuntu has been requested. Restart Windows if WSL asks for it, then rerun this command."
            return
        }
        $drive = $root.Substring(0, 1).ToLowerInvariant()
        $rest = $root.Substring(2).Replace("\", "/")
        $installer = "/mnt/$drive$rest/scripts/install_wsl_gpu_tools.sh"
        & wsl -d $ubuntu.Trim() -u root -- bash $installer
    }
}

& $python (Join-Path $root "scripts\check_local_tools.py") --strict --json
if ($failures.Count) {
    Write-Warning "[local-tools] incomplete steps:`n$($failures -join "`n")"
    exit 1
}
