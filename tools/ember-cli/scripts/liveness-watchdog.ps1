# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
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

      - Marker-expiry enforcement leg: on each cycle, if planned-outage.json exists AND
        now > expires, archive the stale marker (rename to planned-outage-expired-<ts>.json),
        run the restore-on-removal triggers, and append an activity event (issue #464 receipt
        fix: llama-server stayed dead 18min past marker expiry; the log-only path was
        incomplete).

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
    [int]$TickIntervalSec = 5,
    # Freshness leg (issue #545): poll public/master and auto-pull the main tree
    [int]$FreshnessPollIntervalSec = 120,
    [switch]$WhatIf = $false
)

# Issue #666 / PR954 round 2: if this script's checkout is itself a git WORKTREE (`.git`
# is a FILE with a `gitdir: <main>/.git/worktrees/<name>` pointer), state paths derived
# from it would diverge from the main-tree paths the cockpit writer resolves to.
# Canonicalize to the main checkout so writer and watchdog provably bind the SAME
# heartbeat file.
#
# Strict contract (round 2 repair of the reviewer's reject, same contract as
# repo-root.ts's canonicalizeThroughWorktree/CanonicalRootError): a marker-valid
# standalone root with NO `.git` at all is accepted as-is (git-less deployment / plain
# copy -- the only case Test-Path's Leaf check returns false without a validated `.git`
# FILE also covers "`.git` is a directory", i.e. an ordinary main checkout, which is
# likewise returned unchanged). Every OTHER shape that fails to fully resolve to a
# marker-valid main checkout -- an unreadable `.git` FILE, one whose content doesn't
# match `gitdir:` at all, one whose gitdir doesn't match the
# `<main>/.git/worktrees/<name>` shape (e.g. a submodule), or a worktree pointer whose
# resolved main checkout fails the marker check -- THROWS. The old fallback-to-$Root
# cases for the malformed/unreadable shapes are REMOVED: this function must never
# silently return an unverified root, because that root feeds directly into
# $HeartbeatPath below and a wrong root here means the watchdog polls a file nobody
# writes.
function Get-SingleGitdirRecord {
    <#
    .SYNOPSIS
    PR954 round 3: parses a .git FILE's raw content as EXACTLY ONE `gitdir: <path>` record,
    optionally followed by a single trailing newline (`\n` or `\r\n`). Returns the captured
    path, or $null if the content is not exactly one such record -- e.g. a junk line
    before/after the record, a second record, or any other embedded newline. Same contract
    as repo-root.ts's parseSingleGitdirRecord: round 2's `(?m)^gitdir:\s*(.+?)\s*$` used
    the multiline flag, so `^`/`$` matched at ANY line boundary and a shape like
    "junk`ngitdir: valid`n" silently validated against the junk-prefixed line -- exactly
    the malformed shape this resolver must reject, not paper over.
    #>
    param([Parameter(Mandatory)][AllowEmptyString()][string]$Raw)
    $content = $Raw
    if ($content.EndsWith("`r`n")) { $content = $content.Substring(0, $content.Length - 2) }
    elseif ($content.EndsWith("`n")) { $content = $content.Substring(0, $content.Length - 1) }
    if ($content.Contains("`n")) { return $null }
    $m = [regex]::Match($content, '^gitdir:\s*(.+?)\s*$')
    if (-not $m.Success) { return $null }
    return $m.Groups[1].Value
}

function Get-DotGitItemState {
    <#
    .SYNOPSIS
    PR954 round 4 repair: classifies $Path strictly under TERMINATING-error semantics via
    Get-Item, never Test-Path. `Test-Path -PathType Leaf` swallows access errors internally
    and returns $false on anything it can't classify (permission-denied, locked, or
    otherwise unclassifiable) -- Resolve-CanonicalRepoRoot then read that $false as
    "definitely absent" and fell open to the worktree-local heartbeat path, exactly the
    silent-wrong-root failure issue #666 exists to kill. This classifier returns EXACTLY
    'Absent' (a genuine ItemNotFoundException) or 'Directory'/'File' (Get-Item succeeded);
    any OTHER failure -- access denied, locked, or any unclassifiable stat error -- throws,
    same fail-closed contract as the unreadable-content path below.
    #>
    param([Parameter(Mandatory)][string]$Path)
    try {
        $item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    } catch [System.Management.Automation.ItemNotFoundException] {
        return 'Absent'
    } catch {
        throw "could not classify $Path (permission-denied, locked, or otherwise unclassifiable -- neither confirmed absent nor confirmed present): $($_.Exception.Message). Refusing to guess whether this is a worktree gitdir pointer file (issue #666 strict resolver, PR954 round 4)."
    }
    if ($item.PSIsContainer) { return 'Directory' }
    return 'File'
}

