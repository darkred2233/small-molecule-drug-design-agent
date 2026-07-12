param(
    [switch]$Parallel,
    [switch]$SkipPull,
    [switch]$SmallGnina,
    [string]$DockerHubMirrorPrefix = $env:DOCKER_HUB_MIRROR_PREFIX,
    [Parameter(Position = 0, ValueFromRemainingArguments = $true)]
    [string[]]$Tools = @("all")
)

$ErrorActionPreference = "Stop"

Set-Location (Resolve-Path "$PSScriptRoot\..")

$env:DOCKER_BUILDKIT = "1"
$env:COMPOSE_DOCKER_CLI_BUILD = "1"
$env:BUILDKIT_PROGRESS = "plain"

if ($SmallGnina) {
    $env:GNINA_IMAGE = "gnina/gnina:1.0.3"
}

$toolMap = [ordered]@{
    "gnina" = @{
        Name = "GNINA"
        Service = "gnina"
        Description = "Docking / CNN scoring"
        HasBuild = $false
        Image = $(if ($env:GNINA_IMAGE) { $env:GNINA_IMAGE } else { "gnina/gnina:latest" })
    }
    "vina" = @{
        Name = "AutoDock Vina"
        Service = "vina"
        Description = "Docking"
        HasBuild = $true
    }
    "chemprop" = @{
        Name = "Chemprop"
        Service = "chemprop"
        Description = "ADMET prediction"
        HasBuild = $true
    }
    "diffdock" = @{
        Name = "DiffDock"
        Service = "diffdock"
        Description = "Diffusion docking"
        HasBuild = $true
    }
    "reinvent4" = @{
        Name = "REINVENT4"
        Service = "reinvent4"
        Description = "Molecule generation"
        HasBuild = $true
    }
    "autogrow4" = @{
        Name = "AutoGrow4"
        Service = "autogrow4"
        Description = "Genetic molecule generation"
        HasBuild = $true
    }
    "aizynthfinder" = @{
        Name = "AiZynthFinder"
        Service = "aizynthfinder"
        Description = "Retrosynthesis planning"
        HasBuild = $true
    }
}

function Resolve-SelectedTools {
    param([string[]]$RequestedTools)

    $normalized = @()
    foreach ($tool in $RequestedTools) {
        if ([string]::IsNullOrWhiteSpace($tool)) {
            continue
        }
        $normalized += $tool.Trim().ToLowerInvariant()
    }

    if ($normalized.Count -eq 0 -or $normalized -contains "all") {
        return @("gnina", "vina", "chemprop", "diffdock", "reinvent4", "autogrow4", "aizynthfinder")
    }

    if ($normalized -contains "core") {
        return @("gnina", "vina", "chemprop")
    }

    foreach ($tool in $normalized) {
        if (-not $toolMap.Contains($tool)) {
            throw "Unknown tool: $tool. Use: all, core, $($toolMap.Keys -join ', ')"
        }
    }

    return $normalized
}

function Invoke-Docker {
    param([string[]]$Arguments)

    Write-Host ""
    Write-Host "docker $($Arguments -join ' ')" -ForegroundColor DarkGray
    & docker @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Docker command failed: docker $($Arguments -join ' ')"
    }
}

function Invoke-PullPublicImage {
    param(
        [string]$Service,
        [string]$Image
    )

    try {
        Invoke-Docker -Arguments @("compose", "pull", $Service)
        return
    }
    catch {
        if ([string]::IsNullOrWhiteSpace($DockerHubMirrorPrefix)) {
            throw
        }

        $prefix = $DockerHubMirrorPrefix.Trim().TrimEnd("/")
        $mirrorImage = "$prefix/$Image"
        Write-Host "Direct pull failed. Trying mirror image: $mirrorImage" -ForegroundColor Yellow
        Invoke-Docker -Arguments @("pull", $mirrorImage)
        Invoke-Docker -Arguments @("tag", $mirrorImage, $Image)
    }
}

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Small Molecule Drug Design Agent - tool image setup" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

