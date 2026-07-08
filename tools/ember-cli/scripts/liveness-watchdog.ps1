#requires -Version 5.1
<#
.SYNOPSIS
    Standing liveness watchdogs for the two ember operator-surface daemons (issue #464):
    the cockpit TUI process and the shared llama-server model server.

.DESCRIPTION
    Today's receipt (issue #464): the cockpit died 4x and the model server was
    stopped/relaunched 4x for planned probe outages -- every recovery was a
    coordinator-dispatched lane hand-carrying kill-receipts. That only works while a
    session is actively watching. This script is the standing replacement: one process,
    two independent ticks.

      - Cockpit tick: reads state/cockpit-heartbeat.json (see
        src/services/liveness-heartbeat.ts, issue #413/#447). Heartbeat age above
        threshold (default 90s) -> relaunch via the instrumented launcher batch file
        (stderr capture retained).
      - Server tick: polls http://127.0.0.1:8082/health. Two consecutive failures ->
        PID-verified kill of the hung/dead process (if still alive) + relaunch with the
        exact receipted cmdline (PID lineage 3264->39540->40652->7120, 2026-07-08).

    Both ticks stand down while a valid tools/ember-cli/state/planned-outage.json marker
    covers their target -- the FROZEN CONTRACT from issue #464 comment 4918207339:
    {owner, reason, target, started, expires, kill_receipt_ref}, all required; a marker
    missing kill_receipt_ref is treated as absent; an expired marker does not extend
    silently -- the watchdog resumes duty and logs the overrun (owner named).

    Every restart/standdown/backoff/overrun decision is appended to
    state/liveness-watchdog-restart-log.jsonl (dead pid, heartbeat/health age, relaunch
    pid, backoff state -- receipts, not silence). Every kill this script performs writes
    its own row to the shared vigil kill-receipts ledger, via a JSON serializer, BEFORE
    the kill -- the sanctioned append-only exception for "the cohort actually performing
    the kill" (kill-discipline.md) -- and is PID-verified by cmdline match, never a
    name-pattern kill.

    Crashloop backoff: 3 deaths within a 10-minute window (per target) trips a 10-minute
    cooldown during which the watchdog logs a 'backoff' action and does not relaunch --
    a crashloop must surface as a loud, visible failure, not a silent restart storm.

.NOTES
    Functions in this file are the testable unit -- see liveness-watchdog.Tests.ps1, which
    dot-sources this script (never invoking the live loop; see the execution guard at the
    bottom) and Mocks every OS-facing cmdlet (Get-CimInstance, Invoke-WebRequest,
    Start-Process, Stop-Process) so the decision logic runs with zero real processes
    touched.

    Per the build mission for issue #464: this lane BUILDS the script and its fixture
    only. Arming the live loop against the operator's real cockpit/server is a separate,
    explicitly gated step -- this file is never invoked directly (only dot-sourced for
    tests) until that arming step runs it.
#>

param(
    [string]$RepoRoot = $(Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path,
    [int]$CockpitStaleThresholdSec = 90,
    [int]$CockpitPollIntervalSec = 15,
    [string]$ServerHealthUrl = 'http://127.0.0.1:8082/health',
    [int]$ServerPollIntervalSec = 30,
    [int]$ServerFailureThreshold = 2,
    # No literal default on purpose: this repo is PUBLIC (tools/repo-guard.sh fails any
    # commit embedding an operator-machine absolute path). The exact receipted cmdline
    # lives only in the shared vigil kill-receipts ledger (not this repo) -- an operator
    # arming this watchdog supplies it via -ServerCmdline / -ServerExePath / a local
    # (gitignored) EMBER_SERVER_CMDLINE / EMBER_SERVER_EXE_PATH environment variable.
    # Start-LivenessWatchdogLoop refuses to start the live loop if these are still empty
    # (see the arm-time validation below) -- this can never silently no-op on an unarmed
    # server watchdog.
    [string]$ServerCmdline = $env:EMBER_SERVER_CMDLINE,
    [string]$ServerExePath = $env:EMBER_SERVER_EXE_PATH,
    [string]$LauncherBatPath = $null,
    [int]$DeathWindowMinutes = 10,
    [int]$DeathThreshold = 3,
    [int]$BackoffMinutes = 10,
    # Same no-literal-default rule: kill-receipts.jsonl lives outside this repo entirely
    # (the shared avir/infra vigil ledger). Supply via -KillReceiptsPath or the
    # EMBER_KILL_RECEIPTS_PATH environment variable at arm-time.
    [string]$KillReceiptsPath = $env:EMBER_KILL_RECEIPTS_PATH,
    [int]$TickIntervalSec = 5
)

$StateDir          = Join-Path $RepoRoot 'tools\ember-cli\state'
$HeartbeatPath     = Join-Path $StateDir 'cockpit-heartbeat.json'
$MarkerPath        = Join-Path $StateDir 'planned-outage.json'
$WatchdogStatePath = Join-Path $StateDir 'liveness-watchdog-state.json'
$RestartLogPath    = Join-Path $StateDir 'liveness-watchdog-restart-log.jsonl'
$PidFilePath       = Join-Path $StateDir 'liveness-watchdog.pid'
if (-not $LauncherBatPath) {
    $LauncherBatPath = Join-Path $RepoRoot 'tools\ember-cli\src\launch-cockpit-instrumented.bat'
}

# ---------------------------------------------------------------------------------------
# Restart-log + watchdog-state persistence
# ---------------------------------------------------------------------------------------

function Write-RestartLogRow {
    <#
    .SYNOPSIS
    Appends one JSON row (dead pid, age, relaunch pid, backoff state -- whatever the
    caller passes) to the restart-log ledger. Never a hand-built string -- ConvertTo-Json
    only, matching the kill-discipline.md encoding lesson.
    #>
    param([Parameter(Mandatory)][string]$Path, [Parameter(Mandatory)][hashtable]$Row)
    $dir = Split-Path -Parent $Path
    if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    ($Row | ConvertTo-Json -Compress) | Add-Content -Path $Path -Encoding utf8
}

function Get-DefaultWatchdogState {
    [PSCustomObject]@{
        cockpit = [PSCustomObject]@{ deaths = @(); backoffUntil = $null; consecutiveFailures = 0 }
        server  = [PSCustomObject]@{ deaths = @(); backoffUntil = $null; consecutiveFailures = 0 }
    }
}

function Read-WatchdogState {
    <#
    .SYNOPSIS
    Loads persisted per-target state (death timestamps, backoff cooldown, consecutive
    health-check failures). Missing/corrupt file -> fresh default state, never a throw.
    #>
    param([Parameter(Mandatory)][string]$Path)
    if (-not (Test-Path $Path)) { return Get-DefaultWatchdogState }
    try {
        $raw = Get-Content -Path $Path -Raw -ErrorAction Stop
        if ([string]::IsNullOrWhiteSpace($raw)) { return Get-DefaultWatchdogState }
        $parsed = $raw | ConvertFrom-Json -ErrorAction Stop
        foreach ($t in 'cockpit', 'server') {
            if (-not ($parsed.PSObject.Properties.Name -contains $t)) {
                $parsed | Add-Member -NotePropertyName $t -NotePropertyValue ([PSCustomObject]@{ deaths = @(); backoffUntil = $null; consecutiveFailures = 0 })
            }
        }
        return $parsed
    } catch {
        Write-Warning "[liveness-watchdog] state file unreadable, resetting: $($_.Exception.Message)"
        return Get-DefaultWatchdogState
    }
}

function Save-WatchdogState {
    param([Parameter(Mandatory)][string]$Path, [Parameter(Mandatory)]$State)
    $dir = Split-Path -Parent $Path
    if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    ($State | ConvertTo-Json -Depth 8) | Set-Content -Path $Path -Encoding utf8
}

# ---------------------------------------------------------------------------------------
# Frozen planned-outage marker contract (issue #464 comment 4918207339)
# ---------------------------------------------------------------------------------------

function Get-PlannedOutageMarker {
    <#
    .SYNOPSIS
    Reads + validates the frozen planned-outage.json contract: owner/reason/target/
    started/expires/kill_receipt_ref all required. Missing/blank field, unparseable
    JSON, unparseable expires, or an invalid target value -> treated as ABSENT ($null),
    never partially honored (a marker without kill_receipt_ref is explicitly invalid
    per the frozen contract -- receipt-first kill discipline is not waivable by a marker).
    #>
    param([Parameter(Mandatory)][string]$Path)
    if (-not (Test-Path $Path)) { return $null }
    try {
        $raw = Get-Content -Path $Path -Raw -ErrorAction Stop
        $m = $raw | ConvertFrom-Json -ErrorAction Stop
    } catch {
        return $null
    }
    foreach ($f in 'owner', 'reason', 'target', 'started', 'expires', 'kill_receipt_ref') {
        $prop = $m.PSObject.Properties[$f]
        if (-not $prop -or [string]::IsNullOrWhiteSpace([string]$prop.Value)) { return $null }
    }
    if ($m.target -notin @('server', 'cockpit', 'both')) { return $null }
    try {
        [void][datetime]::Parse($m.expires, [System.Globalization.CultureInfo]::InvariantCulture, [System.Globalization.DateTimeStyles]::AdjustToUniversal)
    } catch {
        return $null
    }
    return $m
}

function Test-MarkerCoversTarget {
    <#
    .SYNOPSIS
    Given a validated marker (or $null) and a target ("cockpit"|"server"), decides
    whether that watchdog should stand down right now. An expired marker is NOT a
    stand-down -- the caller resumes duty and logs the overrun (owner named), per the
    frozen contract's "does not extend silently" clause.
    #>
    param($Marker, [Parameter(Mandatory)][string]$Target, [Parameter(Mandatory)][datetime]$Now)
    $result = [PSCustomObject]@{ StandDown = $false; Expired = $false; Marker = $Marker }
    if ($null -eq $Marker) { return $result }
    if ($Marker.target -ne $Target -and $Marker.target -ne 'both') { return $result }
    $expires = [datetime]::Parse($Marker.expires, [System.Globalization.CultureInfo]::InvariantCulture, [System.Globalization.DateTimeStyles]::AdjustToUniversal)
    if ($Now -lt $expires) {
        $result.StandDown = $true
    } else {
        $result.Expired = $true
    }
    return $result
}

# ---------------------------------------------------------------------------------------
# Cockpit heartbeat (state/cockpit-heartbeat.json -- {ts, pid, version}, issue #413)
# ---------------------------------------------------------------------------------------

function Get-HeartbeatAgeSeconds {
    param([Parameter(Mandatory)][string]$Path, [Parameter(Mandatory)][datetime]$Now)
    if (-not (Test-Path $Path)) { return $null }
    try {
        $row = (Get-Content -Path $Path -Raw -ErrorAction Stop) | ConvertFrom-Json -ErrorAction Stop
        if (-not $row.ts) { return $null }
        $ts = [datetime]::Parse($row.ts, [System.Globalization.CultureInfo]::InvariantCulture, [System.Globalization.DateTimeStyles]::AdjustToUniversal)
        return [math]::Round(($Now - $ts).TotalSeconds, 3)
    } catch {
        return $null
    }
}

function Get-HeartbeatPid {
    param([Parameter(Mandatory)][string]$Path)
    if (-not (Test-Path $Path)) { return $null }
    try {
        $row = (Get-Content -Path $Path -Raw -ErrorAction Stop) | ConvertFrom-Json -ErrorAction Stop
        return $row.pid
    } catch {
        return $null
    }
}

# ---------------------------------------------------------------------------------------
# Crashloop backoff (per-target: deaths within a trailing window trip a cooldown)
# ---------------------------------------------------------------------------------------

function Get-BackoffState {
    param($TargetState, [Parameter(Mandatory)][datetime]$Now)
    if ($TargetState.backoffUntil) {
        $until = [datetime]::Parse([string]$TargetState.backoffUntil, [System.Globalization.CultureInfo]::InvariantCulture, [System.Globalization.DateTimeStyles]::AdjustToUniversal)
        if ($Now -lt $until) { return [PSCustomObject]@{ InBackoff = $true; Until = $until } }
    }
    return [PSCustomObject]@{ InBackoff = $false; Until = $null }
}

function Add-DeathRecord {
    <#
    .SYNOPSIS
    Appends $Now to a target's death-timestamp list (pruned to the trailing
    $WindowMinutes), and trips backoffUntil = Now + $BackoffMinutes the instant the
    count reaches $Threshold within the window -- a crashloop must surface as a visible
    failure, not a silent restart storm. Returns the updated sub-state plus whether this
    death just tripped the cooldown, so the caller can log a distinct 'crashloop-backoff'
    row.
    #>
    param($TargetState, [Parameter(Mandatory)][datetime]$Now, [int]$WindowMinutes = 10, [int]$Threshold = 3, [int]$BackoffMinutes = 10)
    $windowStart = $Now.AddMinutes(-$WindowMinutes)
    $existing = @($TargetState.deaths | Where-Object {
        try { ([datetime]::Parse([string]$_, [System.Globalization.CultureInfo]::InvariantCulture, [System.Globalization.DateTimeStyles]::AdjustToUniversal)) -ge $windowStart } catch { $false }
    })
    $updated = @($existing) + $Now.ToString('o')
    $tripped = $false
    if ($updated.Count -ge $Threshold) {
        $TargetState.backoffUntil = $Now.AddMinutes($BackoffMinutes).ToString('o')
        $tripped = $true
    }
    $TargetState.deaths = $updated
    return [PSCustomObject]@{ State = $TargetState; Tripped = $tripped; DeathsInWindow = $updated.Count }
}

# ---------------------------------------------------------------------------------------
# Cockpit tick
# ---------------------------------------------------------------------------------------

function Start-CockpitLauncher {
    <#
    .SYNOPSIS
    Invokes the instrumented launcher batch file (stderr capture retained) detached.
    Missing launcher -> warn + report Started=$false rather than throw, so a single bad
    path never crashes the watchdog loop.
    #>
    param([Parameter(Mandatory)][string]$LauncherBatPath)
    if (-not (Test-Path $LauncherBatPath)) {
        Write-Warning "[liveness-watchdog] cockpit launcher not found: $LauncherBatPath"
        return [PSCustomObject]@{ Pid = $null; Started = $false }
    }
    $proc = Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', "`"$LauncherBatPath`"" -PassThru -WindowStyle Hidden
    return [PSCustomObject]@{ Pid = $proc.Id; Started = $true }
}

function Invoke-CockpitWatchdogTick {
    <#
    .SYNOPSIS
    One decision cycle for the cockpit watchdog. Order: planned-outage stand-down/overrun
    check, then crashloop-backoff check, then heartbeat-age check, then (if stale)
    relaunch + death-record + restart-log row.
    #>
    param(
        [Parameter(Mandatory)][datetime]$Now,
        [Parameter(Mandatory)]$State,
        [string]$HeartbeatPath = $HeartbeatPath,
        [string]$MarkerPath = $MarkerPath,
        [int]$StaleThresholdSec = $CockpitStaleThresholdSec,
        [string]$LauncherBatPath = $LauncherBatPath,
        [string]$RestartLogPath = $RestartLogPath,
        [int]$DeathWindowMinutes = $DeathWindowMinutes,
        [int]$DeathThreshold = $DeathThreshold,
        [int]$BackoffMinutes = $BackoffMinutes
    )
    $marker = Get-PlannedOutageMarker -Path $MarkerPath
    $coverage = Test-MarkerCoversTarget -Marker $marker -Target 'cockpit' -Now $Now
    if ($coverage.StandDown) {
        return [PSCustomObject]@{ Action = 'standdown'; Detail = "owner=$($marker.owner) expires=$($marker.expires)" }
    }
    if ($coverage.Expired) {
        Write-RestartLogRow -Path $RestartLogPath -Row @{
            ts = $Now.ToString('o'); target = 'cockpit'; event = 'marker-overrun'
            owner = $marker.owner; expiredAt = $marker.expires
        }
    }

    $backoff = Get-BackoffState -TargetState $State.cockpit -Now $Now
    if ($backoff.InBackoff) {
        return [PSCustomObject]@{ Action = 'backoff'; Detail = "until=$($backoff.Until.ToString('o'))" }
    }

    $age = Get-HeartbeatAgeSeconds -Path $HeartbeatPath -Now $Now
    if ($null -ne $age -and $age -le $StaleThresholdSec) {
        return [PSCustomObject]@{ Action = 'none'; Detail = "ageSec=$age" }
    }

    # Stale (or unreadable/missing heartbeat -- can't confirm liveness either way) -> relaunch.
    $deadPid = Get-HeartbeatPid -Path $HeartbeatPath
    $launch = Start-CockpitLauncher -LauncherBatPath $LauncherBatPath

    $deathRecord = Add-DeathRecord -TargetState $State.cockpit -Now $Now -WindowMinutes $DeathWindowMinutes -Threshold $DeathThreshold -BackoffMinutes $BackoffMinutes
    $State.cockpit = $deathRecord.State

    Write-RestartLogRow -Path $RestartLogPath -Row @{
        ts = $Now.ToString('o'); target = 'cockpit'; event = 'relaunch'
        deadPid = $deadPid; ageSec = $age; relaunchPid = $launch.Pid
        deathsInWindow = $deathRecord.DeathsInWindow
    }
    if ($deathRecord.Tripped) {
        Write-RestartLogRow -Path $RestartLogPath -Row @{
            ts = $Now.ToString('o'); target = 'cockpit'; event = 'crashloop-backoff'
            deathsInWindow = $deathRecord.DeathsInWindow; backoffUntil = $State.cockpit.backoffUntil
        }
    }

    return [PSCustomObject]@{ Action = 'relaunch'; Detail = "relaunchPid=$($launch.Pid)" }
}

# ---------------------------------------------------------------------------------------
# Server tick (http health poll + PID-verified kill + relaunch)
# ---------------------------------------------------------------------------------------

function Test-ServerHealth {
    param([Parameter(Mandatory)][string]$Url)
    try {
        $resp = Invoke-WebRequest -Uri $Url -Method Get -TimeoutSec 5 -UseBasicParsing -ErrorAction Stop
        return ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 300)
    } catch {
        return $false
    }
}

function Find-ServerProcess {
    <#
    .SYNOPSIS
    PID-verified lookup: the llama-server.exe process whose full command line contains
    $ServerExePath, or $null if none is running. Never a name-pattern-only match --
    per kill-discipline.md, matches by verified cmdline.
    #>
    param([Parameter(Mandatory)][string]$ServerExePath)
    $procs = Get-CimInstance Win32_Process -Filter "Name='llama-server.exe'" -ErrorAction SilentlyContinue
    foreach ($p in $procs) {
        if ($p.CommandLine -and $p.CommandLine.Contains($ServerExePath)) { return $p }
    }
    return $null
}

function Write-KillReceiptRow {
    <#
    .SYNOPSIS
    Appends one row to the shared vigil kill-receipts ledger via ConvertTo-Json (never a
    hand-built string -- the 2026-07-07 encoding-repair lesson). Append-only: this is the
    sanctioned "cohort actually performing the kill" exception (kill-discipline.md).
    #>
    param([Parameter(Mandatory)][string]$Path, [Parameter(Mandatory)][hashtable]$Row)
    $dir = Split-Path -Parent $Path
    if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    ($Row | ConvertTo-Json -Compress) | Add-Content -Path $Path -Encoding utf8
}

function Start-ServerProcess {
    <#
    .SYNOPSIS
    Relaunches the model server with the exact receipted cmdline. Splits the leading
    quoted exe path from the argument tail so Start-Process gets a clean -FilePath /
    -ArgumentList pair without re-parsing the quoting ourselves.
    #>
    param([Parameter(Mandatory)][string]$ServerCmdline)
    if ($ServerCmdline -match '^"([^"]+)"\s*(.*)$') {
        $exe = $Matches[1]; $argLine = $Matches[2]
    } else {
        $parts = $ServerCmdline.Split(' ', 2); $exe = $parts[0]; $argLine = $parts[1]
    }
    $proc = Start-Process -FilePath $exe -ArgumentList $argLine -PassThru -WindowStyle Hidden
    return [PSCustomObject]@{ Pid = $proc.Id; Started = $true }
}

function Invoke-ServerWatchdogTick {
    <#
    .SYNOPSIS
    One decision cycle for the server watchdog. Order: planned-outage stand-down/overrun
    check, then crashloop-backoff check, then a single /health poll. A failure only acts
    once $FailureThreshold consecutive failures have accumulated in State.server --
    at that point: PID-verified kill (receipt written BEFORE the kill) if the process is
    still alive, then relaunch with the exact receipted cmdline, then death-record +
    restart-log row.
    #>
    param(
        [Parameter(Mandatory)][datetime]$Now,
        [Parameter(Mandatory)]$State,
        [string]$HealthUrl = $ServerHealthUrl,
        [string]$MarkerPath = $MarkerPath,
        [int]$FailureThreshold = $ServerFailureThreshold,
        [string]$ServerCmdline = $ServerCmdline,
        [string]$ServerExePath = $ServerExePath,
        [string]$RestartLogPath = $RestartLogPath,
        [string]$KillReceiptsPath = $KillReceiptsPath,
        [int]$DeathWindowMinutes = $DeathWindowMinutes,
        [int]$DeathThreshold = $DeathThreshold,
        [int]$BackoffMinutes = $BackoffMinutes
    )
    $marker = Get-PlannedOutageMarker -Path $MarkerPath
    $coverage = Test-MarkerCoversTarget -Marker $marker -Target 'server' -Now $Now
    if ($coverage.StandDown) {
        return [PSCustomObject]@{ Action = 'standdown'; Detail = "owner=$($marker.owner) expires=$($marker.expires)" }
    }
    if ($coverage.Expired) {
        Write-RestartLogRow -Path $RestartLogPath -Row @{
            ts = $Now.ToString('o'); target = 'server'; event = 'marker-overrun'
            owner = $marker.owner; expiredAt = $marker.expires
        }
    }

    $backoff = Get-BackoffState -TargetState $State.server -Now $Now
    if ($backoff.InBackoff) {
        return [PSCustomObject]@{ Action = 'backoff'; Detail = "until=$($backoff.Until.ToString('o'))" }
    }

    $healthy = Test-ServerHealth -Url $HealthUrl
    if ($healthy) {
        $State.server.consecutiveFailures = 0
        return [PSCustomObject]@{ Action = 'none'; Detail = 'healthy' }
    }

    $State.server.consecutiveFailures = [int]$State.server.consecutiveFailures + 1
    if ($State.server.consecutiveFailures -lt $FailureThreshold) {
        return [PSCustomObject]@{ Action = 'none'; Detail = "consecutiveFailures=$($State.server.consecutiveFailures)" }
    }

    $proc = Find-ServerProcess -ServerExePath $ServerExePath
    if ($proc) {
        Write-KillReceiptRow -Path $KillReceiptsPath -Row @{
            ts = $Now.ToString('o'); script = 'liveness-watchdog'
            pids = @([int]$proc.ProcessId)
            match_rule = "cmdline-verified via Get-CimInstance Win32_Process: Name=llama-server.exe, CommandLine contains $ServerExePath"
            reason = "consecutive /health failures ($($State.server.consecutiveFailures)) at $HealthUrl"
            survivors_expected = 'none'
            recovery = "relaunch with receipted cmdline: $ServerCmdline"
        }
        Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
    }

    $launch = Start-ServerProcess -ServerCmdline $ServerCmdline
    $State.server.consecutiveFailures = 0

    $deathRecord = Add-DeathRecord -TargetState $State.server -Now $Now -WindowMinutes $DeathWindowMinutes -Threshold $DeathThreshold -BackoffMinutes $BackoffMinutes
    $State.server = $deathRecord.State

    Write-RestartLogRow -Path $RestartLogPath -Row @{
        ts = $Now.ToString('o'); target = 'server'; event = 'relaunch'
        deadPid = $(if ($proc) { [int]$proc.ProcessId } else { $null }); relaunchPid = $launch.Pid
        deathsInWindow = $deathRecord.DeathsInWindow
    }
    if ($deathRecord.Tripped) {
        Write-RestartLogRow -Path $RestartLogPath -Row @{
            ts = $Now.ToString('o'); target = 'server'; event = 'crashloop-backoff'
            deathsInWindow = $deathRecord.DeathsInWindow; backoffUntil = $State.server.backoffUntil
        }
    }

    return [PSCustomObject]@{ Action = 'relaunch'; Detail = "relaunchPid=$($launch.Pid)" }
}

# ---------------------------------------------------------------------------------------
# Idempotent start + main loop
# ---------------------------------------------------------------------------------------

function Test-WatchdogAlreadyRunning {
    <#
    .SYNOPSIS
    Idempotent-start guard: reads the pidfile (if any) and confirms via cmdline that the
    recorded PID is genuinely this same watchdog script, not a reused PID belonging to an
    unrelated process. Enumerate-before-spawn, never stack.
    #>
    param([Parameter(Mandatory)][string]$PidFilePath)
    if (-not (Test-Path $PidFilePath)) { return $false }
    try {
        $existingPid = [int](Get-Content -Path $PidFilePath -Raw -ErrorAction Stop).Trim()
    } catch {
        return $false
    }
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$existingPid" -ErrorAction SilentlyContinue
    return [bool]($proc -and $proc.CommandLine -and $proc.CommandLine -match 'liveness-watchdog')
}

function Start-LivenessWatchdogLoop {
    <#
    .SYNOPSIS
    The live infinite loop: cockpit tick every $CockpitPollIntervalSec, server tick every
    $ServerPollIntervalSec, state persisted after every pass. Refuses to start a second
    instance (pidfile + cmdline-verified check); writes its own pidfile on start, removes
    it on exit.

    Arm-time validation: $ServerCmdline / $ServerExePath / $KillReceiptsPath have no
    literal default (repo-guard.sh bans operator-machine absolute paths in this public
    repo) -- they must come from -Parameter overrides or the EMBER_SERVER_CMDLINE /
    EMBER_SERVER_EXE_PATH / EMBER_KILL_RECEIPTS_PATH environment variables. An unarmed
    server watchdog must fail loudly here, never silently no-op on every future health
    failure.
    #>
    param([int]$TickIntervalSec = $TickIntervalSec)
    $missing = @('ServerCmdline', 'ServerExePath', 'KillReceiptsPath') | Where-Object { [string]::IsNullOrWhiteSpace((Get-Variable -Name $_ -ValueOnly)) }
    if ($missing.Count -gt 0) {
        throw "[liveness-watchdog] refusing to start: not armed for the server watchdog -- missing $($missing -join ', '). Supply via -ServerCmdline/-ServerExePath/-KillReceiptsPath or the EMBER_SERVER_CMDLINE/EMBER_SERVER_EXE_PATH/EMBER_KILL_RECEIPTS_PATH environment variables (see the day's kill-receipts.jsonl row for the exact receipted cmdline)."
    }
    if (Test-WatchdogAlreadyRunning -PidFilePath $PidFilePath) {
        Write-Warning "[liveness-watchdog] already running (pidfile $PidFilePath) -- refusing to start a second instance."
        return
    }
    $dir = Split-Path -Parent $PidFilePath
    if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    Set-Content -Path $PidFilePath -Value $PID -Encoding utf8

    $state = Read-WatchdogState -Path $WatchdogStatePath
    $nextCockpitCheck = [datetime]::UtcNow
    $nextServerCheck  = [datetime]::UtcNow

    try {
        while ($true) {
            $now = [datetime]::UtcNow
            if ($now -ge $nextCockpitCheck) {
                Invoke-CockpitWatchdogTick -Now $now -State $state | Out-Null
                $nextCockpitCheck = $now.AddSeconds($CockpitPollIntervalSec)
            }
            if ($now -ge $nextServerCheck) {
                Invoke-ServerWatchdogTick -Now $now -State $state | Out-Null
                $nextServerCheck = $now.AddSeconds($ServerPollIntervalSec)
            }
            Save-WatchdogState -Path $WatchdogStatePath -State $state
            Start-Sleep -Seconds $TickIntervalSec
        }
    } finally {
        Remove-Item -Path $PidFilePath -Force -ErrorAction SilentlyContinue
    }
}

# Execution guard: only start the live loop when this script is run directly, never when
# dot-sourced (tests / future callers reusing the functions). Build-mission rail: this
# lane builds the script + fixture only -- arming the live loop against the operator's
# real cockpit/server is a separate, explicitly gated step.
if ($MyInvocation.InvocationName -ne '.') {
    Start-LivenessWatchdogLoop
}
