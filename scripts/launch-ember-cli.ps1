# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$BunVersion = "1.3.12"
$BunArchiveUrl = "https://github.com/oven-sh/bun/releases/download/bun-v1.3.12/bun-windows-x64.zip"
$BunArchiveSha256 = "841ff9c5dffcaa3a2620d1e3f87ee500f32a4ca830b001cade7a3479609d4a89"
$EmberLauncherMutexName = "Local\EmberCliCanonicalLauncher"
$EmberInTreeStateDirectoryName = ".ember"
$EmberSanctionedStateDirectoryName = "cockpit-state"
# Mirrors ember-named-root-discovery.name_patterns in manifests/ember-01-custody/root-spec.json.
$EmberCensusDiscoveryNamePatterns = @("ember*", "wt-stab480-bench594-scratch")

Add-Type @"
using System;
using System.Runtime.InteropServices;
using System.Collections.Generic;
using System.Text;
public static class EmberWindowNative {
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
    [StructLayout(LayoutKind.Sequential)] public struct MONITORINFO {
        public int cbSize; public RECT rcMonitor; public RECT rcWork; public uint dwFlags;
    }
    [DllImport("kernel32.dll")] public static extern IntPtr GetConsoleWindow();
    [DllImport("user32.dll")] public static extern bool IsWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);
    [DllImport("user32.dll")] public static extern IntPtr MonitorFromWindow(IntPtr hWnd, uint flags);
    [DllImport("user32.dll")] public static extern bool GetMonitorInfo(IntPtr monitor, ref MONITORINFO info);
    [DllImport("user32.dll")] public static extern bool SetWindowPos(
        IntPtr hWnd, IntPtr insertAfter, int x, int y, int width, int height, uint flags);
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc callback, IntPtr state);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr hWnd, StringBuilder text, int count);
    public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr state);
    public static long[] FindVisibleWindowsByTitle(string token) {
        var found = new List<long>();
        EnumWindows((hWnd, state) => {
            if (!IsWindowVisible(hWnd)) return true;
            var title = new StringBuilder(512);
            GetWindowText(hWnd, title, title.Capacity);
            if (title.ToString().Contains(token)) found.Add(hWnd.ToInt64());
            return true;
        }, IntPtr.Zero);
        return found.ToArray();
    }
}
"@

function Get-EmberLeftHalfRectangle(
    [int]$Left,
    [int]$Top,
    [int]$Right,
    [int]$Bottom
) {
    if ($Right -le $Left -or $Bottom -le $Top) { throw "The monitor work area is invalid." }
    [pscustomobject]@{
        X = $Left
        Y = $Top
        Width = [Math]::Floor(($Right - $Left) / 2)
        Height = $Bottom - $Top
    }
}

# --- Cockpit state root (issue #1330) ------------------------------------------------
# The completion verifier certifies this tree by TOTALITY -- every file, tracked and
# untracked -- so a cockpit writing inside it produces list-vs-hash contradictions and a
# red receipt. Rather than weaken the census with exclusions, the writer moves out: all
# cockpit-mutable state (pinned runtime, built cockpit binaries, build logs, run dirs)
# lives under an external root, and the cockpit can stay up while the tree is certified.
#
# This is the ONE PowerShell resolution point. No other line in this script may join a
# state path onto $repositoryRoot.

