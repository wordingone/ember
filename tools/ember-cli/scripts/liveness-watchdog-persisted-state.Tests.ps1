# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
# Focused regressions for corrupt persisted watchdog state in issue #464 / PR #945.

$scriptPath = Join-Path $PSScriptRoot 'liveness-watchdog.ps1'
. $scriptPath

Describe 'Corrupt persisted watchdog state fails closed for both targets' {
    BeforeEach {
        $script:scratch = Join-Path ([System.IO.Path]::GetTempPath()) ('ember-watchdog-state-review-' + [guid]::NewGuid())
        New-Item -ItemType Directory -Path $scratch -Force | Out-Null
        $script:statePath = Join-Path $scratch 'watchdog-state.json'
        $script:now = [datetime]::Parse('2026-07-08T12:00:00Z').ToUniversalTime()
    }

    AfterEach {
        Remove-Item -Path $scratch -Recurse -Force -ErrorAction SilentlyContinue
    }

    function Assert-BothTargetsFailClosed {
        param([hashtable]$Cockpit, [hashtable]$Server)
        $payload = @{ cockpit = $Cockpit; server = $Server; freshness = @{} }
        ($payload | ConvertTo-Json -Depth 8) | Set-Content -Path $statePath -Encoding utf8
        $state = Read-WatchdogState -Path $statePath

        foreach ($target in 'cockpit', 'server') {
            { Get-BackoffState -TargetState $state.$target -Now $now | Out-Null } | Should Not Throw
            $state.$target.backoffLevel | Should Be 0
            $state.$target.backoffUntil | Should BeNullOrEmpty
            $state.$target.backoffState | Should Be 'clear'
        }
    }

    It 'resets non-integer level and invalid time corruption on both targets' {
        Assert-BothTargetsFailClosed `
            -Cockpit @{ deaths = @(); backoffLevel = 'not-an-integer'; backoffUntil = 'not-a-time'; backoffState = 'active' } `
            -Server  @{ deaths = @(); backoffLevel = 'not-an-integer'; backoffUntil = 'not-a-time'; backoffState = 'active' }
    }

    It 'resets negative persisted levels on both targets' {
        Assert-BothTargetsFailClosed `
            -Cockpit @{ deaths = @(); backoffLevel = -1; backoffUntil = '2026-07-08T13:00:00Z'; backoffState = 'active' } `
            -Server  @{ deaths = @(); backoffLevel = -1; backoffUntil = '2026-07-08T13:00:00Z'; backoffState = 'active' }
    }

    It 'resets out-of-range persisted levels on both targets' {
        Assert-BothTargetsFailClosed `
            -Cockpit @{ deaths = @(); backoffLevel = 2147483648; backoffUntil = '2026-07-08T13:00:00Z'; backoffState = 'active' } `
            -Server  @{ deaths = @(); backoffLevel = 2147483648; backoffUntil = '2026-07-08T13:00:00Z'; backoffState = 'active' }
    }

    It 'resets a valid level paired with invalid time on both targets' {
        Assert-BothTargetsFailClosed `
            -Cockpit @{ deaths = @(); backoffLevel = 2; backoffUntil = 'not-a-time'; backoffState = 'active' } `
            -Server  @{ deaths = @(); backoffLevel = 2; backoffUntil = 'not-a-time'; backoffState = 'active' }
    }
}
