# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
param(
    [Parameter(Mandatory = $true)][ValidateSet("Mint", "Run")][string]$Mode,
    [Parameter(Mandatory = $true)][string]$RepoRoot,
    [Parameter(Mandatory = $true)][string]$Plan,
    [string]$PlanRawSha256,
    [Parameter(Mandatory = $true)][string]$Output,
    [string]$DeclaredHead,
    [string]$LegSpec,
    [string]$LegSpecRawSha256,
    [string]$SetuptoolsSdist,
    [string]$ArtifactRoot
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path -LiteralPath $RepoRoot).Path
$launcher = Join-Path $repo "scripts\headless-python.ps1"
$orchestrator = Join-Path $repo "scripts\issue1949_a_clean.py"
$canonicalPythonEnvironment = Join-Path $repo "src\ember\infrastructure\tools\ember-restart-3b\python_environment.py"
$legacyPythonEnvironment = Join-Path $repo "tools\ember-restart-3b\python_environment.py"
if (Test-Path -LiteralPath $canonicalPythonEnvironment -PathType Leaf) {
    $pythonEnvironment = $canonicalPythonEnvironment
    $platformProfileArgs = @("--platform-profile", "windows")
} elseif (Test-Path -LiteralPath $legacyPythonEnvironment -PathType Leaf) {
    $pythonEnvironment = $legacyPythonEnvironment
    $platformProfileArgs = @()
} else {
    throw "A_CLEAN_TOOL_ROOT_UNRESOLVED:python_environment.py"
}
if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) { throw "HEADLESS_LAUNCHER_MISSING:$launcher" }
if (-not (Test-Path -LiteralPath $orchestrator -PathType Leaf)) { throw "A_CLEAN_ORCHESTRATOR_MISSING:$orchestrator" }

$outside = [System.IO.Path]::GetTempPath()
Push-Location -LiteralPath $outside
try {
    if ($Mode -eq "Mint") {
        if ($DeclaredHead -notmatch '^[0-9a-f]{40}$') { throw "A_CLEAN_DECLARED_HEAD_REFUSED:$DeclaredHead" }
        if ($LegSpecRawSha256 -notmatch '^[0-9a-f]{64}$') { throw "A_CLEAN_LEG_SPEC_HASH_REFUSED" }
        $legSpecPath = (Resolve-Path -LiteralPath $LegSpec).Path
        $actualSpecSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $legSpecPath).Hash.ToLowerInvariant()
        if ($actualSpecSha256 -ne $LegSpecRawSha256) { throw "A_CLEAN_LEG_SPEC_HASH_REFUSED:$actualSpecSha256" }
        $sdistPath = (Resolve-Path -LiteralPath $SetuptoolsSdist).Path
        $actualSdistSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $sdistPath).Hash.ToLowerInvariant()
        if ($actualSdistSha256 -ne 'f4695c21257f0d9b537ec2692c941d02ee143b7cc1276941349a546573b2ef73') {
            throw "A_CLEAN_SDIST_HASH_REFUSED:$actualSdistSha256"
        }
        $artifacts = (Resolve-Path -LiteralPath $ArtifactRoot).Path
        $installReceipt = Join-Path $artifacts "issue1949-a-clean-windows-install.json"
        & powershell.exe -NoLogo -NoProfile -NonInteractive -File $launcher -- `
            $pythonEnvironment --root $repo @platformProfileArgs install --receipt $installReceipt
        if ($LASTEXITCODE -ne 0) { throw "A_CLEAN_WINDOWS_BOOTSTRAP_REFUSED:$LASTEXITCODE" }
        $isolatedPython = Join-Path $repo "state\python-environments\issue1949-a-clean-windows-install\Scripts\python.exe"
        $cargo = (Get-Command cargo.exe -ErrorAction Stop).Source
        & powershell.exe -NoLogo -NoProfile -NonInteractive -File $launcher -- `
            $orchestrator mint-plan --repo-root $repo --leg-spec $legSpecPath --output $Plan `
            --declared-head $DeclaredHead --platform windows --python-executable $isolatedPython `
            --cargo-executable $cargo --artifact-root $artifacts --install-receipt $installReceipt `
            --setuptools-sdist $sdistPath
        if ($LASTEXITCODE -ne 0) { throw "A_CLEAN_WINDOWS_MINT_REFUSED:$LASTEXITCODE" }
        return
    }

    if ($PlanRawSha256 -notmatch '^[0-9a-f]{64}$') { throw "A_CLEAN_PLAN_RAW_HASH_REFUSED" }
    $planPath = (Resolve-Path -LiteralPath $Plan).Path
    $actualPlanSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $planPath).Hash.ToLowerInvariant()
    if ($actualPlanSha256 -ne $PlanRawSha256) { throw "A_CLEAN_PLAN_RAW_HASH_REFUSED:$actualPlanSha256" }
    & powershell.exe -NoLogo -NoProfile -NonInteractive -File $launcher -- `
        $orchestrator run --repo-root $repo --plan $planPath --output $Output --platform windows
    if ($LASTEXITCODE -ne 0) { throw "A_CLEAN_WINDOWS_REFUSED:$LASTEXITCODE" }
    & powershell.exe -NoLogo -NoProfile -NonInteractive -File $launcher -- `
        $orchestrator verify --receipt $Output
    if ($LASTEXITCODE -ne 0) { throw "A_CLEAN_WINDOWS_VERIFY_REFUSED:$LASTEXITCODE" }
}
finally {
    Pop-Location
}