try {
    $dockerVersion = docker --version
    Write-Host "Docker: $dockerVersion" -ForegroundColor Green
    docker ps | Out-Null
    Write-Host "Docker Desktop is running" -ForegroundColor Green
}
catch {
    Write-Host "Docker is unavailable. Please start Docker Desktop first." -ForegroundColor Red
    exit 1
}

$selectedTools = Resolve-SelectedTools -RequestedTools $Tools

Write-Host ""
Write-Host "Selected tools: $($selectedTools -join ', ')" -ForegroundColor Yellow
Write-Host "Download cache: BuildKit + pip/apt cache mounts enabled" -ForegroundColor Yellow
$buildMode = if ($Parallel) { "parallel" } else { "sequential, better for slow networks" }
Write-Host "Build mode: $buildMode" -ForegroundColor Yellow
if ($env:GNINA_IMAGE) {
    Write-Host "GNINA image: $env:GNINA_IMAGE" -ForegroundColor Yellow
}
if (-not [string]::IsNullOrWhiteSpace($DockerHubMirrorPrefix)) {
    Write-Host "Docker Hub mirror prefix fallback: $DockerHubMirrorPrefix" -ForegroundColor Yellow
}

$failed = @()
$startedAt = Get-Date

foreach ($key in $selectedTools) {
    $tool = $toolMap[$key]
    if (-not $tool.HasBuild -and -not $SkipPull) {
        Write-Host ""
        Write-Host "[$($tool.Name)] Pull public image: $($tool.Description)" -ForegroundColor Cyan
        try {
            Invoke-PullPublicImage -Service $tool.Service -Image $tool.Image
        }
        catch {
            Write-Host $_ -ForegroundColor Red
            $failed += $tool.Name
        }
    }
}

$buildServices = @()
foreach ($key in $selectedTools) {
    $tool = $toolMap[$key]
    if ($tool.HasBuild) {
        $buildServices += $tool.Service
    }
}

if ($buildServices.Count -gt 0) {
    if ($Parallel) {
        Write-Host ""
        Write-Host "Parallel build: $($buildServices -join ', ')" -ForegroundColor Cyan
        try {
            Invoke-Docker -Arguments (@("compose", "--progress=plain", "build", "--parallel") + $buildServices)
        }
        catch {
            Write-Host $_ -ForegroundColor Red
            $failed += "parallel-build"
        }
    }
    else {
        foreach ($service in $buildServices) {
            $tool = $toolMap.GetEnumerator() | Where-Object { $_.Value.Service -eq $service } | Select-Object -First 1
            Write-Host ""
            Write-Host "[$($tool.Value.Name)] Build image: $($tool.Value.Description)" -ForegroundColor Cyan
            try {
                Invoke-Docker -Arguments @("compose", "--progress=plain", "build", $service)
            }
            catch {
                Write-Host $_ -ForegroundColor Red
                $failed += $tool.Value.Name
            }
        }
    }
}

$elapsed = [math]::Round(((Get-Date) - $startedAt).TotalMinutes, 1)

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Setup finished in about $elapsed minutes" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

if ($failed.Count -gt 0) {
    Write-Host "Failed or incomplete: $($failed -join ', ')" -ForegroundColor Red
    Write-Host ""
    Write-Host "Retry only the failed item, for example:" -ForegroundColor Yellow
    Write-Host "  .\scripts\build_tools.bat chemprop" -ForegroundColor White
    Write-Host "  .\scripts\build_tools.bat diffdock" -ForegroundColor White
    exit 1
}

Write-Host "All selected tools are ready." -ForegroundColor Green
Write-Host ""
Write-Host "Verify:" -ForegroundColor Yellow
Write-Host "  python scripts\check_tools.py --verbose" -ForegroundColor White
Write-Host "  python scripts\manage_docker_tools.py status" -ForegroundColor White
