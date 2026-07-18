# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
# Focused regressions for the exact-head review of issue #464 / PR #945.

$scriptPath = Join-Path $PSScriptRoot 'liveness-watchdog.ps1'
. $scriptPath

Describe 'Issue #464 exact-head review regressions' {
    BeforeEach {
        $script:scratch = Join-Path ([System.IO.Path]::GetTempPath()) ('ember-watchdog-review-' + [guid]::NewGuid())
        New-Item -ItemType Directory -Path $scratch -Force | Out-Null
        $script:markerPath = Join-Path $scratch 'planned-outage.json'
    }

    AfterEach {
        Remove-Item -Path $scratch -Recurse -Force -ErrorAction SilentlyContinue
    }

    It 'rejects a fractional-dot timestamp with no fractional digit for both targets' {
        $marker = @{
            owner = 'test-lane'; reason = 'planned probe'; target = 'both'
            started = '2026-07-08T11:00:00.Z'; expires = '2026-07-08T13:00:00Z'
            kill_receipt_ref = '2026-07-08T11:00:00Z'
        }
        ($marker | ConvertTo-Json) | Set-Content -Path $markerPath -Encoding utf8

        $m = Get-PlannedOutageMarker -Path $markerPath
        $m | Should BeNullOrEmpty
        (Test-MarkerCoversTarget -Marker $m -Target 'cockpit' -Now ([datetime]::Parse('2026-07-08T12:00:00Z'))).StandDown | Should Be $false
        (Test-MarkerCoversTarget -Marker $m -Target 'server' -Now ([datetime]::Parse('2026-07-08T12:00:00Z'))).StandDown | Should Be $false
    }

    It 'rejects a fractional-dot expires timestamp with no fractional digit for both targets' {
        $marker = @{
            owner = 'test-lane'; reason = 'planned probe'; target = 'both'
            started = '2026-07-08T11:00:00Z'; expires = '2026-07-08T13:00:00.Z'
            kill_receipt_ref = '2026-07-08T11:00:00Z'
        }
        ($marker | ConvertTo-Json) | Set-Content -Path $markerPath -Encoding utf8

        $m = Get-PlannedOutageMarker -Path $markerPath
        $m | Should BeNullOrEmpty
        (Test-MarkerCoversTarget -Marker $m -Target 'cockpit' -Now ([datetime]::Parse('2026-07-08T12:00:00Z'))).StandDown | Should Be $false
        (Test-MarkerCoversTarget -Marker $m -Target 'server' -Now ([datetime]::Parse('2026-07-08T12:00:00Z'))).StandDown | Should Be $false
    }

    It 'caps reachable exponential backoff before arithmetic or DateTime overflow' {
        $baseTs = [datetime]::Parse('2026-07-08T12:00:00Z').ToUniversalTime()
        $state = Get-DefaultWatchdogState
        $state.cockpit.backoffLevel = 28
        $state.cockpit.backoffUntil = $baseTs.AddMinutes(-1).ToString('o')

        { Add-DeathRecord -TargetState $state.cockpit -Now $baseTs -WindowMinutes 10 -Threshold 3 -BackoffMinutes 10 | Out-Null
          Add-DeathRecord -TargetState $state.cockpit -Now $baseTs.AddMinutes(2) -WindowMinutes 10 -Threshold 3 -BackoffMinutes 10 | Out-Null
          Add-DeathRecord -TargetState $state.cockpit -Now $baseTs.AddMinutes(4) -WindowMinutes 10 -Threshold 3 -BackoffMinutes 10 | Out-Null
        } | Should Not Throw

        $state.cockpit.backoffLevel | Should Be 28
        $until = [datetime]::Parse($state.cockpit.backoffUntil, [System.Globalization.CultureInfo]::InvariantCulture, [System.Globalization.DateTimeStyles]::AdjustToUniversal)
        (($until - $baseTs).TotalMinutes -le [int]::MaxValue) | Should Be $true
    }
}
