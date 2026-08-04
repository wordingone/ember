# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
#
# Pins the staged-artifact path expectation against bun's actual win32 output naming
# (issue #1368): bun --compile force-appends .exe to any outfile not already ending in
# it. Fakes both landing layouts in a temp dir and asserts the launcher's resolution
# logic (scripts/ember-launch-staging.ps1) finds the binary in each.
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot "..\ember-launch-staging.ps1")

$script:failures = 0
function Assert-Probe([bool]$Condition, [string]$Name) {
    if ($Condition) {
        Write-Output "PASS $Name"
    }
    else {
        Write-Output "FAIL $Name"
        $script:failures += 1
    }
}

$probeRoot = Join-Path $env:TEMP ("ember-staging-probe-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $probeRoot | Out-Null
try {
    $outfile = Get-EmberStagedBuildOutfile $probeRoot

    # bun win32 appends .exe unless the outfile already ends in it; the staged name
    # must therefore end in .exe, and must not be the final Ember.exe (crash safety).
    Assert-Probe ($outfile.EndsWith(".exe")) "staged outfile ends in .exe so bun's forced suffix is a no-op"
    Assert-Probe ($outfile -ne (Join-Path $probeRoot "Ember.exe")) "staged outfile is not the final Ember.exe"

    # Layout A: bun lands exactly the requested name (current .exe-suffixed request).
    Set-Content -LiteralPath $outfile -Value "binary-bytes"
    Assert-Probe ((Resolve-EmberStagedBuildArtifact $outfile) -eq $outfile) "resolver finds the exact requested artifact"
    Remove-Item -LiteralPath $outfile

    # Layout B: the issue-#1368 shape — bun force-appended .exe to a non-.exe request.
    $legacyRequest = Join-Path $probeRoot "Ember.exe.partial"
    $bunLanded = "$legacyRequest.exe"
    Set-Content -LiteralPath $bunLanded -Value "binary-bytes"
    Assert-Probe ((Resolve-EmberStagedBuildArtifact $legacyRequest) -eq $bunLanded) "resolver accepts the bun-forced .exe-suffixed variant"
    Remove-Item -LiteralPath $bunLanded

    # Layout C: nothing landed.
    Assert-Probe ($null -eq (Resolve-EmberStagedBuildArtifact (Join-Path $probeRoot "missing.exe"))) "resolver returns null when no artifact landed"

    # Layout D: a zero-byte staged file (crashed writer) is never a runnable binary.
    $zeroByte = Join-Path $probeRoot "Ember.partial.exe"
    New-Item -ItemType File -Path $zeroByte | Out-Null
    Assert-Probe ($null -eq (Resolve-EmberStagedBuildArtifact $zeroByte)) "resolver ignores a zero-byte staged artifact"
    Remove-Item -LiteralPath $zeroByte
}
finally {
    Remove-Item -Recurse -Force $probeRoot
}

if ($script:failures -gt 0) {
    Write-Output "PROBE FAILED ($script:failures assertion(s))"
    exit 1
}
Write-Output "PROBE PASSED (6 assertions)"
exit 0
