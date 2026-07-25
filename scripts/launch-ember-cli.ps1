# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$BunVersion = "1.3.12"
$BunArchiveUrl = "https://github.com/oven-sh/bun/releases/download/bun-v1.3.12/bun-windows-x64.zip"
$BunArchiveSha256 = "841ff9c5dffcaa3a2620d1e3f87ee500f32a4ca830b001cade7a3479609d4a89"

function Stop-EmberLaunch([string]$Message) {
    Write-Host ""
    Write-Host "Ember could not prepare its runtime." -ForegroundColor Red
    Write-Host $Message
    exit 1
}

function Get-VerifiedBun([string]$RepositoryRoot) {
    if ($env:EMBER_LAUNCH_TEST_MODE -eq "1") {
        $candidate = $env:EMBER_LAUNCH_TEST_RUNTIME
        if ([string]::IsNullOrWhiteSpace($candidate) -or -not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            throw "The launch test runtime is missing."
        }
        return (Resolve-Path -LiteralPath $candidate).Path
    }

    $installed = Get-Command bun.exe,bun.cmd -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -ne $installed -and -not [string]::IsNullOrWhiteSpace($installed.Source)) {
        try {
            $installedVersion = (& $installed.Source --version 2>$null | Select-Object -First 1).Trim()
            if ($installedVersion -eq $BunVersion) {
                return $installed.Source
            }
        }
        catch {
            # A missing, broken, or wrong-version PATH runtime is not authoritative.
        }
    }

    $runtimeParent = Join-Path $RepositoryRoot ".ember\runtime"
    $runtimeRoot = Join-Path $runtimeParent "bun-v$BunVersion"
    $bun = Join-Path $runtimeRoot "bun-windows-x64\bun.exe"
    if (Test-Path -LiteralPath $bun -PathType Leaf) {
        return $bun
    }

    New-Item -ItemType Directory -Force -Path $runtimeParent | Out-Null
    $transaction = Join-Path $runtimeParent (".install-" + [Guid]::NewGuid().ToString("N"))
    $archive = Join-Path $transaction "bun.zip"
    $expanded = Join-Path $transaction "expanded"
    try {
        New-Item -ItemType Directory -Force -Path $transaction | Out-Null
        Write-Host "Preparing Ember's pinned local runtime once..."
        Invoke-WebRequest -UseBasicParsing -Uri $BunArchiveUrl -OutFile $archive
        $actualSha256 = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actualSha256 -ne $BunArchiveSha256) {
            throw "The downloaded runtime failed its SHA-256 check."
        }
        Expand-Archive -LiteralPath $archive -DestinationPath $expanded
        $expandedBunRoot = Join-Path $expanded "bun-windows-x64"
        $expandedBun = Join-Path $expandedBunRoot "bun.exe"
        if (-not (Test-Path -LiteralPath $expandedBun -PathType Leaf)) {
            throw "The verified runtime archive did not contain bun.exe."
        }
        if (-not (Test-Path -LiteralPath $runtimeRoot)) {
            New-Item -ItemType Directory -Force -Path $runtimeRoot | Out-Null
        }
        if (-not (Test-Path -LiteralPath $bun -PathType Leaf)) {
            Move-Item -LiteralPath $expandedBunRoot -Destination (Join-Path $runtimeRoot "bun-windows-x64")
        }
    }
    finally {
        if (Test-Path -LiteralPath $transaction) {
            Remove-Item -LiteralPath $transaction -Recurse -Force
        }
    }
    if (-not (Test-Path -LiteralPath $bun -PathType Leaf)) {
        throw "The verified runtime could not be installed."
    }
    return $bun
}

try {
    $repositoryRoot = Split-Path -Parent $PSScriptRoot
    $sourceRoot = Join-Path $repositoryRoot "tools\ember-cli\src"
    $entrypoint = Join-Path $sourceRoot "entrypoints\main.ts"
    $package = Join-Path $sourceRoot "package.json"
    $lock = Join-Path $sourceRoot "bun.lock"
    foreach ($required in @($entrypoint, $package, $lock)) {
        if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
            throw "This copy of the repository is incomplete. Restore it and run Ember.cmd again."
        }
    }

    $bun = Get-VerifiedBun $repositoryRoot
    $dependenciesReady = Test-Path -LiteralPath (Join-Path $sourceRoot "node_modules\react\package.json") -PathType Leaf
    if (-not $dependenciesReady) {
        Write-Host "Preparing Ember's interface dependencies once..."
        Push-Location $sourceRoot
        try {
            & $bun install --frozen-lockfile --production
            if ($LASTEXITCODE -ne 0) {
                throw "Dependency preparation exited with code $LASTEXITCODE."
            }
        }
        finally {
            Pop-Location
        }
        if ($env:EMBER_LAUNCH_TEST_MODE -ne "1" -and -not (Test-Path -LiteralPath (Join-Path $sourceRoot "node_modules\react\package.json") -PathType Leaf)) {
            throw "Dependency preparation did not produce the required interface runtime."
        }
    }

    if ([string]::IsNullOrWhiteSpace($env:EMBER_GPU_FREE)) {
        $env:EMBER_GPU_FREE = "1"
    }

    if ($env:EMBER_LAUNCH_TEST_MODE -eq "1") {
        Push-Location $sourceRoot
        try {
            & $bun run entrypoints/main.ts
            $exitCode = $LASTEXITCODE
        }
        finally {
            Pop-Location
        }
        if ($exitCode -ne 0) {
            throw "Ember CLI exited with code $exitCode."
        }
        return
    }

    $commit = (& git -C $repositoryRoot rev-parse HEAD 2>$null | Select-Object -First 1).Trim()
    if ($commit -notmatch "^[0-9a-f]{40}$") {
        throw "This repository does not have an exact Git source identity."
    }
    $applicationRoot = Join-Path $repositoryRoot ".ember\runtime\ember\$commit"
    $application = Join-Path $applicationRoot "Ember.exe"
    if (-not (Test-Path -LiteralPath $application -PathType Leaf)) {
        $buildOutput = Join-Path $sourceRoot "ember.exe"
        $buildLog = Join-Path $repositoryRoot ".ember\runtime\ember-build.log"
        New-Item -ItemType Directory -Force -Path $applicationRoot | Out-Null
        try {
            Push-Location $sourceRoot
            try {
                $previousErrorActionPreference = $ErrorActionPreference
                $ErrorActionPreference = "Continue"
                try {
                    & $bun run build *> $buildLog
                }
                finally {
                    $ErrorActionPreference = $previousErrorActionPreference
                }
                $buildExit = $LASTEXITCODE
            }
            finally {
                Pop-Location
            }
            if ($buildExit -ne 0 -or -not (Test-Path -LiteralPath $buildOutput -PathType Leaf)) {
                throw "Ember's local application build was refused. Restore a clean repository and run Ember.cmd again."
            }
            Move-Item -LiteralPath $buildOutput -Destination $application
        }
        finally {
            if (Test-Path -LiteralPath $buildOutput -PathType Leaf) {
                Remove-Item -LiteralPath $buildOutput -Force
            }
        }
    }

    & $application
    if ($LASTEXITCODE -ne 0) {
        throw "Ember CLI exited with code $LASTEXITCODE."
    }
}
catch {
    Stop-EmberLaunch $_.Exception.Message
}