function Resolve-CanonicalRepoRoot {
    param([Parameter(Mandatory)][string]$Root)
    $dotGit = Join-Path $Root '.git'
    $dotGitState = Get-DotGitItemState -Path $dotGit
    if ($dotGitState -eq 'Absent') { return $Root } # no .git at all -- standalone/git-less deployment.
    if ($dotGitState -eq 'Directory') { return $Root } # main checkout.

    try {
        $raw = Get-Content -Path $dotGit -Raw -ErrorAction Stop
    } catch {
        throw "repo root $Root has a .git file at $dotGit that could not be read: $($_.Exception.Message) -- refusing to poll a worktree-scoped heartbeat path with an unverified root (issue #666)."
    }

    $gitdir = Get-SingleGitdirRecord -Raw $raw
    if ($null -eq $gitdir) {
        throw "repo root $Root has a .git file at $dotGit that does not contain exactly one gitdir: record (malformed, junk-prefixed, multi-line, or otherwise unsupported .git file shape) -- refusing to poll a worktree-scoped heartbeat path with an unverified root (issue #666)."
    }
    if (-not [System.IO.Path]::IsPathRooted($gitdir)) { $gitdir = Join-Path $Root $gitdir }
    $resolvedGitdir = [System.IO.Path]::GetFullPath($gitdir)
    $wt = [regex]::Match($resolvedGitdir, '^(.*)[\\/]\.git[\\/]worktrees[\\/][^\\/]+$')
    if (-not $wt.Success) {
        throw "repo root $Root's .git file points to $resolvedGitdir, which is not a <main>/.git/worktrees/<name> path (unsupported gitdir shape, e.g. a submodule) -- refusing to poll a worktree-scoped heartbeat path with an unverified root (issue #666)."
    }
    # PR954 round 3: a dangling gitdir pointer (target directory absent, or present but not
    # a directory) must reject -- unverifiable is the same failure class as unreadable or
    # malformed.
    if (-not (Test-Path $resolvedGitdir -PathType Container)) {
        throw "repo root $Root's .git file points to $resolvedGitdir, which does not exist as a directory (dangling worktree gitdir pointer) -- refusing to poll a worktree-scoped heartbeat path with an unverified root (issue #666)."
    }
    $mainRoot = $wt.Groups[1].Value
    if ((Test-Path (Join-Path $mainRoot 'GOAL.md')) -and (Test-Path (Join-Path $mainRoot 'tools\ember-cli'))) {
        return $mainRoot
    }
    throw "repo root $Root is a git worktree of $mainRoot, but that main checkout does not validate as the ember repo root (issue #666) -- refusing to poll a worktree-scoped heartbeat path."
}
$RepoRoot = Resolve-CanonicalRepoRoot -Root $RepoRoot

$StateDir          = Join-Path $RepoRoot 'tools\ember-cli\state'
$HeartbeatPath     = Join-Path $StateDir 'cockpit-heartbeat.json'
$MarkerPath        = Join-Path $StateDir 'planned-outage.json'
$WatchdogStatePath = Join-Path $StateDir 'liveness-watchdog-state.json'
$RestartLogPath    = Join-Path $StateDir 'liveness-watchdog-restart-log.jsonl'
$ActivityLedgerPath = Join-Path $StateDir 'activity-ledger.jsonl'
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

function Get-StandDownDecisionKey {
    param([Parameter(Mandatory)]$Marker)
    $canonical = [ordered]@{
        target = [string]$Marker.target
        owner = [string]$Marker.owner
        reason = [string]$Marker.reason
        started = [string]$Marker.started
        expires = [string]$Marker.expires
        kill_receipt_ref = [string]$Marker.kill_receipt_ref
    }
    $json = $canonical | ConvertTo-Json -Compress
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        return (([BitConverter]::ToString($sha.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($json)))) -replace '-', '').ToLowerInvariant()
    }
    finally {
        $sha.Dispose()
    }
}

