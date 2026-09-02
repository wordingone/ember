# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
param(
    [Parameter(Mandatory = $true)][string]$RepoRoot,
    [Parameter(Mandatory = $true)][string]$Plan,
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$PlanRawSha256,
    [Parameter(Mandatory = $true)][string]$Output
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path -LiteralPath $RepoRoot).Path
$planPath = (Resolve-Path -LiteralPath $Plan).Path
$actualPlanSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $planPath).Hash.ToLowerInvariant()
if ($actualPlanSha256 -ne $PlanRawSha256) { throw "A_CLEAN_PLAN_RAW_HASH_REFUSED:$actualPlanSha256" }
$launcher = Join-Path $repo "scripts\headless-python.ps1"
$orchestrator = Join-Path $repo "scripts\issue1949_a_clean.py"
if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) { throw "HEADLESS_LAUNCHER_MISSING:$launcher" }
if (-not (Test-Path -LiteralPath $orchestrator -PathType Leaf)) { throw "A_CLEAN_ORCHESTRATOR_MISSING:$orchestrator" }

$outside = [System.IO.Path]::GetTempPath()
Push-Location -LiteralPath $outside
try {
    & powershell.exe -NoLogo -NoProfile -NonInteractive -File $launcher -- `
        $orchestrator run --repo-root $repo --plan $planPath --output $Output --platform windows
    if ($LASTEXITCODE -ne 0) { throw "A_CLEAN_WINDOWS_REFUSED:$LASTEXITCODE" }
}
finally {
    Pop-Location
}
