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

    It 'server restart row carries health age and backoff state' {
        Mock Test-ServerHealth { $script:healthCalls++; return $false }
        Mock Find-ServerProcess { return $null }
        $state.server.consecutiveFailures = 1
        $state.server.lastHealthAt = '2026-07-08T12:00:00Z'
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
