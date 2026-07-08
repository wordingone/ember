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

        $result = Invoke-CockpitWatchdogTick -Now $now -State $state `
            -HeartbeatPath $heartbeatPath -MarkerPath $markerPath -StaleThresholdSec 90 `
            -LauncherBatPath $launcherPath -RestartLogPath $restartLogPath

        $result.Action | Should Be 'standdown'
        $launcherCalls | Should Be 0
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

        $result = Invoke-ServerWatchdogTick -Now ([datetime]::UtcNow) -State $state `
            -MarkerPath $markerPath -FailureThreshold 2 -ServerCmdline $cmdline -ServerExePath $exePath `
            -RestartLogPath $restartLogPath -KillReceiptsPath $killReceiptsPath

        $result.Action | Should Be 'standdown'
        $healthCalls | Should Be 0
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
