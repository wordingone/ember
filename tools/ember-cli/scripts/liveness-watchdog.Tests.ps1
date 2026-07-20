# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
# liveness-watchdog.Tests.ps1 -- Pester fixture for issue #464 (standing liveness
# watchdogs). Dot-sources liveness-watchdog.ps1: the execution guard at the bottom of
# that file means dot-sourcing only defines functions -- it never starts the live loop
# (Start-LivenessWatchdogLoop / Test-WatchdogAlreadyRunning's caller are never invoked
# here). Every OS-facing cmdlet the decision logic calls (Start-Process, Stop-Process,
# Invoke-WebRequest, Get-CimInstance) is Mocked in the tests that would otherwise touch
# it -- zero real processes are touched by this fixture, per the build mission's rail 6
# (build + fixture only from this lane; arming is a separate gated step).
#
# Run with: Invoke-Pester -Script (this file's path)

$scriptPath = Join-Path $PSScriptRoot 'liveness-watchdog.ps1'
. $scriptPath

function New-Scratch {
    $dir = Join-Path ([System.IO.Path]::GetTempPath()) ('ember-watchdog-test-' + [guid]::NewGuid())
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
    return $dir
}

Describe 'Get-PlannedOutageMarker + Test-MarkerCoversTarget (frozen contract, issue #464)' {
    BeforeEach {
        $script:scratch = New-Scratch
        $script:markerPath = Join-Path $scratch 'planned-outage.json'
    }
    AfterEach {
        Remove-Item -Path $scratch -Recurse -Force -ErrorAction SilentlyContinue
    }

    It 'valid marker covering the target and not yet expired -> StandDown true' {
        $now = [datetime]::Parse('2026-07-08T12:00:00Z').ToUniversalTime()
        $marker = @{
            owner = 'test-lane'; reason = 'planned probe'; target = 'cockpit'
            started = '2026-07-08T11:00:00Z'; expires = '2026-07-08T13:00:00Z'
            kill_receipt_ref = '2026-07-08T11:00:00Z'
        }
        ($marker | ConvertTo-Json) | Set-Content -Path $markerPath -Encoding utf8

        $m = Get-PlannedOutageMarker -Path $markerPath
        $m | Should Not BeNullOrEmpty
        $coverage = Test-MarkerCoversTarget -Marker $m -Target 'cockpit' -Now $now
        $coverage.StandDown | Should Be $true
        $coverage.Expired | Should Be $false
    }

    It 'marker missing kill_receipt_ref -> treated as absent ($null), not partially honored' {
        $marker = @{
            owner = 'test-lane'; reason = 'planned probe'; target = 'cockpit'
            started = '2026-07-08T11:00:00Z'; expires = '2026-07-08T13:00:00Z'
        }
        ($marker | ConvertTo-Json) | Set-Content -Path $markerPath -Encoding utf8

        Get-PlannedOutageMarker -Path $markerPath | Should BeNullOrEmpty
    }

    It 'marker targets a different surface (not "both") -> does not cover this target' {
        $now = [datetime]::Parse('2026-07-08T12:00:00Z').ToUniversalTime()
        $marker = @{
            owner = 'test-lane'; reason = 'planned probe'; target = 'server'
            started = '2026-07-08T11:00:00Z'; expires = '2026-07-08T13:00:00Z'
            kill_receipt_ref = '2026-07-08T11:00:00Z'
        }
        ($marker | ConvertTo-Json) | Set-Content -Path $markerPath -Encoding utf8

        $m = Get-PlannedOutageMarker -Path $markerPath
        $coverage = Test-MarkerCoversTarget -Marker $m -Target 'cockpit' -Now $now
        $coverage.StandDown | Should Be $false
        $coverage.Expired | Should Be $false
    }

    It 'expired marker -> Expired true, StandDown false (resume duty; caller logs the overrun)' {
        $now = [datetime]::Parse('2026-07-08T14:00:00Z').ToUniversalTime()
        $marker = @{
            owner = 'test-lane'; reason = 'planned probe'; target = 'both'
            started = '2026-07-08T11:00:00Z'; expires = '2026-07-08T13:00:00Z'
            kill_receipt_ref = '2026-07-08T11:00:00Z'
        }
        ($marker | ConvertTo-Json) | Set-Content -Path $markerPath -Encoding utf8

        $m = Get-PlannedOutageMarker -Path $markerPath
        $coverage = Test-MarkerCoversTarget -Marker $m -Target 'server' -Now $now
        $coverage.StandDown | Should Be $false
        $coverage.Expired | Should Be $true
    }

    It 'no marker file at all -> StandDown false, Expired false' {
        $now = [datetime]::UtcNow
        $coverage = Test-MarkerCoversTarget -Marker (Get-PlannedOutageMarker -Path $markerPath) -Target 'cockpit' -Now $now
        $coverage.StandDown | Should Be $false
        $coverage.Expired | Should Be $false
    }

    It 'rejects a malformed started timestamp for a both-target marker' {
        $marker = @{
            owner = 'test-lane'; reason = 'planned probe'; target = 'both'
            started = 'not-an-iso-timestamp'; expires = '2026-07-08T13:00:00Z'
            kill_receipt_ref = '2026-07-08T11:00:00Z'
        }
        ($marker | ConvertTo-Json) | Set-Content -Path $markerPath -Encoding utf8

        $m = Get-PlannedOutageMarker -Path $markerPath
        $m | Should BeNullOrEmpty
        (Test-MarkerCoversTarget -Marker $m -Target 'cockpit' -Now ([datetime]::Parse('2026-07-08T12:00:00Z'))).StandDown | Should Be $false
        (Test-MarkerCoversTarget -Marker $m -Target 'server' -Now ([datetime]::Parse('2026-07-08T12:00:00Z'))).StandDown | Should Be $false
    }

    It 'rejects a non-Z expires timestamp for a both-target marker' {
        $marker = @{
            owner = 'test-lane'; reason = 'planned probe'; target = 'both'
            started = '2026-07-08T11:00:00Z'; expires = '2026-07-08T13:00:00+00:00'
            kill_receipt_ref = '2026-07-08T11:00:00Z'
        }
        ($marker | ConvertTo-Json) | Set-Content -Path $markerPath -Encoding utf8

        Get-PlannedOutageMarker -Path $markerPath | Should BeNullOrEmpty
    }
}

