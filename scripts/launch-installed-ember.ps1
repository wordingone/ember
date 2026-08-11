# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
param(
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA "Programs\Ember")
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot "ember-window-placement.ps1")

function Assert-ExactJsonProperties($Value, [string[]]$Expected, [string]$Name) {
    $actual = @($Value.PSObject.Properties.Name | Sort-Object)
    $wanted = @($Expected | Sort-Object)
    if (($actual -join "`n") -ne ($wanted -join "`n")) {
        throw "$Name has missing or unknown fields."
    }
}

function Read-EmberInstalledManifest([string]$Root) {
    $path = Join-Path $Root "current.json"
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Ember is not installed: current.json is absent." }
    try { $manifest = Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json }
    catch { throw "Ember current.json is not valid JSON." }
    Assert-ExactJsonProperties $manifest @(
        "schema_version", "source_commit", "executable_sha256", "executable_relative_path",
        "installed_at_utc", "previous_source_commit"
    ) "Ember current.json"
    if ($manifest.schema_version -ne 1) { throw "Ember current.json has an unsupported schema version." }
    if ($manifest.source_commit -notmatch '^[0-9a-f]{40}$') { throw "Ember current.json has an invalid source commit." }
    if ($manifest.executable_sha256 -notmatch '^[0-9a-f]{64}$') { throw "Ember current.json has an invalid executable hash." }
    if ($manifest.previous_source_commit -ne "" -and $manifest.previous_source_commit -notmatch '^[0-9a-f]{40}$') {
        throw "Ember current.json has an invalid previous source commit."
    }
    $installed = [DateTime]::MinValue
    if (-not [DateTime]::TryParse($manifest.installed_at_utc, [ref]$installed)) {
        throw "Ember current.json has an invalid installation time."
    }
    if ($manifest.executable_relative_path -isnot [string] -or
        $manifest.executable_relative_path -notmatch '^versions/[0-9a-f]{40}/Ember\.exe$') {
        throw "Ember current.json has an invalid executable relative path."
    }
    return $manifest
}

function Resolve-EmberInstalledExecutable([string]$Root, $Manifest) {
    $rootPath = [IO.Path]::GetFullPath($Root).TrimEnd('\', '/')
    $relative = $Manifest.executable_relative_path.Replace('/', [IO.Path]::DirectorySeparatorChar)
    $candidate = [IO.Path]::GetFullPath((Join-Path $rootPath $relative))
    if (-not $candidate.StartsWith($rootPath + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Ember executable escapes the installation root."
    }
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { throw "The admitted Ember executable is absent." }
    $actual = (Get-FileHash -LiteralPath $candidate -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $Manifest.executable_sha256) { throw "The admitted Ember executable hash does not match current.json." }
    return $candidate
}

if ($env:EMBER_INSTALLED_LAUNCH_LIBRARY_ONLY -eq "1") { return }

try {
    $root = [IO.Path]::GetFullPath($InstallRoot)
    $manifest = Read-EmberInstalledManifest $root
    $application = Resolve-EmberInstalledExecutable $root $manifest
    Set-Location -LiteralPath $root
    $env:EMBER_SOURCE_ROOT = $root
    $env:EMBER_REPO_ROOT = $root
    $windowHandle = Get-EmberHostWindowHandle
    Set-EmberWindowToLeftWorkArea $windowHandle | Out-Null
    & $application
    exit $LASTEXITCODE
}
catch {
    [Console]::Error.WriteLine("Ember launch refused: " + $_.Exception.Message)
    exit 1
}