function Get-EmberStateRootKey([string]$RepositoryRoot) {
    # Mirrors repoStateKey in tools/ember-cli/src/utils/ember-state-root.ts. Both sides are
    # pinned to the same fixture vectors so the two implementations cannot drift apart.
    # Lowercased because Windows paths are case-insensitive: two spellings of one checkout
    # must key to one state directory.
    $full = [System.IO.Path]::GetFullPath($RepositoryRoot).TrimEnd(
        [System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar)
    $key = ($full.ToLowerInvariant() -replace '[^a-z0-9]+', '-').Trim('-')
    if ([string]::IsNullOrWhiteSpace($key)) {
        throw "Ember could not derive a state key for this repository location."
    }
    return $key
}

function Test-EmberDiscoveryNameMatch([string]$Name) {
    foreach ($pattern in $EmberCensusDiscoveryNamePatterns) {
        if ($Name.ToLowerInvariant() -like $pattern.ToLowerInvariant()) { return $true }
    }
    return $false
}

function Assert-EmberStateRootIsWritable([string]$StateRoot, [string]$RepositoryRoot) {
    # Writer-side and fail-closed. A verifier-only refusal finds the regression at the NEXT
    # census, by which time the run is already red; this refuses before anything is written.
    # Mirrors assertStateRootIsWritable in tools/ember-cli/src/utils/ember-state-root.ts.
    $resolved = [System.IO.Path]::GetFullPath($StateRoot)
    $repository = [System.IO.Path]::GetFullPath($RepositoryRoot).TrimEnd(
        [System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar)

    if ($resolved.Equals($repository, [StringComparison]::OrdinalIgnoreCase) -or
        $resolved.StartsWith($repository + [System.IO.Path]::DirectorySeparatorChar,
            [StringComparison]::OrdinalIgnoreCase)) {
        throw ("Cockpit state root '$resolved' is inside the repository. The completion " +
            "verifier censuses that tree in full, so state written there reds the run. " +
            "Point EMBER_STATE_ROOT at a directory outside it.")
    }

    # The non-obvious one: the census DISCOVERS roots by name under EMBER_NAMED_ROOT_PARENT
    # (root-spec.json's ember-named-root-discovery) and byte-hashes every match. A state
    # root in a directory named e.g. 'ember-cockpit-state' would be censused wherever else
    # it sits, so the relocation would buy nothing.
    if ([string]::IsNullOrWhiteSpace($env:EMBER_NAMED_ROOT_PARENT)) { return }
    $parent = [System.IO.Path]::GetFullPath($env:EMBER_NAMED_ROOT_PARENT.Trim()).TrimEnd(
        [System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar)
    if (-not $resolved.StartsWith($parent + [System.IO.Path]::DirectorySeparatorChar,
            [StringComparison]::OrdinalIgnoreCase)) {
        return
    }
    $child = $resolved.Substring($parent.Length).Split(
        [char[]]@([System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar),
        [StringSplitOptions]::RemoveEmptyEntries)[0]
    if (Test-EmberDiscoveryNameMatch $child) {
        throw ("Cockpit state root '$resolved' sits under the census named-root parent in " +
            "'$child', whose name matches a root-discovery pattern " +
            "($($EmberCensusDiscoveryNamePatterns -join ', ')). The census discovers and " +
            "byte-hashes that directory, so relocating there buys nothing. Use a directory " +
            "named '$EmberSanctionedStateDirectoryName', or another name outside those patterns.")
    }
}

function Get-EmberStateRoot([string]$RepositoryRoot) {
    # 1. EMBER_STATE_ROOT verbatim, so an operator can place cockpit state deliberately.
    if (-not [string]::IsNullOrWhiteSpace($env:EMBER_STATE_ROOT)) {
        $override = [System.IO.Path]::GetFullPath($env:EMBER_STATE_ROOT.Trim())
        Assert-EmberStateRootIsWritable $override $RepositoryRoot
        return $override
    }
    # 2. <EMBER_HOME>/cockpit-state/<key>, EMBER_HOME defaulting to the CLI's own
    #    user-scoped config home -- always outside any checkout.
    $emberHome = $env:EMBER_HOME
    if ([string]::IsNullOrWhiteSpace($emberHome)) {
        $profile = $env:USERPROFILE
        if ([string]::IsNullOrWhiteSpace($profile)) { $profile = $HOME }
        if ([string]::IsNullOrWhiteSpace($profile)) {
            throw "Ember could not locate a user profile directory for its state root."
        }
        $emberHome = Join-Path $profile $EmberInTreeStateDirectoryName
    }
    $keyed = Join-Path (Join-Path $emberHome $EmberSanctionedStateDirectoryName) (Get-EmberStateRootKey $RepositoryRoot)
    $resolved = [System.IO.Path]::GetFullPath($keyed)
    Assert-EmberStateRootIsWritable $resolved $RepositoryRoot
    return $resolved
}

function Move-EmberStateOutOfTree([string]$RepositoryRoot, [string]$StateRoot) {
    # One-time migration: an in-tree .ember/ from a pre-relocation launch is moved wholesale
    # to $StateRoot and NOTHING is left behind, so the very next census sees a clean tree.
    $inTree = Join-Path $RepositoryRoot $EmberInTreeStateDirectoryName
    if (-not (Test-Path -LiteralPath $inTree -PathType Container)) { return }

    $entries = @(Get-ChildItem -LiteralPath $inTree -Force -ErrorAction Stop)
    if ($entries.Count -gt 0) {
        New-Item -ItemType Directory -Force -Path $StateRoot | Out-Null
        foreach ($entry in $entries) {
            $destination = Join-Path $StateRoot $entry.Name
            if (Test-Path -LiteralPath $destination) {
                # The external root already owns this name: it is the live copy, and the
                # in-tree one is stale residue. Discard the residue rather than merging two
                # divergent histories of the same state.
                Remove-Item -LiteralPath $entry.FullName -Recurse -Force
                continue
            }
            Move-Item -LiteralPath $entry.FullName -Destination $destination
        }
        Write-Host "Moved $($entries.Count) cockpit state item(s) out of the repository into $StateRoot."
    }

    Remove-Item -LiteralPath $inTree -Recurse -Force
}

function Assert-EmberStateIsExternal([string]$RepositoryRoot) {
    # Fail-closed re-check: if the entry reappeared (a stale binary at an old revision still
    # writing, a hand-created path), refuse rather than certify around it.
    #
    # ANY in-tree `.ember` entry is refused -- directory, file, OR reparse point. A
    # junction pointing at the external root is the dangerous shape: the census's
    # ignored-registry scan walks THROUGH it and hashes live external state, so a
    # compatibility shim would reintroduce exactly the contamination this move removes.
    # Refusing every shape is also the only version with no blind spot to argue about.
    $inTree = Join-Path $RepositoryRoot $EmberInTreeStateDirectoryName
    $entry = Get-Item -LiteralPath $inTree -Force -ErrorAction SilentlyContinue
    if ($null -eq $entry) { return }

    $isReparsePoint = ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0
    if (-not $isReparsePoint -and ($entry -is [IO.DirectoryInfo]) -and
        @(Get-ChildItem -LiteralPath $inTree -Force -ErrorAction SilentlyContinue).Count -eq 0) {
        # A genuinely empty directory writes nothing; sweep it instead of refusing.
        Remove-Item -LiteralPath $inTree -Recurse -Force -ErrorAction SilentlyContinue
        return
    }

    $shape = if ($isReparsePoint) { "a junction or symlink" }
        elseif ($entry -is [IO.DirectoryInfo]) { "a directory" }
        else { "a file" }
    throw ("Cockpit state is present inside the repository at '$inTree' (it is $shape). " +
        "It must live outside the certified tree, and a shim pointing at the external " +
        "root is not acceptable -- the census walks through it. Stop every Ember process " +
        "writing there, remove that entry, and run Ember.cmd again.")
}

function Test-IsOwnedEmberExecutablePath([string]$Candidate, [string]$StateRoot) {
    if ([string]::IsNullOrWhiteSpace($Candidate)) { return $false }
    try {
        $ownedRoot = [System.IO.Path]::GetFullPath((Join-Path $StateRoot "runtime\ember"))
        $candidatePath = [System.IO.Path]::GetFullPath($Candidate)
        return $candidatePath.StartsWith($ownedRoot + [System.IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase) -and
            [System.IO.Path]::GetFileName($candidatePath).Equals("Ember.exe", [StringComparison]::OrdinalIgnoreCase)
    }
    catch { return $false }
}

function Enter-EmberLauncherLease([string]$Name = $EmberLauncherMutexName) {
    $mutex = [Threading.Mutex]::new($false, $Name)
    try {
        $acquired = $false
        try { $acquired = $mutex.WaitOne(0) }
        catch [Threading.AbandonedMutexException] { $acquired = $true }
        if (-not $acquired) { throw "Another Ember cockpit is already running." }
        return $mutex
    }
    catch {
        $mutex.Dispose()
        throw
    }
}

function Stop-StaleOwnedEmberApplications([string]$StateRoot) {
    $stale = @(Get-CimInstance Win32_Process -Filter "Name='Ember.exe'" -ErrorAction Stop |
        Where-Object {
            $_.ProcessId -ne $PID -and
            (Test-IsOwnedEmberExecutablePath ([string]$_.ExecutablePath) $StateRoot)
        })
    foreach ($process in $stale) {
        Stop-Process -Id $process.ProcessId -Force -ErrorAction Stop
        Wait-Process -Id $process.ProcessId -Timeout 5 -ErrorAction SilentlyContinue
        if (Get-Process -Id $process.ProcessId -ErrorAction SilentlyContinue) {
            throw "A stale repository-owned Ember process could not be retired."
        }
    }
}

function Get-EmberHostWindowHandle {
    # Windows Terminal can host several windows in one process, so process ancestry and
    # MainWindowHandle are ambiguous. Give this active tab a one-use title token, then bind the
    # exact visible top-level window that displays it.
    $token = "ember-launch-$PID-$([Guid]::NewGuid().ToString('N'))"
    [Console]::Write("$([char]27)]0;$token$([char]7)")
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        $matches = @([EmberWindowNative]::FindVisibleWindowsByTitle($token))
        if ($matches.Count -eq 1) { return [IntPtr]$matches[0] }
        if ($matches.Count -gt 1) { throw "Ember's terminal ownership marker matched more than one window." }
        Start-Sleep -Milliseconds 50
    }
    throw "Ember could not bind the active terminal tab to exactly one visible window."
}
function Set-EmberWindowToLeftWorkArea([IntPtr]$WindowHandle) {
    $monitor = [EmberWindowNative]::MonitorFromWindow($WindowHandle, 2)
    if ($monitor -eq [IntPtr]::Zero) { throw "Ember could not identify the active monitor." }
    $info = [EmberWindowNative+MONITORINFO]::new()
    $info.cbSize = [Runtime.InteropServices.Marshal]::SizeOf($info)
    if (-not [EmberWindowNative]::GetMonitorInfo($monitor, [ref]$info)) {
        throw "Ember could not read the monitor work area."
    }
    $target = Get-EmberLeftHalfRectangle $info.rcWork.Left $info.rcWork.Top $info.rcWork.Right $info.rcWork.Bottom
    # SWP_NOZORDER only. Deliberately do not use SWP_NOSIZE: width and height are authoritative.
    if (-not [EmberWindowNative]::SetWindowPos($WindowHandle, [IntPtr]::Zero, $target.X, $target.Y, $target.Width, $target.Height, 0x0004)) {
        throw "Ember could not place its terminal window."
    }
    for ($attempt = 0; $attempt -lt 5; $attempt++) {
        $actual = [EmberWindowNative+RECT]::new()
        if ([EmberWindowNative]::GetWindowRect($WindowHandle, [ref]$actual) -and
            $actual.Left -eq $target.X -and $actual.Top -eq $target.Y -and
            ($actual.Right - $actual.Left) -eq $target.Width -and
            ($actual.Bottom - $actual.Top) -eq $target.Height) {
            return $target
        }
        Start-Sleep -Milliseconds 100
    }
    throw "Ember's terminal window did not retain the requested left-half work-area geometry."
}

# $Headline is the one line an operator reads. It defaults to the preparation failure, but
# a cockpit that RAN and then exited is not a preparation failure -- reporting it as one
# sent operators hunting a broken install after a deliberate stop. The child-exit callers
# pass their own headline.
function Stop-EmberLaunch([string]$Message, [string]$Headline = "Ember could not prepare its runtime.") {
    Write-Host ""
    Write-Host $Headline -ForegroundColor Red
    if (-not [string]::IsNullOrWhiteSpace($Message)) { Write-Host $Message }
    exit 1
}

function Stop-EmberLaunchAfterChildExit([int]$ExitCode) {
    Stop-EmberLaunch "The cockpit started and then stopped. Nothing needs repairing unless this was unexpected." `
        "Ember CLI exited with code $ExitCode."
}

function Get-VerifiedBun([string]$StateRoot) {
    if ($env:EMBER_LAUNCH_TEST_MODE -eq "1") {
        $candidate = $env:EMBER_LAUNCH_TEST_RUNTIME
        if ([string]::IsNullOrWhiteSpace($candidate) -or -not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            throw "The launch test runtime is missing."
        }
        return (Resolve-Path -LiteralPath $candidate).Path
    }

    $installed = Get-Command bun.exe,bun.cmd -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -ne $installed -and -not [string]::IsNullOrWhiteSpace($installed.Source)) {
        try {
            $installedVersion = (& $installed.Source --version 2>$null | Select-Object -First 1).Trim()
            if ($installedVersion -eq $BunVersion) {
                return $installed.Source
            }
        }
        catch {
            # A missing, broken, or wrong-version PATH runtime is not authoritative.
        }
    }

    $runtimeParent = Join-Path $StateRoot "runtime"
    $runtimeRoot = Join-Path $runtimeParent "bun-v$BunVersion"
    $bun = Join-Path $runtimeRoot "bun-windows-x64\bun.exe"
    if (Test-Path -LiteralPath $bun -PathType Leaf) {
        return $bun
    }

    New-Item -ItemType Directory -Force -Path $runtimeParent | Out-Null
    $transaction = Join-Path $runtimeParent (".install-" + [Guid]::NewGuid().ToString("N"))
    $archive = Join-Path $transaction "bun.zip"
    $expanded = Join-Path $transaction "expanded"
    try {
        New-Item -ItemType Directory -Force -Path $transaction | Out-Null
        Write-Host "Preparing Ember's pinned local runtime once..."
        Invoke-WebRequest -UseBasicParsing -Uri $BunArchiveUrl -OutFile $archive
        $actualSha256 = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actualSha256 -ne $BunArchiveSha256) {
            throw "The downloaded runtime failed its SHA-256 check."
        }
        Expand-Archive -LiteralPath $archive -DestinationPath $expanded
        $expandedBunRoot = Join-Path $expanded "bun-windows-x64"
        $expandedBun = Join-Path $expandedBunRoot "bun.exe"
        if (-not (Test-Path -LiteralPath $expandedBun -PathType Leaf)) {
            throw "The verified runtime archive did not contain bun.exe."
        }
        if (-not (Test-Path -LiteralPath $runtimeRoot)) {
            New-Item -ItemType Directory -Force -Path $runtimeRoot | Out-Null
        }
        if (-not (Test-Path -LiteralPath $bun -PathType Leaf)) {
            Move-Item -LiteralPath $expandedBunRoot -Destination (Join-Path $runtimeRoot "bun-windows-x64")
        }
    }
    finally {
        if (Test-Path -LiteralPath $transaction) {
            Remove-Item -LiteralPath $transaction -Recurse -Force
        }
    }
    if (-not (Test-Path -LiteralPath $bun -PathType Leaf)) {
        throw "The verified runtime could not be installed."
    }
    return $bun
}

if ($env:EMBER_LAUNCH_LIBRARY_ONLY -eq "1") { return }

$launcherLease = $null
try {
    $repositoryRoot = Split-Path -Parent $PSScriptRoot
    $sourceRoot = Join-Path $repositoryRoot "tools\ember-cli\src"
    $entrypoint = Join-Path $sourceRoot "entrypoints\main.ts"
    $package = Join-Path $sourceRoot "package.json"
    $lock = Join-Path $sourceRoot "bun.lock"
    foreach ($required in @($entrypoint, $package, $lock)) {
        if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
            throw "This copy of the repository is incomplete. Restore it and run Ember.cmd again."
        }
    }

    # State root first: the migration below must complete before anything writes runtime
    # bytes, and the lease must be held before the migration moves files another launcher
    # could be reading. EMBER_STATE_ROOT is exported so the cockpit child resolves the
    # identical root instead of recomputing its own.
    $stateRoot = Get-EmberStateRoot $repositoryRoot
    if ($env:EMBER_LAUNCH_TEST_MODE -ne "1") {
        $launcherLease = Enter-EmberLauncherLease
    }
    Move-EmberStateOutOfTree $repositoryRoot $stateRoot
    Assert-EmberStateIsExternal $repositoryRoot
    $env:EMBER_STATE_ROOT = $stateRoot

    # Bun's package cache is cockpit state, so it moves out with the rest. node_modules
    # itself cannot: Bun resolves it by walking up from the importing file, so it has to
    # stay beside the sources, inside the censused tree.
    $env:BUN_INSTALL_CACHE_DIR = Join-Path $stateRoot "bun-cache"

    $bun = Get-VerifiedBun $stateRoot
    $dependenciesReady = Test-Path -LiteralPath (Join-Path $sourceRoot "node_modules\react\package.json") -PathType Leaf
    if (-not $dependenciesReady) {
        # THE ONE REMAINING IN-TREE WRITE, and it is deliberate. Installing populates
        # tools/ember-cli/src/node_modules/ inside the certified tree; a census running
        # concurrently WILL red. This is a one-time preparation step, not steady state:
        # once dependencies exist, launches perform no in-tree writes and the cockpit can
        # stay up across certifications, which is the acceptance this issue claims.
        # Announced rather than silent so an operator who sees it knows to let it finish
        # before a census window opens.
        Write-Host "Preparing Ember's interface dependencies once. This writes into the repository (node_modules); let it finish before starting a certification run."
        Push-Location $sourceRoot
        try {
            & $bun install --frozen-lockfile --production
            if ($LASTEXITCODE -ne 0) {
                throw "Dependency preparation exited with code $LASTEXITCODE."
            }
        }
        finally {
            Pop-Location
        }
        if ($env:EMBER_LAUNCH_TEST_MODE -ne "1" -and -not (Test-Path -LiteralPath (Join-Path $sourceRoot "node_modules\react\package.json") -PathType Leaf)) {
            throw "Dependency preparation did not produce the required interface runtime."
        }
    }

    if ([string]::IsNullOrWhiteSpace($env:EMBER_GPU_FREE)) {
        $env:EMBER_GPU_FREE = "1"
    }

    if ($env:EMBER_LAUNCH_TEST_MODE -eq "1") {
        Push-Location $sourceRoot
        try {
            & $bun run entrypoints/main.ts
            $exitCode = $LASTEXITCODE
        }
        finally {
            Pop-Location
        }
        if ($exitCode -ne 0) {
            Stop-EmberLaunchAfterChildExit $exitCode
        }
        return
    }

    Stop-StaleOwnedEmberApplications $stateRoot

    $commit = (& git -C $repositoryRoot rev-parse HEAD 2>$null | Select-Object -First 1).Trim()
    if ($commit -notmatch "^[0-9a-f]{40}$") {
        throw "This repository does not have an exact Git source identity."
    }
    $applicationRoot = Join-Path $stateRoot "runtime\ember\$commit"
    $application = Join-Path $applicationRoot "Ember.exe"
    if (-not (Test-Path -LiteralPath $application -PathType Leaf)) {
        # Compile STRAIGHT into the state root. The build used to emit ember.exe beside the
        # sources and then move it, which put a transient writer inside the censused tree
        # for the length of every build. Publishing is write-to-partial-then-rename ON THE
        # DESTINATION volume, so a crash mid-build can never leave a truncated binary at
        # the final name for the next launch's Test-Path to accept.
        $buildOutput = Join-Path $applicationRoot "Ember.exe.partial"
        $buildLog = Join-Path $stateRoot "runtime\ember-build.log"
        New-Item -ItemType Directory -Force -Path $applicationRoot | Out-Null
        try {
            Push-Location $sourceRoot
            try {
                $previousErrorActionPreference = $ErrorActionPreference
                $ErrorActionPreference = "Continue"
                $previousBuildOutfile = $env:EMBER_BUILD_OUTFILE
                $env:EMBER_BUILD_OUTFILE = $buildOutput
                try {
                    & $bun run build *> $buildLog
                }
                finally {
                    $env:EMBER_BUILD_OUTFILE = $previousBuildOutfile
                    $ErrorActionPreference = $previousErrorActionPreference
                }
                $buildExit = $LASTEXITCODE
            }
            finally {
                Pop-Location
            }
            if ($buildExit -ne 0 -or -not (Test-Path -LiteralPath $buildOutput -PathType Leaf)) {
                throw "Ember's local application build was refused. Restore a clean repository and run Ember.cmd again."
            }
            Move-Item -LiteralPath $buildOutput -Destination $application
        }
        finally {
            if (Test-Path -LiteralPath $buildOutput -PathType Leaf) {
                Remove-Item -LiteralPath $buildOutput -Force
            }
        }
    }
    Assert-EmberStateIsExternal $repositoryRoot

    $windowHandle = Get-EmberHostWindowHandle
    Set-EmberWindowToLeftWorkArea $windowHandle | Out-Null

    # Invoke in this shell: no second terminal or dead launcher window may remain underneath.
    & $application
    $applicationExit = $LASTEXITCODE
    if ($applicationExit -ne 0) {
        Stop-EmberLaunchAfterChildExit $applicationExit
    }
}
catch {
    Stop-EmberLaunch $_.Exception.Message
}
finally {
    if ($null -ne $launcherLease) {
        try { $launcherLease.ReleaseMutex() } catch {}
        $launcherLease.Dispose()
    }
}