Describe 'Invoke-CockpitWatchdogTick' {
    BeforeEach {
        $script:scratch = New-Scratch
        $script:heartbeatPath = Join-Path $scratch 'cockpit-heartbeat.json'
        $script:markerPath = Join-Path $scratch 'planned-outage.json'
        $script:restartLogPath = Join-Path $scratch 'restart-log.jsonl'
        $script:launcherPath = Join-Path $scratch 'launch-cockpit-instrumented.bat'
        'rem stub launcher' | Set-Content -Path $launcherPath -Encoding ascii
        $script:state = Get-DefaultWatchdogState

        # Self-tracked call counter, not Assert-MockCalled: this Pester install (3.4.0)
        # accumulates Assert-MockCalled's call history across It blocks within the same
        # Describe instead of resetting per-test (confirmed empirically -- a fresh Mock
        # in each BeforeEach did not zero the count). A private counter incremented by
        # the mock body, reset at the top of every BeforeEach, is unambiguous per-test.
        $script:launcherCalls = 0
        Mock Start-CockpitLauncher { $script:launcherCalls++; return [PSCustomObject]@{ Pid = 42424; Started = $true } }
    }
    AfterEach {
        Remove-Item -Path $scratch -Recurse -Force -ErrorAction SilentlyContinue
    }

    It 'fresh heartbeat (age well under threshold) -> Action none, launcher never invoked' {
        $now = [datetime]::Parse('2026-07-08T12:00:05Z').ToUniversalTime()
        $row = @{ ts = '2026-07-08T12:00:00Z'; pid = 1234; version = 'abc' }
        ($row | ConvertTo-Json) | Set-Content -Path $heartbeatPath -Encoding utf8

        $result = Invoke-CockpitWatchdogTick -Now $now -State $state `
            -HeartbeatPath $heartbeatPath -MarkerPath $markerPath -StaleThresholdSec 90 `
            -LauncherBatPath $launcherPath -RestartLogPath $restartLogPath

        $result.Action | Should Be 'none'
        $launcherCalls | Should Be 0
        (Test-Path $restartLogPath) | Should Be $false
    }

    It 'stale heartbeat -> Action relaunch, launcher invoked, restart-log row carries dead pid + age' {
        $now = [datetime]::Parse('2026-07-08T12:05:00Z').ToUniversalTime()
        $row = @{ ts = '2026-07-08T12:00:00Z'; pid = 1234; version = 'abc' }   # 300s old
        ($row | ConvertTo-Json) | Set-Content -Path $heartbeatPath -Encoding utf8

        $result = Invoke-CockpitWatchdogTick -Now $now -State $state `
            -HeartbeatPath $heartbeatPath -MarkerPath $markerPath -StaleThresholdSec 90 `
            -LauncherBatPath $launcherPath -RestartLogPath $restartLogPath

        $result.Action | Should Be 'relaunch'
        $launcherCalls | Should Be 1
        $logRow = (Get-Content -Path $restartLogPath -Raw) | ConvertFrom-Json
        $logRow.event | Should Be 'relaunch'
        $logRow.deadPid | Should Be 1234
        $logRow.relaunchPid | Should Be 42424
        @($logRow.PSObject.Properties.Name | Where-Object { $_ -eq 'backoffUntil' }).Count | Should Be 1
    }

    It 'missing/unreadable heartbeat -> treated as stale (cannot confirm liveness) -> relaunch' {
        $now = [datetime]::Parse('2026-07-08T12:05:00Z').ToUniversalTime()
        # heartbeatPath deliberately never written

        $result = Invoke-CockpitWatchdogTick -Now $now -State $state `
            -HeartbeatPath $heartbeatPath -MarkerPath $markerPath -StaleThresholdSec 90 `
            -LauncherBatPath $launcherPath -RestartLogPath $restartLogPath

        $result.Action | Should Be 'relaunch'
        $launcherCalls | Should Be 1
    }

    It 'valid planned-outage marker covering cockpit -> Action standdown, launcher never invoked' {
        $now = [datetime]::Parse('2026-07-08T12:05:00Z').ToUniversalTime()
        $row = @{ ts = '2026-07-08T12:00:00Z'; pid = 1234; version = 'abc' }   # stale on its own
        ($row | ConvertTo-Json) | Set-Content -Path $heartbeatPath -Encoding utf8
        $marker = @{
            owner = 'test-lane'; reason = 'planned probe'; target = 'cockpit'
            started = '2026-07-08T11:00:00Z'; expires = '2026-07-08T13:00:00Z'
            kill_receipt_ref = '2026-07-08T11:00:00Z'
        }
        ($marker | ConvertTo-Json) | Set-Content -Path $markerPath -Encoding utf8

        $script:standdownRows = @()
        $script:originalWriteRestartLogRow = (Get-Command Write-RestartLogRow).ScriptBlock
        Mock Write-RestartLogRow { param($Path, $Row) $script:standdownRows += [PSCustomObject]$Row; & $script:originalWriteRestartLogRow -Path $Path -Row $Row }
        $result = Invoke-CockpitWatchdogTick -Now $now -State $state `
            -HeartbeatPath $heartbeatPath -MarkerPath $markerPath -StaleThresholdSec 90 `
            -LauncherBatPath $launcherPath -RestartLogPath $restartLogPath

        $result.Action | Should Be 'standdown'
        $launcherCalls | Should Be 0
        $rows = @($standdownRows)
        $rows.Count | Should Be 1
        $rows[0].event | Should Be 'standdown'
        $rows[0].target | Should Be 'cockpit'
        $rows[0].owner | Should Be 'test-lane'
        $rows[0].backoffState | Should Be 'clear'
    }

    It 'repeated planned-outage cockpit polls emit one bounded stand-down decision row' {
        $now = [datetime]::Parse('2026-07-08T12:05:00Z').ToUniversalTime()
        $row = @{ ts = '2026-07-08T12:00:00Z'; pid = 1234; version = 'abc' }
        ($row | ConvertTo-Json) | Set-Content -Path $heartbeatPath -Encoding utf8
        $marker = @{
            owner = 'test-lane'; reason = 'planned probe'; target = 'cockpit'
            started = '2026-07-08T11:00:00Z'; expires = '2026-07-08T13:00:00Z'
            kill_receipt_ref = '2026-07-08T11:00:00Z'
        }
        ($marker | ConvertTo-Json) | Set-Content -Path $markerPath -Encoding utf8

        $first = Invoke-CockpitWatchdogTick -Now $now -State $state `
            -HeartbeatPath $heartbeatPath -MarkerPath $markerPath -StaleThresholdSec 90 `
            -LauncherBatPath $launcherPath -RestartLogPath $restartLogPath
        $second = Invoke-CockpitWatchdogTick -Now $now.AddSeconds(15) -State $state `
            -HeartbeatPath $heartbeatPath -MarkerPath $markerPath -StaleThresholdSec 90 `
            -LauncherBatPath $launcherPath -RestartLogPath $restartLogPath

        $first.Action | Should Be 'standdown'
        $second.Action | Should Be 'standdown'
        @(Get-Content -Path $restartLogPath | ForEach-Object { $_ | ConvertFrom-Json }).Count | Should Be 1
    }

    It 'reason-only marker change emits a fresh stand-down decision row' {
        $now = [datetime]::Parse('2026-07-08T12:05:00Z').ToUniversalTime()
        $row = @{ ts = '2026-07-08T12:00:00Z'; pid = 1234; version = 'abc' }
        ($row | ConvertTo-Json) | Set-Content -Path $heartbeatPath -Encoding utf8
        $marker = @{
            owner = 'test-lane'; reason = 'planned probe'; target = 'cockpit'
            started = '2026-07-08T11:00:00Z'; expires = '2026-07-08T13:00:00Z'
            kill_receipt_ref = '2026-07-08T11:00:00Z'
        }
        ($marker | ConvertTo-Json) | Set-Content -Path $markerPath -Encoding utf8

        Invoke-CockpitWatchdogTick -Now $now -State $state `
            -HeartbeatPath $heartbeatPath -MarkerPath $markerPath -StaleThresholdSec 90 `
            -LauncherBatPath $launcherPath -RestartLogPath $restartLogPath | Out-Null

        $marker.reason = 'corrected probe'
        ($marker | ConvertTo-Json) | Set-Content -Path $markerPath -Encoding utf8
        Invoke-CockpitWatchdogTick -Now $now.AddSeconds(15) -State $state `
            -HeartbeatPath $heartbeatPath -MarkerPath $markerPath -StaleThresholdSec 90 `
            -LauncherBatPath $launcherPath -RestartLogPath $restartLogPath | Out-Null

        $rows = @(Get-Content -Path $restartLogPath | ForEach-Object { $_ | ConvertFrom-Json })
        $rows.Count | Should Be 2
        $rows[0].reason | Should Be 'planned probe'
        $rows[1].reason | Should Be 'corrected probe'
    }
    It 'expired planned-outage marker -> resumes duty (relaunch) AND logs a marker-overrun row naming the owner' {
        $now = [datetime]::Parse('2026-07-08T14:00:00Z').ToUniversalTime()
        $row = @{ ts = '2026-07-08T12:00:00Z'; pid = 1234; version = 'abc' }   # very stale
        ($row | ConvertTo-Json) | Set-Content -Path $heartbeatPath -Encoding utf8
        $marker = @{
            owner = 'grow-runner-466'; reason = 'planned probe'; target = 'cockpit'
            started = '2026-07-08T11:00:00Z'; expires = '2026-07-08T13:00:00Z'
            kill_receipt_ref = '2026-07-08T11:00:00Z'
        }
        ($marker | ConvertTo-Json) | Set-Content -Path $markerPath -Encoding utf8

        $result = Invoke-CockpitWatchdogTick -Now $now -State $state `
            -HeartbeatPath $heartbeatPath -MarkerPath $markerPath -StaleThresholdSec 90 `
            -LauncherBatPath $launcherPath -RestartLogPath $restartLogPath

        $result.Action | Should Be 'relaunch'
        # @(...) forces array context -- PS 5.1 unwraps a single Where-Object match to a
        # scalar PSCustomObject, which has no .Count property (silently $null, not 1).
        $rows = @(Get-Content -Path $restartLogPath | ForEach-Object { $_ | ConvertFrom-Json })
        $overrun = @($rows | Where-Object { $_.event -eq 'marker-overrun' })
        $overrun[0].owner | Should Be 'grow-runner-466'
        @($rows | Where-Object { $_.event -eq 'relaunch' }).Count | Should Be 1
    }

    It '3 rapid deaths within the window trip crashloop-backoff; a 4th tick inside the cooldown does not relaunch again' {
        $baseTs = [datetime]::Parse('2026-07-08T12:00:00Z').ToUniversalTime()

        for ($i = 0; $i -lt 3; $i++) {
            $now = $baseTs.AddMinutes($i * 2)
            $row = @{ ts = $baseTs.AddMinutes($i * 2 - 5).ToString('o'); pid = (1000 + $i); version = 'abc' }
            ($row | ConvertTo-Json) | Set-Content -Path $heartbeatPath -Encoding utf8

            $r = Invoke-CockpitWatchdogTick -Now $now -State $state `
                -HeartbeatPath $heartbeatPath -MarkerPath $markerPath -StaleThresholdSec 90 `
                -LauncherBatPath $launcherPath -RestartLogPath $restartLogPath `
                -DeathWindowMinutes 10 -DeathThreshold 3 -BackoffMinutes 10
            $r.Action | Should Be 'relaunch'
        }

        $launcherCalls | Should Be 3
        $rows = @(Get-Content -Path $restartLogPath | ForEach-Object { $_ | ConvertFrom-Json })
        @($rows | Where-Object { $_.event -eq 'crashloop-backoff' }).Count | Should Be 1

        # 4th tick, 4 minutes after the window start -- inside the 10-minute cooldown
        # that tripped at the 3rd death (t=4min + 10min = t=14min).
        $now4 = $baseTs.AddMinutes(4 * 2)
        $row4 = @{ ts = $baseTs.AddMinutes(4 * 2 - 5).ToString('o'); pid = 1003; version = 'abc' }
        ($row4 | ConvertTo-Json) | Set-Content -Path $heartbeatPath -Encoding utf8

        $r4 = Invoke-CockpitWatchdogTick -Now $now4 -State $state `
            -HeartbeatPath $heartbeatPath -MarkerPath $markerPath -StaleThresholdSec 90 `
            -LauncherBatPath $launcherPath -RestartLogPath $restartLogPath `
            -DeathWindowMinutes 10 -DeathThreshold 3 -BackoffMinutes 10

        $r4.Action | Should Be 'backoff'
        $launcherCalls | Should Be 3   # still 3 -- no 4th restart
    }

    It 'escalates cockpit backoff across crash windows and resets after a quiet window' {
        $baseTs = [datetime]::Parse('2026-07-08T12:00:00Z').ToUniversalTime()
        $invoke = {
            param([datetime]$Now)
            $row = @{ ts = $Now.AddMinutes(-5).ToString('o'); pid = 1000; version = 'abc' }
            ($row | ConvertTo-Json) | Set-Content -Path $heartbeatPath -Encoding utf8
            Invoke-CockpitWatchdogTick -Now $Now -State $state `
                -HeartbeatPath $heartbeatPath -MarkerPath $markerPath -StaleThresholdSec 90 `
                -LauncherBatPath $launcherPath -RestartLogPath $restartLogPath `
                -DeathWindowMinutes 10 -DeathThreshold 3 -BackoffMinutes 10
        }

        0..2 | ForEach-Object { & $invoke $baseTs.AddMinutes($_ * 2) | Out-Null }
        $state.cockpit.backoffLevel | Should Be 1
        $state.cockpit.backoffUntil | Should Be $baseTs.AddMinutes(14).ToString('o')

        0..2 | ForEach-Object { & $invoke $baseTs.AddMinutes(15 + ($_ * 2)) | Out-Null }
        $state.cockpit.backoffLevel | Should Be 2
        $state.cockpit.backoffUntil | Should Be $baseTs.AddMinutes(39).ToString('o')

        0..2 | ForEach-Object { & $invoke $baseTs.AddMinutes(50 + ($_ * 2)) | Out-Null }
        $state.cockpit.backoffLevel | Should Be 1
        $state.cockpit.backoffState | Should Be 'active'
    }
}

Describe 'Invoke-ServerWatchdogTick' {
    BeforeEach {
        $script:scratch = New-Scratch
        $script:markerPath = Join-Path $scratch 'planned-outage.json'
        $script:restartLogPath = Join-Path $scratch 'restart-log.jsonl'
        $script:killReceiptsPath = Join-Path $scratch 'kill-receipts.jsonl'
        $script:state = Get-DefaultWatchdogState
        $script:cmdline = '"C:\fake\llama-server.exe" --port 8082'
        $script:exePath = 'C:\fake\llama-server.exe'

        # Self-tracked counters, not Assert-MockCalled -- see the cockpit Describe's
        # BeforeEach comment: this Pester install (3.4.0) accumulates Assert-MockCalled
        # call history across It blocks within a Describe rather than resetting per-test.
        $script:serverStartCalls = 0
        $script:stopProcessCalls = 0
        $script:killReceiptCalls = 0
        $script:healthCalls = 0
        Mock Start-ServerProcess { $script:serverStartCalls++; return [PSCustomObject]@{ Pid = 55555; Started = $true } }
        Mock Stop-Process { $script:stopProcessCalls++ }
        Mock Write-KillReceiptRow { $script:killReceiptCalls++ }
    }
    AfterEach {
        Remove-Item -Path $scratch -Recurse -Force -ErrorAction SilentlyContinue
    }

    It 'healthy server -> Action none, consecutiveFailures reset to 0' {
        Mock Test-ServerHealth { $script:healthCalls++; return $true }
        $state.server.consecutiveFailures = 1

        $result = Invoke-ServerWatchdogTick -Now ([datetime]::UtcNow) -State $state `
            -MarkerPath $markerPath -FailureThreshold 2 -ServerCmdline $cmdline -ServerExePath $exePath `
            -RestartLogPath $restartLogPath -KillReceiptsPath $killReceiptsPath

        $result.Action | Should Be 'none'
        $state.server.consecutiveFailures | Should Be 0
        $serverStartCalls | Should Be 0
    }

    It 'a single failure (below the 2-failure threshold) -> Action none, no kill, no relaunch' {
        Mock Test-ServerHealth { $script:healthCalls++; return $false }
        Mock Find-ServerProcess { return $null }

        $result = Invoke-ServerWatchdogTick -Now ([datetime]::UtcNow) -State $state `
            -MarkerPath $markerPath -FailureThreshold 2 -ServerCmdline $cmdline -ServerExePath $exePath `
            -RestartLogPath $restartLogPath -KillReceiptsPath $killReceiptsPath

        $result.Action | Should Be 'none'
        $state.server.consecutiveFailures | Should Be 1
        $serverStartCalls | Should Be 0
        $killReceiptCalls | Should Be 0
    }

    It 'two consecutive failures -> kill-receipt written BEFORE Stop-Process, then relaunch with the receipted cmdline' {
        Mock Test-ServerHealth { $script:healthCalls++; return $false }
        Mock Find-ServerProcess { return [PSCustomObject]@{ ProcessId = 9999; CommandLine = $cmdline } }
        $script:callOrder = New-Object System.Collections.Generic.List[string]
        Mock Write-KillReceiptRow { $script:callOrder.Add('receipt'); $script:killReceiptCalls++ }
        Mock Stop-Process { $script:callOrder.Add('kill'); $script:stopProcessCalls++ }

        $state.server.consecutiveFailures = 1   # one prior failure already recorded this window

        $result = Invoke-ServerWatchdogTick -Now ([datetime]::UtcNow) -State $state `
            -MarkerPath $markerPath -FailureThreshold 2 -ServerCmdline $cmdline -ServerExePath $exePath `
            -RestartLogPath $restartLogPath -KillReceiptsPath $killReceiptsPath

        $result.Action | Should Be 'relaunch'
        $callOrder.Count | Should Be 2
        $callOrder[0] | Should Be 'receipt'
        $callOrder[1] | Should Be 'kill'
        $serverStartCalls | Should Be 1
        $state.server.consecutiveFailures | Should Be 0
    }

    It 'server restart row carries health age and backoff state' {
        Mock Test-ServerHealth { $script:healthCalls++; return $false }
        Mock Find-ServerProcess { return $null }
        $state.server.consecutiveFailures = 1
        $state.server.lastHealthyAt = '2026-07-08T12:00:00Z'
        $now = [datetime]::Parse('2026-07-08T12:05:00Z').ToUniversalTime()

        $result = Invoke-ServerWatchdogTick -Now $now -State $state `
            -MarkerPath $markerPath -FailureThreshold 2 -ServerCmdline $cmdline -ServerExePath $exePath `
            -RestartLogPath $restartLogPath -KillReceiptsPath $killReceiptsPath

        $result.Action | Should Be 'relaunch'
        $row = (Get-Content -Path $restartLogPath -Raw) | ConvertFrom-Json
        @($row.PSObject.Properties.Name | Where-Object { $_ -eq 'healthAgeSec' }).Count | Should Be 1
        $row.healthAgeSec | Should Be 300
        @($row.PSObject.Properties.Name | Where-Object { $_ -eq 'backoffUntil' }).Count | Should Be 1
    }

    It 'no live process found at the failure threshold (already dead) -> no kill-receipt, still relaunches' {
        Mock Test-ServerHealth { $script:healthCalls++; return $false }
        Mock Find-ServerProcess { return $null }
        $state.server.consecutiveFailures = 1

        $result = Invoke-ServerWatchdogTick -Now ([datetime]::UtcNow) -State $state `
            -MarkerPath $markerPath -FailureThreshold 2 -ServerCmdline $cmdline -ServerExePath $exePath `
            -RestartLogPath $restartLogPath -KillReceiptsPath $killReceiptsPath

        $result.Action | Should Be 'relaunch'
        $killReceiptCalls | Should Be 0
        $stopProcessCalls | Should Be 0
        $serverStartCalls | Should Be 1
    }

    It 'valid planned-outage marker targeting "both" -> server watchdog stands down too, never polls health' {
        $marker = @{
            owner = 'probe-lane'; reason = 'gpu offload probe'; target = 'both'
            started = (Get-Date).ToUniversalTime().ToString('o')
            expires = (Get-Date).AddMinutes(10).ToUniversalTime().ToString('o')
            kill_receipt_ref = '2026-07-08T17:10:32Z'
        }
        ($marker | ConvertTo-Json) | Set-Content -Path $markerPath -Encoding utf8
        Mock Test-ServerHealth { $script:healthCalls++; return $false }

        $script:standdownRows = @()
        $script:originalWriteRestartLogRow = (Get-Command Write-RestartLogRow).ScriptBlock
        Mock Write-RestartLogRow { param($Path, $Row) $script:standdownRows += [PSCustomObject]$Row; & $script:originalWriteRestartLogRow -Path $Path -Row $Row }
        $result = Invoke-ServerWatchdogTick -Now ([datetime]::UtcNow) -State $state `
            -MarkerPath $markerPath -FailureThreshold 2 -ServerCmdline $cmdline -ServerExePath $exePath `
            -RestartLogPath $restartLogPath -KillReceiptsPath $killReceiptsPath

        $result.Action | Should Be 'standdown'
        $healthCalls | Should Be 0
        $rows = @($standdownRows)
        $rows.Count | Should Be 1
        $rows[0].event | Should Be 'standdown'
        $rows[0].target | Should Be 'server'
        $rows[0].owner | Should Be 'probe-lane'
        $rows[0].backoffState | Should Be 'clear'
    }

    It 'healthy then two failed server polls preserve last healthy age and bound stand-down-independent state' {
        $healthyAt = [datetime]::Parse('2026-07-08T12:00:00Z').ToUniversalTime()
        $failedAt = $healthyAt.AddMinutes(1)
        $relaunchAt = $healthyAt.AddMinutes(5)
        $script:healthCalls = 0
        Mock Test-ServerHealth { $script:healthCalls++; return ($script:healthCalls -eq 1) }
        Mock Find-ServerProcess { return $null }
        $state.server.consecutiveFailures = 0

        (Invoke-ServerWatchdogTick -Now $healthyAt -State $state `
            -MarkerPath $markerPath -FailureThreshold 2 -ServerCmdline $cmdline -ServerExePath $exePath `
            -RestartLogPath $restartLogPath -KillReceiptsPath $killReceiptsPath).Action | Should Be 'none'
        (Invoke-ServerWatchdogTick -Now $failedAt -State $state `
            -MarkerPath $markerPath -FailureThreshold 2 -ServerCmdline $cmdline -ServerExePath $exePath `
            -RestartLogPath $restartLogPath -KillReceiptsPath $killReceiptsPath).Action | Should Be 'none'
        $result = Invoke-ServerWatchdogTick -Now $relaunchAt -State $state `
            -MarkerPath $markerPath -FailureThreshold 2 -ServerCmdline $cmdline -ServerExePath $exePath `
            -RestartLogPath $restartLogPath -KillReceiptsPath $killReceiptsPath

        $result.Action | Should Be 'relaunch'
        $state.server.lastHealthyAt | Should Be $healthyAt.ToString('o')
        $state.server.lastHealthCheckAt | Should Be $relaunchAt.ToString('o')
        $row = (Get-Content -Path $restartLogPath -Raw) | ConvertFrom-Json
        $row.healthAgeSec | Should Be 300
    }

    It 'escalates server backoff across crash windows and resets after a quiet window' {
        $baseTs = [datetime]::Parse('2026-07-08T12:00:00Z').ToUniversalTime()
        Mock Test-ServerHealth { $false }
        Mock Find-ServerProcess { return $null }
        $invoke = {
            param([datetime]$Now)
            $state.server.consecutiveFailures = 1
            Invoke-ServerWatchdogTick -Now $Now -State $state -FailureThreshold 2 `
                -MarkerPath $markerPath -ServerCmdline $cmdline -ServerExePath $exePath `
                -RestartLogPath $restartLogPath -KillReceiptsPath $killReceiptsPath `
                -DeathWindowMinutes 10 -DeathThreshold 3 -BackoffMinutes 10
        }

        0..2 | ForEach-Object { & $invoke $baseTs.AddMinutes($_ * 2) | Out-Null }
        $state.server.backoffLevel | Should Be 1
        $state.server.backoffUntil | Should Be $baseTs.AddMinutes(14).ToString('o')

        0..2 | ForEach-Object { & $invoke $baseTs.AddMinutes(15 + ($_ * 2)) | Out-Null }
        $state.server.backoffLevel | Should Be 2
        $state.server.backoffUntil | Should Be $baseTs.AddMinutes(39).ToString('o')

        0..2 | ForEach-Object { & $invoke $baseTs.AddMinutes(50 + ($_ * 2)) | Out-Null }
        $state.server.backoffLevel | Should Be 1
        $state.server.backoffState | Should Be 'active'
    }
}

Describe 'Watchdog state migration' {
    BeforeEach { $script:scratch = New-Scratch; $script:statePath = Join-Path $scratch 'watchdog-state.json' }
    AfterEach { Remove-Item -Path $scratch -Recurse -Force -ErrorAction SilentlyContinue }

    It 'maps legacy lastHealthAt to lastHealthCheckAt without claiming a successful health' {
        $legacy = @{ server = @{ deaths = @(); backoffUntil = $null; consecutiveFailures = 1; lastHealthAt = '2026-07-08T12:00:00Z' }; cockpit = @{ deaths = @(); backoffUntil = $null; consecutiveFailures = 0 }; freshness = @{} }
        ($legacy | ConvertTo-Json -Depth 8) | Set-Content -Path $statePath -Encoding utf8

        $migrated = Read-WatchdogState -Path $statePath

        $migrated.server.lastHealthCheckAt | Should Be '2026-07-08T12:00:00Z'
        $migrated.server.lastHealthyAt | Should Be $null
    }
}

Describe 'Stand-down receipt append atomicity' {
    BeforeEach {
        $script:scratch = New-Scratch
        $script:restartLogPath = Join-Path $scratch 'restart-log.jsonl'
        $script:state = Get-DefaultWatchdogState
        $script:marker = @{
            owner = 'test-lane'; reason = 'planned probe'; target = 'cockpit'
            started = '2026-07-08T11:00:00Z'; expires = '2026-07-08T13:00:00Z'
            kill_receipt_ref = '2026-07-08T11:00:00Z'
        }
    }
    AfterEach {
        Remove-Item -Path $scratch -Recurse -Force -ErrorAction SilentlyContinue
    }

    It 'does not consume dedupe state when the first receipt append fails, then retries once' {
        $decisionKey = Get-StandDownDecisionKey -Marker $marker
        $row = @{ ts = '2026-07-08T12:05:00Z'; target = 'cockpit'; event = 'standdown'; decision = 'planned-outage'; reason = $marker.reason }
        $script:appendAttempts = 0
        $script:originalWriteRestartLogRow = (Get-Command Write-RestartLogRow).ScriptBlock
        Mock Write-RestartLogRow {
            param($Path, $Row)
            $script:appendAttempts++
            if ($script:appendAttempts -eq 1) { throw 'simulated append failure' }
            & $script:originalWriteRestartLogRow -Path $Path -Row $Row
        }

        $failed = $false
        try { Write-StandDownDecision -Path $restartLogPath -Row $row -TargetState $state.cockpit -DecisionKey $decisionKey | Out-Null }
        catch { $failed = $true }

        $failed | Should Be $true
        $state.cockpit.standdownDecisionKey | Should Be $null
        (Test-Path $restartLogPath) | Should Be $false

        (Write-StandDownDecision -Path $restartLogPath -Row $row -TargetState $state.cockpit -DecisionKey $decisionKey) | Should Be $true
        (Write-StandDownDecision -Path $restartLogPath -Row $row -TargetState $state.cockpit -DecisionKey $decisionKey) | Should Be $false
        $state.cockpit.standdownDecisionKey | Should Be $decisionKey
        $script:appendAttempts | Should Be 2
        @(Get-Content -Path $restartLogPath | ForEach-Object { $_ | ConvertFrom-Json }).Count | Should Be 1
    }
}
Describe 'Test-WatchdogAlreadyRunning (idempotent start)' {
    BeforeEach {
        $script:scratch = New-Scratch
        $script:pidFilePath = Join-Path $scratch 'liveness-watchdog.pid'
    }
    AfterEach {
        Remove-Item -Path $scratch -Recurse -Force -ErrorAction SilentlyContinue
    }

    It 'no pidfile -> not running' {
        Test-WatchdogAlreadyRunning -PidFilePath $pidFilePath | Should Be $false
    }

    It 'pidfile points at a live process whose cmdline matches this script -> already running (refuse a 2nd instance)' {
        '4242' | Set-Content -Path $pidFilePath -Encoding ascii
        Mock Get-CimInstance { return [PSCustomObject]@{ ProcessId = 4242; CommandLine = 'powershell.exe -File ...\liveness-watchdog.ps1' } }

        Test-WatchdogAlreadyRunning -PidFilePath $pidFilePath | Should Be $true
    }

    It 'pidfile points at a PID that no longer exists (or is unrelated) -> not running' {
        '4243' | Set-Content -Path $pidFilePath -Encoding ascii
        Mock Get-CimInstance { return $null }

        Test-WatchdogAlreadyRunning -PidFilePath $pidFilePath | Should Be $false
    }
}

Describe 'Freshness leg (issue #545): auto-pull main tree from public/master' {
    BeforeEach {
        $script:scratch = New-Scratch
        $script:repoPath = Join-Path $scratch 'test-repo'
        $script:markerPath = Join-Path $scratch 'planned-outage.json'
        $script:ledgerPath = Join-Path $scratch 'activity-ledger.jsonl'
        New-Item -ItemType Directory -Path $repoPath -Force | Out-Null
    }
    AfterEach {
        Remove-Item -Path $scratch -Recurse -Force -ErrorAction SilentlyContinue
    }

    It 'tree is current (0 commits behind) -> no action' {
        $now = [datetime]::UtcNow
        $state = Get-DefaultWatchdogState

        $result = Invoke-FreshnessWatchdogTick -Now $now -State $state -RepoPath $repoPath `
            -MarkerPath $markerPath -ActivityLedgerPath $ledgerPath -WhatIfMode $true -InjectedCommitsBehind 0

        $result.Action | Should Be 'current'
        Test-Path $ledgerPath | Should Be $false  # No activity event should be written
    }

    It 'tree is behind and clean -> pull and append advance event' {
        $now = [datetime]::UtcNow
        $state = Get-DefaultWatchdogState

        $result = Invoke-FreshnessWatchdogTick -Now $now -State $state -RepoPath $repoPath `
            -MarkerPath $markerPath -ActivityLedgerPath $ledgerPath -WhatIfMode $true `
            -InjectedCommitsBehind 5 -InjectedDirtyState $false

        $result.Action | Should Be 'advanced'

        # Check that activity ledger was written
        Test-Path $ledgerPath | Should Be $true
        $event = Get-Content -Path $ledgerPath | ConvertFrom-Json
        $event.source | Should Be 'watchdog'
        $event.line | Should Match 'tree advanced'
        $event.line | Should Match '5 commits'
    }

    It 'tree is behind and dirty -> append LOUD residue event, touch nothing' {
        $now = [datetime]::UtcNow
        $state = Get-DefaultWatchdogState

        $result = Invoke-FreshnessWatchdogTick -Now $now -State $state -RepoPath $repoPath `
            -MarkerPath $markerPath -ActivityLedgerPath $ledgerPath -WhatIfMode $true `
            -InjectedCommitsBehind 3 -InjectedDirtyState $true

        $result.Action | Should Be 'residue'

        # Check that residue event was written
        Test-Path $ledgerPath | Should Be $true
        $event = Get-Content -Path $ledgerPath | ConvertFrom-Json
        $event.source | Should Be 'watchdog'
        $event.line | Should Match 'RESIDUE'
        $event.line | Should Match '3 commits behind'
    }

    It 'planned-outage marker covering "both" -> stand down and skip poll' {
        $now = [datetime]::Parse('2026-07-08T12:00:00Z').ToUniversalTime()
        $marker = @{
            owner = 'test-lane'; reason = 'training'; target = 'both'
            started = '2026-07-08T11:00:00Z'; expires = '2026-07-08T13:00:00Z'
            kill_receipt_ref = '2026-07-08T11:00:00Z'
        }
        ($marker | ConvertTo-Json) | Set-Content -Path $markerPath -Encoding utf8

        $state = Get-DefaultWatchdogState
        $result = Invoke-FreshnessWatchdogTick -Now $now -State $state -RepoPath $repoPath `
            -MarkerPath $markerPath -ActivityLedgerPath $ledgerPath -WhatIfMode $true

        $result.Action | Should Be 'standdown'
        Test-Path $ledgerPath | Should Be $false  # No activity event
    }

    It 'Get-RepoHeadSha in WhatIf mode -> returns mock SHA' {
        $sha = Get-RepoHeadSha -RepoPath $repoPath -WhatIfMode $true
        $sha | Should Match 'mock-sha'
    }

    It 'Test-RepoClean in WhatIf mode with clean state -> returns true' {
        $clean = Test-RepoClean -RepoPath $repoPath -WhatIfMode $true -InjectedDirtyState $false
        $clean | Should Be $true
    }

    It 'Test-RepoClean in WhatIf mode with dirty state -> returns false' {
        $clean = Test-RepoClean -RepoPath $repoPath -WhatIfMode $true -InjectedDirtyState $true
        $clean | Should Be $false
    }

    It 'Get-CommitsBehind in WhatIf mode -> returns injected count' {
        $count = Get-CommitsBehind -RepoPath $repoPath -WhatIfMode $true -InjectedCount 7
        $count | Should Be 7
    }

    It 'Invoke-GitPullFfOnly in WhatIf mode -> returns success' {
        $result = Invoke-GitPullFfOnly -RepoPath $repoPath -WhatIfMode $true
        $result | Should Be $true
    }
}

Describe 'Marker-expiry enforcement leg (issue #464 receipt fix)' {
    BeforeEach {
        $script:scratch = New-Scratch
        $script:markerPath = Join-Path $scratch 'planned-outage.json'
        $script:ledgerPath = Join-Path $scratch 'activity-ledger.jsonl'
    }
    AfterEach {
        Remove-Item -Path $scratch -Recurse -Force -ErrorAction SilentlyContinue
    }

    It 'marker with future expires -> Action none, marker untouched' {
        $now = [datetime]::Parse('2026-07-09T12:00:00Z').ToUniversalTime()
        $marker = @{
            owner = 'test-lane'; reason = 'probe'; target = 'both'
            started = '2026-07-09T11:00:00Z'; expires = '2026-07-09T13:00:00Z'
            kill_receipt_ref = '2026-07-09T11:00:00Z'
        }
        ($marker | ConvertTo-Json) | Set-Content -Path $markerPath -Encoding utf8

        $result = Invoke-MarkerExpiryEnforcementTick -Now $now -MarkerPath $markerPath `
            -ActivityLedgerPath $ledgerPath -WhatIfMode $true

        $result.Action | Should Be 'none'
        Test-Path $markerPath | Should Be $true  # Marker should remain untouched
        Test-Path $ledgerPath | Should Be $false  # No activity event
    }

    It 'marker with past expires (expired) -> archive marker, append OVERRUN event' {
        $now = [datetime]::Parse('2026-07-09T12:30:00Z').ToUniversalTime()
        $marker = @{
            owner = 'eps0rider'; reason = 'probe'; target = 'both'
            started = '2026-07-09T11:00:00Z'; expires = '2026-07-09T11:41:25Z'
            kill_receipt_ref = '2026-07-09T11:00:00Z'
        }
        ($marker | ConvertTo-Json) | Set-Content -Path $markerPath -Encoding utf8

        $result = Invoke-MarkerExpiryEnforcementTick -Now $now -MarkerPath $markerPath `
            -ActivityLedgerPath $ledgerPath -WhatIfMode $true

        $result.Action | Should Be 'archived'
        $result.Detail | Should Match 'overrun'

        # Check that activity event was written with owner and overrun minutes
        Test-Path $ledgerPath | Should Be $true
        $event = Get-Content -Path $ledgerPath | ConvertFrom-Json
        $event.source | Should Be 'watchdog'
        $event.line | Should Match 'MARKER OVERRUN'
        $event.line | Should Match 'eps0rider'
        $event.line | Should Match 'overrun='
    }

    It 'no marker file -> Action none' {
        $now = [datetime]::UtcNow
        $result = Invoke-MarkerExpiryEnforcementTick -Now $now -MarkerPath $markerPath `
            -ActivityLedgerPath $ledgerPath -WhatIfMode $true

        $result.Action | Should Be 'none'
        Test-Path $ledgerPath | Should Be $false
    }

    It 'Archive-StaleMarker renames marker to planned-outage-expired-<ts>.json' {
        $now = [datetime]::Parse('2026-07-09T12:30:45Z').ToUniversalTime()
        $marker = @{
            owner = 'test'; reason = 'probe'; target = 'both'
            started = '2026-07-09T11:00:00Z'; expires = '2026-07-09T11:41:25Z'
            kill_receipt_ref = '2026-07-09T11:00:00Z'
        }
        ($marker | ConvertTo-Json) | Set-Content -Path $markerPath -Encoding utf8

        $archivedPath = Archive-StaleMarker -MarkerPath $markerPath -Now $now

        Test-Path $markerPath | Should Be $false  # Original removed
        $archivedPath | Should Match 'planned-outage-expired'
        $archivedPath | Should Match '20260709T123045Z'
    }
}

Describe 'Resolve-CanonicalRepoRoot (PR954 round 2 -- strict resolver, same contract as repo-root.ts)' {
    BeforeEach {
        $script:scratch = New-Scratch
    }
    AfterEach {
        Remove-Item -Path $scratch -Recurse -Force -ErrorAction SilentlyContinue
    }

    function New-MarkerRoot {
        param([Parameter(Mandatory)][string]$Root)
        New-Item -ItemType Directory -Path (Join-Path $Root 'tools\ember-cli') -Force | Out-Null
        Set-Content -Path (Join-Path $Root 'GOAL.md') -Value "# fixture`n" -Encoding utf8
    }

    It 'a standalone marker-valid root with no .git at all is accepted as-is (git-less deployment)' {
        $root = Join-Path $scratch 'standalone-repo'
        New-MarkerRoot -Root $root
        Test-Path (Join-Path $root '.git') | Should Be $false

        Resolve-CanonicalRepoRoot -Root $root | Should Be $root
    }

    It 'a plain main checkout (.git is a directory) is returned unchanged' {
        $root = Join-Path $scratch 'main-checkout'
        New-MarkerRoot -Root $root
        New-Item -ItemType Directory -Path (Join-Path $root '.git') -Force | Out-Null

        Resolve-CanonicalRepoRoot -Root $root | Should Be $root
    }

    It 'a worktree .git FILE pointing at <main>/.git/worktrees/<name> canonicalizes to the marker-valid main root' {
        $mainRoot = Join-Path $scratch 'main-checkout'
        New-MarkerRoot -Root $mainRoot
        $gitdirTarget = Join-Path $mainRoot '.git\worktrees\lane'
        New-Item -ItemType Directory -Path $gitdirTarget -Force | Out-Null

        $worktreeRoot = Join-Path $scratch 'wt\lane'
        New-MarkerRoot -Root $worktreeRoot
        # PR954 round 3: Set-Content -Value "...`n" appends ITS OWN trailing `r`n on top
        # of the literal `n already in the string, producing a real on-disk double
        # newline that the round-3 exact-single-record parser correctly rejects (a real
        # git-worktree .git file has exactly one trailing newline, written by git itself,
        # never through Set-Content) -- WriteAllText gives byte-exact control instead.
        [System.IO.File]::WriteAllText((Join-Path $worktreeRoot '.git'), "gitdir: $gitdirTarget`n")

        Resolve-CanonicalRepoRoot -Root $worktreeRoot | Should Be $mainRoot
    }

    It 'a .git FILE whose content does not match the gitdir: shape at all THROWS (never silently returns the worktree root)' {
        $root = Join-Path $scratch 'malformed-gitfile'
        New-MarkerRoot -Root $root
        Set-Content -Path (Join-Path $root '.git') -Value "not a gitdir pointer at all`n" -Encoding utf8

        { Resolve-CanonicalRepoRoot -Root $root } | Should Throw
    }

    It 'a .git FILE whose gitdir does not match <main>/.git/worktrees/<name> (e.g. a submodule) THROWS' {
        $root = Join-Path $scratch 'submodule-like'
        New-MarkerRoot -Root $root
        $modulesDir = Join-Path $scratch 'parent-repo\.git\modules\sub'
        New-Item -ItemType Directory -Path $modulesDir -Force | Out-Null
        Set-Content -Path (Join-Path $root '.git') -Value "gitdir: $modulesDir`n" -Encoding utf8

        { Resolve-CanonicalRepoRoot -Root $root } | Should Throw
    }

    It 'a worktree .git FILE resolving to a main checkout that fails the marker check THROWS naming "worktree"' {
        $mainRoot = Join-Path $scratch 'main-checkout'
        New-Item -ItemType Directory -Path (Join-Path $mainRoot '.git\worktrees\lane') -Force | Out-Null
        # Deliberately NOT calling New-MarkerRoot on $mainRoot -- it never validates.

        $worktreeRoot = Join-Path $scratch 'wt\lane'
        New-MarkerRoot -Root $worktreeRoot
        $gitdirTarget = Join-Path $mainRoot '.git\worktrees\lane'
        Set-Content -Path (Join-Path $worktreeRoot '.git') -Value "gitdir: $gitdirTarget`n" -Encoding utf8

        { Resolve-CanonicalRepoRoot -Root $worktreeRoot } | Should Throw 'worktree'
    }
}

Describe 'Resolve-CanonicalRepoRoot (PR954 round 3 -- exact single-record parser + dangling-target check)' {
    BeforeEach {
        $script:scratch = New-Scratch
    }
    AfterEach {
        Remove-Item -Path $scratch -Recurse -Force -ErrorAction SilentlyContinue
    }

    function New-MarkerRoot3 {
        param([Parameter(Mandatory)][string]$Root)
        New-Item -ItemType Directory -Path (Join-Path $Root 'tools\ember-cli') -Force | Out-Null
        Set-Content -Path (Join-Path $Root 'GOAL.md') -Value "# fixture`n" -Encoding utf8
    }

    It 'junk-prefixed content (a valid gitdir: line preceded by garbage) is REJECTED, not silently matched' {
        # Main root VALIDATES and the worktrees/lane target EXISTS, so the only possible
        # cause of a throw here is the exact-single-record parser rejecting the junk
        # prefix -- isolates this from the "main doesn't validate" / dangling-target paths.
        $mainRoot = Join-Path $scratch 'main-for-junk'
        $gitdirTarget = Join-Path $mainRoot '.git\worktrees\lane'
        New-Item -ItemType Directory -Path $gitdirTarget -Force | Out-Null
        New-MarkerRoot3 -Root $mainRoot

        $root = Join-Path $scratch 'junk-prefixed'
        New-MarkerRoot3 -Root $root
        Set-Content -Path (Join-Path $root '.git') -Value "junk`ngitdir: $gitdirTarget`n" -Encoding utf8

        { Resolve-CanonicalRepoRoot -Root $root } | Should Throw
    }

    It 'a trailing junk line AFTER the gitdir: record is also REJECTED' {
        $mainRoot = Join-Path $scratch 'main-for-junk2'
        $gitdirTarget = Join-Path $mainRoot '.git\worktrees\lane'
        New-Item -ItemType Directory -Path $gitdirTarget -Force | Out-Null
        New-MarkerRoot3 -Root $mainRoot

        $root = Join-Path $scratch 'junk-suffixed'
        New-MarkerRoot3 -Root $root
        Set-Content -Path (Join-Path $root '.git') -Value "gitdir: $gitdirTarget`nextra junk`n" -Encoding utf8

        { Resolve-CanonicalRepoRoot -Root $root } | Should Throw
    }

    It 'a single gitdir: record with exactly one trailing newline is ACCEPTED (the common on-disk shape)' {
        $mainRoot = Join-Path $scratch 'single-record-main'
        $gitdirTarget = Join-Path $mainRoot '.git\worktrees\lane'
        New-Item -ItemType Directory -Path $gitdirTarget -Force | Out-Null
        New-MarkerRoot3 -Root $mainRoot

        $worktreeRoot = Join-Path $scratch 'single-record-wt'
        New-MarkerRoot3 -Root $worktreeRoot
        # WriteAllText (not Set-Content, which appends its OWN trailing `r`n on top of
        # the literal `n already in the string) for byte-exact single-trailing-newline
        # content -- the real on-disk shape `git worktree add` produces.
        [System.IO.File]::WriteAllText((Join-Path $worktreeRoot '.git'), "gitdir: $gitdirTarget`n")

        Resolve-CanonicalRepoRoot -Root $worktreeRoot | Should Be $mainRoot
    }

    It 'a single gitdir: record with NO trailing newline is also ACCEPTED' {
        $mainRoot = Join-Path $scratch 'no-newline-main'
        $gitdirTarget = Join-Path $mainRoot '.git\worktrees\lane'
        New-Item -ItemType Directory -Path $gitdirTarget -Force | Out-Null
        New-MarkerRoot3 -Root $mainRoot

        $worktreeRoot = Join-Path $scratch 'no-newline-wt'
        New-MarkerRoot3 -Root $worktreeRoot
        # Set-Content always appends the host's newline; use WriteAllText for a truly
        # newline-free file.
        [System.IO.File]::WriteAllText((Join-Path $worktreeRoot '.git'), "gitdir: $gitdirTarget")

        Resolve-CanonicalRepoRoot -Root $worktreeRoot | Should Be $mainRoot
    }

    It 'a gitdir: pointer whose target directory does not exist on disk is REJECTED (dangling pointer)' {
        $mainRoot = Join-Path $scratch 'dangling-main'
        New-Item -ItemType Directory -Path $mainRoot -Force | Out-Null
        New-MarkerRoot3 -Root $mainRoot
        # Deliberately do NOT create <mainRoot>/.git/worktrees/lane.
        $danglingTarget = Join-Path $mainRoot '.git\worktrees\lane'
        Test-Path $danglingTarget | Should Be $false

        $worktreeRoot = Join-Path $scratch 'dangling-wt'
        New-MarkerRoot3 -Root $worktreeRoot
        Set-Content -Path (Join-Path $worktreeRoot '.git') -Value "gitdir: $danglingTarget`n" -Encoding utf8

        { Resolve-CanonicalRepoRoot -Root $worktreeRoot } | Should Throw
    }

    It 'a gitdir: pointer whose target exists but is a FILE, not a directory, is also REJECTED' {
        $mainRoot = Join-Path $scratch 'file-target-main'
        New-Item -ItemType Directory -Path (Join-Path $mainRoot '.git\worktrees') -Force | Out-Null
        New-MarkerRoot3 -Root $mainRoot
        $fileNotDir = Join-Path $mainRoot '.git\worktrees\lane'
        Set-Content -Path $fileNotDir -Value 'not a directory' -Encoding utf8

        $worktreeRoot = Join-Path $scratch 'file-target-wt'
        New-MarkerRoot3 -Root $worktreeRoot
        Set-Content -Path (Join-Path $worktreeRoot '.git') -Value "gitdir: $fileNotDir`n" -Encoding utf8

        { Resolve-CanonicalRepoRoot -Root $worktreeRoot } | Should Throw
    }
}

Describe 'PR954 round 2 -- watchdog script fails closed before HeartbeatPath construction on an unresolvable repo root' {
    It 'invoking the script with -RepoRoot pointed at a malformed worktree .git FILE throws, never silently proceeds' {
        $scratch = New-Scratch
        try {
            $root = Join-Path $scratch 'malformed-gitfile'
            New-Item -ItemType Directory -Path (Join-Path $root 'tools\ember-cli') -Force | Out-Null
            Set-Content -Path (Join-Path $root 'GOAL.md') -Value "# fixture`n" -Encoding utf8
            Set-Content -Path (Join-Path $root '.git') -Value "not a gitdir pointer at all`n" -Encoding utf8

            { . $scriptPath -RepoRoot $root } | Should Throw
        } finally {
            Remove-Item -Path $scratch -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

# ---------------------------------------------------------------------------------------
# PR954 round 4 -- reviewer reject of round 3 (811dd9d2):
#   P1: Test-Path -PathType Leaf swallows access errors and returns $false on anything it
#       can't classify (permission-denied, locked, unclassifiable) -- Resolve-CanonicalRepoRoot
#       then read that $false as "definitely absent" and fell open to the worktree-local
#       heartbeat path. Repaired via Get-DotGitItemState (Get-Item + terminating errors,
#       above): only a genuine ItemNotFoundException resolves to 'Absent'; every other
#       failure throws.
#   Coverage gaps closed as fixtures at the WATCHDOG-INVOCATION level (full `. $scriptPath
#   -RepoRoot $root`, never just the isolated Resolve-CanonicalRepoRoot function):
#     (1) a RELATIVE gitdir pointer resolves correctly (never silently mis-resolves or
#         throws) -- proves the relative-path Join-Path-against-$Root logic is exercised
#         end-to-end, not just at the function level.
#     (2) a DANGLING gitdir pointer target throws at full invocation (round 3 already
#         covers this at the Resolve-CanonicalRepoRoot function level; this closes the
#         same gap one layer up, at script boot).
#     (3) a genuinely UNREADABLE .git pointer file (real ACL deny, not just malformed
#         content) throws at full invocation, never silently falls through.
# ---------------------------------------------------------------------------------------

Describe 'PR954 round 4 -- P1 repair: Get-Item terminating-error classification never falls open on an unclassifiable .git' {
    BeforeEach {
        $script:scratch = New-Scratch
    }
    AfterEach {
        Remove-Item -Path $scratch -Recurse -Force -ErrorAction SilentlyContinue
    }

    function New-MarkerRoot4 {
        param([Parameter(Mandatory)][string]$Root)
        New-Item -ItemType Directory -Path (Join-Path $Root 'tools\ember-cli') -Force | Out-Null
        Set-Content -Path (Join-Path $Root 'GOAL.md') -Value "# fixture`n" -Encoding utf8
    }

    It 'an unclassifiable .git (Get-Item throws access-denied, the Test-Path fail-open repro) THROWS, never silently falls through to the worktree-local root' {
        # The gitdir target is a VALID <main>/.git/worktrees/<name> shape pointing at a
        # marker-valid main root -- so this test discriminates the P1 defect specifically:
        # old code (Test-Path -PathType Leaf, unaffected by mocking Get-Item) resolves
        # this fixture successfully with NO throw, while new code (Get-Item-based
        # classification) throws because Get-Item is mocked to fail. A gitdir target that
        # was invalid on its own would throw under BOTH old and new code for an unrelated
        # reason (wrong gitdir shape), which would not actually prove this repair.
        $mainRoot = Join-Path $scratch 'unclassifiable-main'
        $gitdirTarget = Join-Path $mainRoot '.git\worktrees\lane'
        New-Item -ItemType Directory -Path $gitdirTarget -Force | Out-Null
        New-MarkerRoot4 -Root $mainRoot

        $root = Join-Path $scratch 'unclassifiable-gitfile'
        New-MarkerRoot4 -Root $root
        # NOTE: named $script:p1TargetDotGit (never bare $dotGit) deliberately -- Mock's
        # -ParameterFilter scriptblock is invoked dynamically from INSIDE
        # Resolve-CanonicalRepoRoot's own call frame (which has ITS OWN local $dotGit), so
        # a filter referencing a bare $dotGit resolves to the CALLEE's variable (trivially
        # always equal to itself) rather than this test's fixture path -- a real defect
        # hit while writing this fixture, not a hypothetical.
        $script:p1TargetDotGit = Join-Path $root '.git'
        [System.IO.File]::WriteAllText($script:p1TargetDotGit, "gitdir: $gitdirTarget`n")

        # Reproduces the exact P1 defect deterministically: a Get-Item failure that is
        # NEITHER a genuine ItemNotFoundException NOR a successful stat -- the shape
        # Test-Path used to swallow and silently report as "absent".
        Mock Get-Item { throw [System.UnauthorizedAccessException]::new("Access to the path '$($script:p1TargetDotGit)' is denied.") } -ParameterFilter { $LiteralPath -eq $script:p1TargetDotGit }

        { Resolve-CanonicalRepoRoot -Root $root } | Should Throw
    }

    It 'control: a genuinely absent .git (no mock) still resolves to $Root unchanged -- the P1 repair does not regress the standalone-deployment case' {
        $root = Join-Path $scratch 'standalone-p1-control'
        New-MarkerRoot4 -Root $root
        Test-Path (Join-Path $root '.git') | Should Be $false

        Resolve-CanonicalRepoRoot -Root $root | Should Be $root
    }
}

Describe 'PR954 round 4 -- watchdog-invocation-level fixtures: relative gitdir, dangling target, unreadable .git' {
    function New-MarkerRoot4Boot {
        param([Parameter(Mandatory)][string]$Root)
        New-Item -ItemType Directory -Path (Join-Path $Root 'tools\ember-cli') -Force | Out-Null
        Set-Content -Path (Join-Path $Root 'GOAL.md') -Value "# fixture`n" -Encoding utf8
    }

    It 'a RELATIVE gitdir pointer (relative to the .git FILE''s own directory) resolves to the marker-valid main root at full script boot' {
        $scratch = New-Scratch
        try {
            $mainRoot = Join-Path $scratch 'relative-main'
            $gitdirTarget = Join-Path $mainRoot '.git\worktrees\lane'
            New-Item -ItemType Directory -Path $gitdirTarget -Force | Out-Null
            New-MarkerRoot4Boot -Root $mainRoot

            $worktreeRoot = Join-Path $scratch 'relative-wt'
            New-MarkerRoot4Boot -Root $worktreeRoot
            # Relative to the directory CONTAINING the .git file (the worktree root
            # itself) -- the real on-disk shape `git worktree add` produces when the
            # main checkout and the worktree share a common parent.
            Set-Content -Path (Join-Path $worktreeRoot '.git') -Value "gitdir: ..\relative-main\.git\worktrees\lane" -Encoding utf8

            $resolved = & {
                . $scriptPath -RepoRoot $worktreeRoot
                return $RepoRoot
            }
            $resolved | Should Be $mainRoot
        } finally {
            Remove-Item -Path $scratch -Recurse -Force -ErrorAction SilentlyContinue
        }
    }

    It 'a DANGLING gitdir pointer (target directory absent) throws at full script boot, never silently proceeds' {
        $scratch = New-Scratch
        try {
            $mainRoot = Join-Path $scratch 'dangling-boot-main'
            New-Item -ItemType Directory -Path $mainRoot -Force | Out-Null
            New-MarkerRoot4Boot -Root $mainRoot
            $danglingTarget = Join-Path $mainRoot '.git\worktrees\lane'
            Test-Path $danglingTarget | Should Be $false

            $worktreeRoot = Join-Path $scratch 'dangling-boot-wt'
            New-MarkerRoot4Boot -Root $worktreeRoot
            Set-Content -Path (Join-Path $worktreeRoot '.git') -Value "gitdir: $danglingTarget`n" -Encoding utf8

            { . $scriptPath -RepoRoot $worktreeRoot } | Should Throw
        } finally {
            Remove-Item -Path $scratch -Recurse -Force -ErrorAction SilentlyContinue
        }
    }

    # PR954 round 5 (reviewer reject P1-B): this used to have its own "genuinely
    # UNREADABLE .git pointer file" It here, but it wrote an INVALID pointer
    # (`gitdir: somewhere`) under the deny -- if the ACL deny didn't actually bite in
    # this process (elevated/inherited token bypass, observed on this box for
    # Get-Item/Test-Path), the invalid pointer alone would still throw, and the test
    # never discriminated "denied" from "malformed". Replaced by the two Describe
    # blocks below: a real-ACL leg over a VALID worktree-shape pointer that explicitly
    # proves denial effectiveness before asserting (Skipped loudly if the deny doesn't
    # bite), plus a deterministic Mock-based leg that is environment-independent.
}

# ---------------------------------------------------------------------------------------
# PR954 round 5 -- P1-B repair: the round-4 "genuinely unreadable .git" fixtures wrote an
# INVALID pointer (`gitdir: somewhere`) under the ACL deny. If the deny didn't actually
# bite in this process (an elevated/inherited token can silently bypass a deny ACE -- we
# verified this on this box: Get-Item/Test-Path stayed readable under a full deny even
# though Get-Content did not), the invalid pointer alone would produce the expected
# throw for the WRONG reason, and the test never discriminated unreadability at all.
#
# Repair, both legs:
#   (1) the ACL fixture now uses a VALID, resolvable worktree-shape pointer (a
#       marker-valid main root with a real worktrees/<name> directory) -- this WOULD
#       succeed if the deny didn't take effect, so a throw can only be attributed to
#       the read denial.
#   (2) denial effectiveness is explicitly PROVEN in-process (both at Describe-body
#       execution time as a general probe, and again against the exact fixture file
#       right before asserting) -- if it's not effective, the real-ACL It is Skipped
#       with a loud Write-Warning reason, never a silently-vacuous pass.
#   (3) a separate, fully deterministic Mock-Get-Content leg (simulating an
#       EACCES-shaped UnauthorizedAccessException) always runs regardless of ACL
#       bypass, so at least one denial test is environment-independent.
# ---------------------------------------------------------------------------------------

Describe 'PR954 round 5 -- real-ACL unreadable .git (valid pointer, denial-effectiveness proven, Skip-if-bypassed)' {
    # Probe ONCE, at Describe-body execution time (Pester discovery, before any It
    # runs) whether icacls /deny actually blocks Get-Content in THIS process.
    $script:r5AclProbeDir = Join-Path ([System.IO.Path]::GetTempPath()) ('ember-acl-probe-' + [guid]::NewGuid())
    New-Item -ItemType Directory -Path $script:r5AclProbeDir -Force | Out-Null
    $script:r5AclProbeFile = Join-Path $script:r5AclProbeDir 'probe.txt'
    Set-Content -Path $script:r5AclProbeFile -Value 'probe' -Encoding utf8
    $r5User = "$env:USERDOMAIN\$env:USERNAME"
    icacls $script:r5AclProbeFile /deny "${r5User}:(R)" | Out-Null
    $script:r5AclDenialEffective = $true
    try {
        Get-Content -Path $script:r5AclProbeFile -Raw -ErrorAction Stop | Out-Null
        $script:r5AclDenialEffective = $false
    } catch { }
    icacls $script:r5AclProbeFile /reset | Out-Null
    Remove-Item -Path $script:r5AclProbeDir -Recurse -Force -ErrorAction SilentlyContinue
    if (-not $script:r5AclDenialEffective) {
        Write-Warning "[PR954 round 5] icacls /deny does NOT block Get-Content in this process (elevated/inherited token bypass) -- the real-ACL It below will be SKIPPED; the deterministic Mock-Get-Content leg (separate Describe) covers this regardless."
    }

    It 'a genuinely UNREADABLE .git pointer file (real ACL deny of a VALID worktree-shape pointer) throws at full script boot' -Skip:(-not $script:r5AclDenialEffective) {
        $scratch = New-Scratch
        try {
            $mainRoot = Join-Path $scratch 'unreadable-real-main'
            $gitdirTarget = Join-Path $mainRoot '.git\worktrees\lane'
            New-Item -ItemType Directory -Path $gitdirTarget -Force | Out-Null
            New-Item -ItemType Directory -Path (Join-Path $mainRoot 'tools\ember-cli') -Force | Out-Null
            Set-Content -Path (Join-Path $mainRoot 'GOAL.md') -Value "# fixture`n" -Encoding utf8

            $root = Join-Path $scratch 'unreadable-real'
            New-Item -ItemType Directory -Path (Join-Path $root 'tools\ember-cli') -Force | Out-Null
            Set-Content -Path (Join-Path $root 'GOAL.md') -Value "# fixture`n" -Encoding utf8
            $dotGit = Join-Path $root '.git'
            # VALID worktree-shape pointer -- this WOULD resolve successfully (to
            # $mainRoot) if the deny below did not take effect, so a throw here can only
            # be attributed to the read denial, never an invalid-pointer red herring.
            [System.IO.File]::WriteAllText($dotGit, "gitdir: $gitdirTarget`n")

            $user = "$env:USERDOMAIN\$env:USERNAME"
            icacls $dotGit /deny "${user}:(R)" | Out-Null
            try {
                # Re-prove denial effectiveness against THIS exact fixture file right
                # before asserting -- the Describe-level probe covers the general case;
                # this covers any per-file surprise (e.g. a differing parent-folder ACL
                # inheritance). A failure here means the -Skip guard above was wrong for
                # this specific file, and the test fails loudly rather than passing
                # vacuously.
                $thisFileDenied = $true
                try { Get-Content -Path $dotGit -Raw -ErrorAction Stop | Out-Null; $thisFileDenied = $false } catch { }
                $thisFileDenied | Should Be $true

                { . $scriptPath -RepoRoot $root } | Should Throw
            } finally {
                # Reset the deny ACE BEFORE the outer scratch cleanup, or the recursive
                # delete below can itself fail/leave the ACL-denied file behind.
                icacls $dotGit /reset | Out-Null
            }
        } finally {
            Remove-Item -Path $scratch -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

Describe 'PR954 round 5 -- deterministic Mock-Get-Content unreadable .git leg (environment-independent, always runs)' {
    It 'Get-Content mocked to throw an EACCES-shaped UnauthorizedAccessException for a VALID worktree-shape pointer throws at full script boot, regardless of real-ACL bypass' {
        $scratch = New-Scratch
        try {
            $mainRoot = Join-Path $scratch 'unreadable-mock-main'
            $gitdirTarget = Join-Path $mainRoot '.git\worktrees\lane'
            New-Item -ItemType Directory -Path $gitdirTarget -Force | Out-Null
            New-Item -ItemType Directory -Path (Join-Path $mainRoot 'tools\ember-cli') -Force | Out-Null
            Set-Content -Path (Join-Path $mainRoot 'GOAL.md') -Value "# fixture`n" -Encoding utf8

            $root = Join-Path $scratch 'unreadable-mock'
            New-Item -ItemType Directory -Path (Join-Path $root 'tools\ember-cli') -Force | Out-Null
            Set-Content -Path (Join-Path $root 'GOAL.md') -Value "# fixture`n" -Encoding utf8
            $dotGit = Join-Path $root '.git'
            # Same VALID worktree-shape-pointer discipline as the real-ACL leg above --
            # this fixture would ALSO resolve successfully absent the mock.
            [System.IO.File]::WriteAllText($dotGit, "gitdir: $gitdirTarget`n")

            $script:r5MockDotGit = $dotGit
            Mock Get-Content { throw [System.UnauthorizedAccessException]::new("Access to the path '$($script:r5MockDotGit)' is denied. (EACCES, simulated)") } -ParameterFilter { $Path -eq $script:r5MockDotGit }

            { . $scriptPath -RepoRoot $root } | Should Throw
        } finally {
            Remove-Item -Path $scratch -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}