function Write-StandDownDecision {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][hashtable]$Row,
        [Parameter(Mandatory)]$TargetState,
        [Parameter(Mandatory)][string]$DecisionKey
    )
    if ($TargetState.standdownDecisionKey -eq $DecisionKey) { return $false }
    Write-RestartLogRow -Path $Path -Row $Row
    $TargetState.standdownDecisionKey = $DecisionKey
    return $true
}
function Get-DefaultWatchdogState {
    [PSCustomObject]@{
        cockpit = [PSCustomObject]@{ deaths = @(); backoffUntil = $null; backoffLevel = 0; backoffState = 'clear'; consecutiveFailures = 0; standdownDecisionKey = $null }
        server  = [PSCustomObject]@{ deaths = @(); backoffUntil = $null; backoffLevel = 0; backoffState = 'clear'; consecutiveFailures = 0; lastHealthAt = $null; lastHealthyAt = $null; lastHealthCheckAt = $null; standdownDecisionKey = $null }
        freshness = [PSCustomObject]@{ lastHeadSha = $null; lastCheckTime = $null }
    }
}
function Normalize-WatchdogBackoffState {
    param($TargetState)
    if ($null -eq $TargetState) { return }
    $level = 0
    $levelValid = $true
    if ($TargetState.PSObject.Properties.Name -contains 'backoffLevel') {
        try {
            $parsedLevel = 0L
            if (-not [long]::TryParse([string]$TargetState.backoffLevel, [System.Globalization.NumberStyles]::Integer, [System.Globalization.CultureInfo]::InvariantCulture, [ref]$parsedLevel) -or $parsedLevel -lt 0 -or $parsedLevel -gt [int64][int]::MaxValue) {
                $levelValid = $false
            } else {
                $level = [int]$parsedLevel
            }
        } catch { $levelValid = $false }
    }
    $until = $null
    $hasUntil = $TargetState.PSObject.Properties.Name -contains 'backoffUntil' -and -not [string]::IsNullOrWhiteSpace([string]$TargetState.backoffUntil)
    $untilValid = $true
    if ($hasUntil) {
        try {
            $parsedUntil = [datetime]::MinValue
            if (-not [datetime]::TryParse([string]$TargetState.backoffUntil, [System.Globalization.CultureInfo]::InvariantCulture, [System.Globalization.DateTimeStyles]::AdjustToUniversal, [ref]$parsedUntil)) {
                $untilValid = $false
            } else {
                $until = $parsedUntil
            }
        } catch { $untilValid = $false }
    }
    if (-not $levelValid -or -not $untilValid) {
        $level = 0
        $until = $null
        $hasUntil = $false
    }
    $TargetState.backoffLevel = $level
    $TargetState.backoffUntil = if ($until) { $until.ToString('o') } else { $null }
    $TargetState.backoffState = if ($until) { if ($level -gt 1) { 'escalated' } else { 'active' } } else { 'clear' }
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
                $parsed | Add-Member -NotePropertyName $t -NotePropertyValue ([PSCustomObject]@{ deaths = @(); backoffUntil = $null; backoffLevel = 0; backoffState = 'clear'; consecutiveFailures = 0; standdownDecisionKey = $null })
            }
            if (-not ($parsed.$t.PSObject.Properties.Name -contains 'backoffLevel')) {
                $parsed.$t | Add-Member -NotePropertyName 'backoffLevel' -NotePropertyValue 0
            }
            if (-not ($parsed.$t.PSObject.Properties.Name -contains 'backoffState')) {
                $parsed.$t | Add-Member -NotePropertyName 'backoffState' -NotePropertyValue $(if ($parsed.$t.backoffUntil) { 'active' } else { 'clear' })
            }
            if (-not ($parsed.$t.PSObject.Properties.Name -contains 'standdownDecisionKey')) {
                $parsed.$t | Add-Member -NotePropertyName 'standdownDecisionKey' -NotePropertyValue $null
            }
        }
        if (-not ($parsed.server.PSObject.Properties.Name -contains 'lastHealthAt')) {
            $parsed.server | Add-Member -NotePropertyName 'lastHealthAt' -NotePropertyValue $null
        }
        if (-not ($parsed.server.PSObject.Properties.Name -contains 'lastHealthyAt')) {
            $parsed.server | Add-Member -NotePropertyName 'lastHealthyAt' -NotePropertyValue $null
        }
        if (-not ($parsed.server.PSObject.Properties.Name -contains 'lastHealthCheckAt')) {
            $legacyHealthAt = $parsed.server.lastHealthAt
            $parsed.server | Add-Member -NotePropertyName 'lastHealthCheckAt' -NotePropertyValue $legacyHealthAt
        }
        Normalize-WatchdogBackoffState -TargetState $parsed.cockpit
        Normalize-WatchdogBackoffState -TargetState $parsed.server
        if (-not ($parsed.PSObject.Properties.Name -contains 'freshness')) {
            $parsed | Add-Member -NotePropertyName 'freshness' -NotePropertyValue ([PSCustomObject]@{ lastHeadSha = $null; lastCheckTime = $null })
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

function Convert-Iso8601Z {
    param([Parameter(Mandatory)][string]$Value)
    $styles = [System.Globalization.DateTimeStyles]::AssumeUniversal -bor [System.Globalization.DateTimeStyles]::AdjustToUniversal
    foreach ($format in @("yyyy-MM-dd'T'HH:mm:ss'Z'", "yyyy-MM-dd'T'HH:mm:ss.f'Z'", "yyyy-MM-dd'T'HH:mm:ss.ff'Z'", "yyyy-MM-dd'T'HH:mm:ss.fff'Z'", "yyyy-MM-dd'T'HH:mm:ss.ffff'Z'", "yyyy-MM-dd'T'HH:mm:ss.fffff'Z'", "yyyy-MM-dd'T'HH:mm:ss.ffffff'Z'", "yyyy-MM-dd'T'HH:mm:ss.fffffff'Z'")) {
        try {
            return [datetimeoffset]::ParseExact($Value, $format, [System.Globalization.CultureInfo]::InvariantCulture, $styles)
        } catch { }
    }
    return $null
}

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
    if ($null -eq (Convert-Iso8601Z -Value ([string]$m.started))) { return $null }
    if ($null -eq (Convert-Iso8601Z -Value ([string]$m.expires))) { return $null }
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
    Normalize-WatchdogBackoffState -TargetState $TargetState
    $level = [int]$TargetState.backoffLevel
    if ($TargetState.backoffUntil) {
        $until = [datetime]::ParseExact([string]$TargetState.backoffUntil, 'o', [System.Globalization.CultureInfo]::InvariantCulture, [System.Globalization.DateTimeStyles]::AdjustToUniversal)
        if ($Now -lt $until) {
            $state = if ($level -gt 1) { 'escalated' } else { 'active' }
            $TargetState.backoffState = $state
            return [PSCustomObject]@{ InBackoff = $true; Until = $until; State = $state; Level = $level }
        }
    }
    $TargetState.backoffState = 'clear'
    return [PSCustomObject]@{ InBackoff = $false; Until = $null; State = 'clear'; Level = $level }
}
function Add-DeathRecord {
    <#
    .SYNOPSIS
    Appends a death timestamp and applies exponential crashloop backoff after each
    threshold crossing. A quiet trailing window after the previous cooldown resets
    escalation to level one.
    #>
    param($TargetState, [Parameter(Mandatory)][datetime]$Now, [int]$WindowMinutes = 10, [int]$Threshold = 3, [int]$BackoffMinutes = 10)
    $windowStart = $Now.AddMinutes(-$WindowMinutes)
    $existing = @($TargetState.deaths | Where-Object {
        try { ([datetime]::Parse([string]$_, [System.Globalization.CultureInfo]::InvariantCulture, [System.Globalization.DateTimeStyles]::AdjustToUniversal)) -ge $windowStart } catch { $false }
    })
    $previousLevel = if ($TargetState.PSObject.Properties.Name -contains 'backoffLevel') { [int]$TargetState.backoffLevel } else { 0 }
    $previousUntil = $null
    if ($TargetState.backoffUntil) {
        try { $previousUntil = [datetime]::Parse([string]$TargetState.backoffUntil, [System.Globalization.CultureInfo]::InvariantCulture, [System.Globalization.DateTimeStyles]::AdjustToUniversal) } catch { $previousUntil = $null }
    }
    if ($previousUntil -and $Now -ge $previousUntil.AddMinutes($WindowMinutes)) {
        $previousLevel = 0
        $TargetState.backoffLevel = 0
    }
    $updated = @($existing) + $Now.ToString('o')
    $tripped = $false
    if ($updated.Count -ge $Threshold) {
        # Keep both the level and DateTime arithmetic inside Int32-safe minutes.
        # Saturate at the largest representable duration instead of allowing a
        # high-level crashloop to overflow the Int32 cast or AddMinutes call.
        $maxMinutes = [int64][int]::MaxValue
        $baseMinutes = [int64]$BackoffMinutes
        if ($baseMinutes -lt 1) { $baseMinutes = 1 }
        if ($baseMinutes -gt $maxMinutes) { $baseMinutes = $maxMinutes }
        $desiredLevel = [int64]$previousLevel + 1
        if ($desiredLevel -lt 1) { $desiredLevel = 1 }
        $actualLevel = 1
        $durationMinutes = $baseMinutes
        while ($actualLevel -lt $desiredLevel -and $durationMinutes -le [int64]($maxMinutes / 2)) {
            $durationMinutes *= 2
            $actualLevel++
        }
        $TargetState.backoffLevel = [int]$actualLevel
        $TargetState.backoffState = if ($actualLevel -gt 1) { 'escalated' } else { 'active' }
        $TargetState.backoffUntil = $Now.AddMinutes($durationMinutes).ToString('o')
        $TargetState.deaths = @()
        $tripped = $true
    } else {
        $TargetState.deaths = $updated
        $TargetState.backoffState = 'clear'
    }
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
    if (-not $coverage.StandDown) { $State.cockpit.standdownDecisionKey = $null }
    if ($coverage.StandDown) {
        $standdownBackoff = Get-BackoffState -TargetState $State.cockpit -Now $Now
        $decisionKey = Get-StandDownDecisionKey -Marker $marker
        Write-StandDownDecision -Path $RestartLogPath -TargetState $State.cockpit -DecisionKey $decisionKey -Row @{
            ts = $Now.ToString('o'); target = 'cockpit'; event = 'standdown'; decision = 'planned-outage'
            owner = $marker.owner; reason = $marker.reason; expires = $marker.expires
            backoffUntil = $standdownBackoff.Until
            backoffState = $standdownBackoff.State
        } | Out-Null
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
    $backoffNow = Get-BackoffState -TargetState $State.cockpit -Now $Now

    Write-RestartLogRow -Path $RestartLogPath -Row @{
        ts = $Now.ToString('o'); target = 'cockpit'; event = 'relaunch'
        deadPid = $deadPid; ageSec = $age; relaunchPid = $launch.Pid
        deathsInWindow = $deathRecord.DeathsInWindow; backoffUntil = $backoffNow.Until; backoffState = $backoffNow.State
    }
    if ($deathRecord.Tripped) {
        Write-RestartLogRow -Path $RestartLogPath -Row @{
            ts = $Now.ToString('o'); target = 'cockpit'; event = 'crashloop-backoff'
            deathsInWindow = $deathRecord.DeathsInWindow; backoffUntil = $backoffNow.Until; backoffState = $backoffNow.State
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
    if (-not $coverage.StandDown) { $State.server.standdownDecisionKey = $null }
    if ($coverage.StandDown) {
        $standdownBackoff = Get-BackoffState -TargetState $State.server -Now $Now
        $decisionKey = Get-StandDownDecisionKey -Marker $marker
        Write-StandDownDecision -Path $RestartLogPath -TargetState $State.server -DecisionKey $decisionKey -Row @{
            ts = $Now.ToString('o'); target = 'server'; event = 'standdown'; decision = 'planned-outage'
            owner = $marker.owner; reason = $marker.reason; expires = $marker.expires
            backoffUntil = $standdownBackoff.Until
            backoffState = $standdownBackoff.State
        } | Out-Null
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

    $lastHealthyAt = $null
    if ($State.server.lastHealthyAt) {
        try {
            $lastHealthyAt = [datetime]::Parse([string]$State.server.lastHealthyAt, [System.Globalization.CultureInfo]::InvariantCulture, [System.Globalization.DateTimeStyles]::AdjustToUniversal)
        } catch {
            $lastHealthyAt = $null
        }
    }
    $healthAgeSec = if ($null -ne $lastHealthyAt) { [int][math]::Max(0, [math]::Round(($Now - $lastHealthyAt).TotalSeconds)) } else { $null }
    $healthy = Test-ServerHealth -Url $HealthUrl
    $State.server.lastHealthCheckAt = $Now.ToString('o')
    if ($healthy) {
        $State.server.lastHealthyAt = $Now.ToString('o')
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
    $backoffNow = Get-BackoffState -TargetState $State.server -Now $Now

    Write-RestartLogRow -Path $RestartLogPath -Row @{
        ts = $Now.ToString('o'); target = 'server'; event = 'relaunch'
        deadPid = $(if ($proc) { [int]$proc.ProcessId } else { $null }); healthAgeSec = $healthAgeSec; relaunchPid = $launch.Pid
        deathsInWindow = $deathRecord.DeathsInWindow; backoffUntil = $backoffNow.Until; backoffState = $backoffNow.State
    }
    if ($deathRecord.Tripped) {
        Write-RestartLogRow -Path $RestartLogPath -Row @{
            ts = $Now.ToString('o'); target = 'server'; event = 'crashloop-backoff'
            deathsInWindow = $deathRecord.DeathsInWindow; backoffUntil = $backoffNow.Until; backoffState = $backoffNow.State
        }
    }

    return [PSCustomObject]@{ Action = 'relaunch'; Detail = "relaunchPid=$($launch.Pid)" }
}

# ---------------------------------------------------------------------------------------
# Freshness leg (issue #545): auto-pull main tree from public/master
# ---------------------------------------------------------------------------------------

function Write-ActivityLedgerRow {
    <#
    .SYNOPSIS
    Appends one JSON activity row to the ledger. Schema: {ts, source, path, line}.
    ConvertTo-Json only, per encoding discipline.
    #>
    param([Parameter(Mandatory)][string]$Path, [Parameter(Mandatory)][hashtable]$Row)
    $dir = Split-Path -Parent $Path
    if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    ($Row | ConvertTo-Json -Compress) | Add-Content -Path $Path -Encoding utf8
}

function Get-RepoHeadSha {
    <#
    .SYNOPSIS
    Returns the SHA of HEAD in the repo, or $null if repo unavailable. -WhatIf mode
    returns a mock SHA for testing.
    #>
    param([Parameter(Mandatory)][string]$RepoPath, [bool]$WhatIfMode = $false)
    if ($WhatIfMode) { return "mock-sha-12345abc" }
    try {
        $sha = & git -C $RepoPath rev-parse HEAD 2>$null
        return if ($LASTEXITCODE -eq 0) { $sha } else { $null }
    } catch {
        return $null
    }
}

function Test-RepoClean {
    <#
    .SYNOPSIS
    Tests if the repo has no tracked modifications and no untracked files that would
    collide with incoming changes from public/master. Returns $true if safe to pull,
    $false if dirty or has collisions. -WhatIf mode returns based on $InjectedDirtyState.
    #>
    param([Parameter(Mandatory)][string]$RepoPath, [bool]$WhatIfMode = $false, [bool]$InjectedDirtyState = $false)
    if ($WhatIfMode) { return -not $InjectedDirtyState }
    try {
        $status = & git -C $RepoPath status --porcelain 2>$null
        if ($LASTEXITCODE -ne 0) { return $false }
        return [string]::IsNullOrWhiteSpace($status)
    } catch {
        return $false
    }
}

function Get-CommitsBehind {
    <#
    .SYNOPSIS
    Returns the count of commits the main tree is behind public/master, or -1 if fetch
    fails. -WhatIf mode returns a mock count for testing.
    #>
    param([Parameter(Mandatory)][string]$RepoPath, [bool]$WhatIfMode = $false, [int]$InjectedCount = 0)
    if ($WhatIfMode) { return $InjectedCount }
    try {
        & git -C $RepoPath fetch public 2>$null | Out-Null
        if ($LASTEXITCODE -ne 0) { return -1 }
        $count = & git -C $RepoPath rev-list --count HEAD..public/master 2>$null
        return if ($LASTEXITCODE -eq 0) { [int]$count } else { -1 }
    } catch {
        return -1
    }
}

function Invoke-GitPullFfOnly {
    <#
    .SYNOPSIS
    Runs git pull --ff-only in the repo, returning $true if successful, $false otherwise.
    -WhatIf mode is a no-op (returns success).
    #>
    param([Parameter(Mandatory)][string]$RepoPath, [bool]$WhatIfMode = $false)
    if ($WhatIfMode) { return $true }
    try {
        $output = & git -C $RepoPath pull --ff-only 2>&1
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    }
}

function Invoke-FreshnessWatchdogTick {
    <#
    .SYNOPSIS
    One tick for the main-tree freshness leg. Order: planned-outage stand-down check,
    then fetch and compare HEAD to public/master. If behind and clean, pull and append
    an advance event. If behind and dirty, append a residue event. If current, no action.
    #>
    param(
        [Parameter(Mandatory)][datetime]$Now,
        [Parameter(Mandatory)]$State,
        [Parameter(Mandatory)][string]$RepoPath,
        [string]$ActivityLedgerPath = $ActivityLedgerPath,
        [string]$MarkerPath = $MarkerPath,
        [bool]$WhatIfMode = $false,
        [int]$InjectedCommitsBehind = -1,
        [bool]$InjectedDirtyState = $false
    )
    $marker = Get-PlannedOutageMarker -Path $MarkerPath
    $coverage = Test-MarkerCoversTarget -Marker $marker -Target 'both' -Now $Now
    if ($coverage.StandDown) {
        return [PSCustomObject]@{ Action = 'standdown'; Detail = "owner=$($marker.owner)" }
    }

    # Fetch and check status
    $behind = if ($InjectedCommitsBehind -ge 0) { $InjectedCommitsBehind } else { Get-CommitsBehind -RepoPath $RepoPath -WhatIfMode $WhatIfMode }
    if ($behind -le 0) {
        return [PSCustomObject]@{ Action = 'current'; Detail = "tree is current" }
    }

    $headSha = Get-RepoHeadSha -RepoPath $RepoPath -WhatIfMode $WhatIfMode
    $clean = if ($InjectedDirtyState -or -not $WhatIfMode) { Test-RepoClean -RepoPath $RepoPath -WhatIfMode $WhatIfMode -InjectedDirtyState $InjectedDirtyState } else { $true }

    if ($clean) {
        $pulled = Invoke-GitPullFfOnly -RepoPath $RepoPath -WhatIfMode $WhatIfMode
        if ($pulled) {
            $newSha = Get-RepoHeadSha -RepoPath $RepoPath -WhatIfMode $WhatIfMode
            Write-ActivityLedgerRow -Path $ActivityLedgerPath -Row @{
                ts = $Now.ToString('o'); source = 'watchdog'
                path = $RepoPath; line = "tree advanced to $newSha ($behind commits pulled)"
            }
            return [PSCustomObject]@{ Action = 'advanced'; Detail = "to $newSha" }
        } else {
            Write-ActivityLedgerRow -Path $ActivityLedgerPath -Row @{
                ts = $Now.ToString('o'); source = 'watchdog'
                path = $RepoPath; line = "PULL FAILED: tree $behind commits behind but pull --ff-only returned non-zero"
            }
            return [PSCustomObject]@{ Action = 'pull-failed'; Detail = "git pull exited non-zero" }
        }
    } else {
        # Dirty or collisions: enumerate the problematic files
        $status = & git -C $RepoPath status --porcelain 2>$null
        $files = @($status -split "`n" | Where-Object { $_ } | ForEach-Object { $_.Substring(3) })
        $fileList = $files -join '; '
        Write-ActivityLedgerRow -Path $ActivityLedgerPath -Row @{
            ts = $Now.ToString('o'); source = 'watchdog'
            path = $RepoPath; line = "RESIDUE: tree $behind commits behind but dirty (tracked/untracked): $fileList"
        }
        return [PSCustomObject]@{ Action = 'residue'; Detail = "$($files.Count) files" }
    }
}

# ---------------------------------------------------------------------------------------
# Marker-expiry enforcement leg (issue #464 receipt fix)
# ---------------------------------------------------------------------------------------

function Archive-StaleMarker {
    <#
    .SYNOPSIS
    Renames an expired marker to planned-outage-expired-<ts>.json (never silently deletes
    evidence). Returns the archived path on success, $null on failure.
    #>
    param([Parameter(Mandatory)][string]$MarkerPath, [Parameter(Mandatory)][datetime]$Now)
    if (-not (Test-Path $MarkerPath)) { return $null }
    $dir = Split-Path -Parent $MarkerPath
    $timestamp = $Now.ToString('yyyyMMddTHHmmssZ')
    $archivedPath = Join-Path $dir "planned-outage-expired-$timestamp.json"
    try {
        Rename-Item -Path $MarkerPath -NewName (Split-Path -Leaf $archivedPath) -Force
        return $archivedPath
    } catch {
        Write-Warning "[watchdog] failed to archive stale marker: $($_.Exception.Message)"
        return $null
    }
}

function Invoke-MarkerExpiryEnforcementTick {
    <#
    .SYNOPSIS
    One tick for marker-expiry enforcement. If marker exists AND is expired: archive it,
    run restore-on-removal triggers, and append activity event. Non-expired markers are
    untouched.
    #>
    param(
        [Parameter(Mandatory)][datetime]$Now,
        [string]$MarkerPath = $MarkerPath,
        [string]$ActivityLedgerPath = $ActivityLedgerPath,
        [bool]$WhatIfMode = $false
    )
    $marker = Get-PlannedOutageMarker -Path $MarkerPath
    if ($null -eq $marker) {
        return [PSCustomObject]@{ Action = 'none'; Detail = 'no marker' }
    }

    try {
        $expires = [datetime]::Parse($marker.expires, [System.Globalization.CultureInfo]::InvariantCulture, [System.Globalization.DateTimeStyles]::AdjustToUniversal)
    } catch {
        return [PSCustomObject]@{ Action = 'none'; Detail = 'unparseable expiry' }
    }

    if ($Now -lt $expires) {
        return [PSCustomObject]@{ Action = 'none'; Detail = 'marker not yet expired' }
    }

    # Marker is expired: archive it and run restore triggers
    if (-not $WhatIfMode) {
        $archivedPath = Archive-StaleMarker -MarkerPath $MarkerPath -Now $Now
    } else {
        $archivedPath = (Join-Path (Split-Path -Parent $MarkerPath) "planned-outage-expired-$(($Now).ToString('yyyyMMddTHHmmssZ')).json")
    }

    $overrunMinutes = [math]::Round(($Now - $expires).TotalMinutes, 1)
    Write-ActivityLedgerRow -Path $ActivityLedgerPath -Row @{
        ts = $Now.ToString('o'); source = 'watchdog'
        path = $MarkerPath; line = "MARKER OVERRUN: owner=$($marker.owner) overrun=$($overrunMinutes)min (expired=$($marker.expires))"
    }

    return [PSCustomObject]@{ Action = 'archived'; Detail = "overrun $overrunMinutes min, archived=$archivedPath" }
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

    # #666 startup path-assert twin of the writer's log line: name the exact heartbeat
    # file this watchdog polls, in both the console and the restart-log ledger.
    Write-Host "[liveness-watchdog] polling heartbeat at $HeartbeatPath (repo root $RepoRoot)"
    Write-RestartLogRow -Path $RestartLogPath -Row @{
        ts = [datetime]::UtcNow.ToString('o'); target = 'cockpit'; event = 'watchdog-start'
        heartbeatPath = $HeartbeatPath; repoRoot = $RepoRoot
    }

    $state = Read-WatchdogState -Path $WatchdogStatePath
    $nextCockpitCheck = [datetime]::UtcNow
    $nextServerCheck  = [datetime]::UtcNow
    $nextFreshnessCheck = [datetime]::UtcNow

    try {
        while ($true) {
            $now = [datetime]::UtcNow
            # Marker-expiry enforcement runs every cycle (quick check if marker exists)
            Invoke-MarkerExpiryEnforcementTick -Now $now -MarkerPath $MarkerPath -ActivityLedgerPath $ActivityLedgerPath -WhatIfMode $WhatIf | Out-Null

            if ($now -ge $nextCockpitCheck) {
                Invoke-CockpitWatchdogTick -Now $now -State $state | Out-Null
                $nextCockpitCheck = $now.AddSeconds($CockpitPollIntervalSec)
            }
            if ($now -ge $nextServerCheck) {
                Invoke-ServerWatchdogTick -Now $now -State $state | Out-Null
                $nextServerCheck = $now.AddSeconds($ServerPollIntervalSec)
            }
            if ($now -ge $nextFreshnessCheck) {
                Invoke-FreshnessWatchdogTick -Now $now -State $state -RepoPath $RepoRoot -ActivityLedgerPath $ActivityLedgerPath -WhatIfMode $WhatIf | Out-Null
                $nextFreshnessCheck = $now.AddSeconds($FreshnessPollIntervalSec)
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
