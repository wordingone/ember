# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
Set-StrictMode -Version Latest

function Get-EmberStagedBuildOutfile([string]$ApplicationRoot) {
    # bun --compile on Windows force-appends .exe to any outfile that does not already
    # end in it, so a request for Ember.exe.partial lands at Ember.exe.partial.exe and
    # the launcher's staging Test-Path misses a fully successful build (issue #1368).
    # Stage under a name bun leaves untouched; it is still not the final Ember.exe, so
    # write-to-partial-then-rename crash safety is preserved.
    return Join-Path $ApplicationRoot "Ember.partial.exe"
}

function Resolve-EmberStagedBuildArtifact([string]$RequestedOutfile) {
    # Returns the path the build tool actually produced for the requested outfile:
    # the exact requested name, or the bun-forced "<name>.exe" variant, else $null.
    # Accepting both means a future staging-name change cannot recreate #1368's
    # silent miss of a good binary. Zero-byte files are never a runnable binary and
    # are ignored rather than published.
    foreach ($candidate in @($RequestedOutfile, "$RequestedOutfile.exe")) {
        if ((Test-Path -LiteralPath $candidate -PathType Leaf) -and
            (Get-Item -LiteralPath $candidate).Length -gt 0) {
            return $candidate
        }
    }
    return $null
}
