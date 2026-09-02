# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot "ember-launch-staging.ps1")

$BunVersion = "1.3.12"
$BunArchiveUrl = "https://github.com/oven-sh/bun/releases/download/bun-v1.3.12/bun-windows-x64.zip"
$BunArchiveSha256 = "841ff9c5dffcaa3a2620d1e3f87ee500f32a4ca830b001cade7a3479609d4a89"
$EmberLauncherMutexName = "Local\EmberCliCanonicalLauncher"
$EmberInTreeStateDirectoryName = ".ember"
$EmberSanctionedStateDirectoryName = "cockpit-state"
# Mirrors ember-named-root-discovery.name_patterns in manifests/ember-01-custody/root-spec.json.
$EmberCensusDiscoveryNamePatterns = @("ember*", "wt-stab480-bench594-scratch")

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
    # Mirrors repoStateKey in src/ember/infrastructure/tools/ember-cli/src/utils/ember-state-root.ts. Both sides are
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
    # Mirrors assertStateRootIsWritable in src/ember/infrastructure/tools/ember-cli/src/utils/ember-state-root.ts.
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
    # 2. <EMBER_HOME>/cockpit-state/<key> when EMBER_HOME is explicit.
    # 3. the governed B: cockpit-state parent on Windows (#1317), preserving the C: operating
    #    reserve. Non-Windows direct launches retain the user-scoped config fallback.
    $emberHome = $env:EMBER_HOME
    if ([string]::IsNullOrWhiteSpace($emberHome)) {
        if ([System.Environment]::OSVersion.Platform -eq [System.PlatformID]::Win32NT) {
            $emberHome = [System.IO.Path]::Combine(
                ("B:" + [System.IO.Path]::DirectorySeparatorChar),
                "M"
            )
        } else {
            $profile = $env:USERPROFILE
            if ([string]::IsNullOrWhiteSpace($profile)) { $profile = $HOME }
            if ([string]::IsNullOrWhiteSpace($profile)) {
                throw "Ember could not locate a user profile directory for its state root."
            }
            $emberHome = Join-Path $profile $EmberInTreeStateDirectoryName
        }
    }
    # Construct the default lexically: Join-Path consults the PowerShell drive provider and
    # fails on clean hosts before the governed B: volume is mounted.
    $keyed = [System.IO.Path]::Combine(
        $emberHome,
        $EmberSanctionedStateDirectoryName,
        (Get-EmberStateRootKey $RepositoryRoot)
    )
    $resolved = [System.IO.Path]::GetFullPath($keyed)
    Assert-EmberStateRootIsWritable $resolved $RepositoryRoot
    return $resolved
}

function Assert-NoResidentCockpitWorktrees([string]$RepositoryRoot) {
    # Worktrees are the ONE thing migration must not touch. Moving a registered worktree
    # breaks its administrative link (git still records the old path); deleting it destroys
    # whatever work is in it. Both are worse than stopping. So they are enumerated, named,
    # and left exactly where they are for the operator to retire deliberately.
    $worktreeRoot = Join-Path (Join-Path $RepositoryRoot $EmberInTreeStateDirectoryName) "worktrees"
    if (-not (Test-Path -LiteralPath $worktreeRoot -PathType Container)) { return }
    $resident = @(Get-ChildItem -LiteralPath $worktreeRoot -Force -ErrorAction SilentlyContinue)
    if ($resident.Count -eq 0) {
        Remove-Item -LiteralPath $worktreeRoot -Recurse -Force -ErrorAction SilentlyContinue
        return
    }

    Write-Host ""
    Write-Host "Cockpit-created worktrees are still inside the repository:" -ForegroundColor Yellow
    foreach ($entry in $resident) { Write-Host "  $($entry.FullName)" }
    Write-Host ""
    Write-Host "They are NOT moved or deleted automatically: moving a registered worktree breaks"
    Write-Host "its link to this repository, and deleting one destroys the work inside it. Retire"
    Write-Host "each deliberately, then run tools\launchers\Ember.cmd again:"
    Write-Host ""
    foreach ($entry in $resident) {
        Write-Host "  python src/ember/governance/scripts/worktree_lifecycle.py retire --path `"$($entry.FullName)`""
    }
    Write-Host ""
    throw ("Cockpit state cannot be migrated while $($resident.Count) cockpit-created " +
        "worktree(s) remain inside the repository. Retire them and run tools\launchers\Ember.cmd again.")
}

function Move-EmberStateOutOfTree([string]$RepositoryRoot, [string]$StateRoot) {
    # One-time migration: an in-tree .ember/ from a pre-relocation launch is moved wholesale
    # to $StateRoot and NOTHING is left behind, so the very next census sees a clean tree.
    $inTree = Join-Path $RepositoryRoot $EmberInTreeStateDirectoryName
    if (-not (Test-Path -LiteralPath $inTree -PathType Container)) { return }

    # Registered worktrees are the exception -- refused, never relocated (see above).
    Assert-NoResidentCockpitWorktrees $RepositoryRoot

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
        "writing there, remove that entry, and run tools\launchers\Ember.cmd again.")
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
            throw "This copy of the repository is incomplete. Restore it and run tools\launchers\Ember.cmd again."
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
        $buildOutput = Get-EmberStagedBuildOutfile $applicationRoot
        $buildLog = Join-Path $stateRoot "runtime\ember-build.log"
        New-Item -ItemType Directory -Force -Path $applicationRoot | Out-Null
        # Sweep staged leftovers from a previously crashed build so the resolver can
        # only ever see what THIS build lands.
        foreach ($staleStagedArtifact in @($buildOutput, "$buildOutput.exe")) {
            if (Test-Path -LiteralPath $staleStagedArtifact -PathType Leaf) {
                Remove-Item -LiteralPath $staleStagedArtifact -Force
            }
        }
        try {
            Push-Location $sourceRoot
            try {
                $previousErrorActionPreference = $ErrorActionPreference
                $ErrorActionPreference = "Continue"
                $previousBuildOutfile = $env:EMBER_BUILD_OUTFILE
                $env:EMBER_BUILD_OUTFILE = $buildOutput
                try {
                    # PS5.1 *> writes UTF-16LE; pipe through Out-File so the log is UTF-8.
                    & $bun run build 2>&1 |
                        ForEach-Object { "$_" } |
                        Out-File -LiteralPath $buildLog -Encoding utf8
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
            $stagedArtifact = Resolve-EmberStagedBuildArtifact $buildOutput
            if ($buildExit -ne 0 -or -not $stagedArtifact) {
                $observed = if ($stagedArtifact) { $stagedArtifact } else { "no file at $buildOutput or $buildOutput.exe" }
                throw ("Ember's local application build did not produce a launchable binary. " +
                    "Build exit code: $buildExit. Expected staged artifact: $buildOutput. " +
                    "Observed: $observed. Inspect the build log: $buildLog")
            }
            Move-Item -LiteralPath $stagedArtifact -Destination $application
        }
        finally {
            foreach ($staleStagedArtifact in @($buildOutput, "$buildOutput.exe")) {
                if (Test-Path -LiteralPath $staleStagedArtifact -PathType Leaf) {
                    Remove-Item -LiteralPath $staleStagedArtifact -Force
                }
            }
        }
    }
    Assert-EmberStateIsExternal $repositoryRoot

    # Preparation only: compile the existing dispatch authority beside the immutable
    # cockpit build. This script never starts Ember.exe and therefore cannot bypass emberd.
    $labTargetRoot = Join-Path $stateRoot "runtime\ember-lab\$commit"
    $emberLab = Join-Path $labTargetRoot "release\ember-lab.exe"
    if (-not (Test-Path -LiteralPath $emberLab -PathType Leaf)) {
        New-Item -ItemType Directory -Force -Path $labTargetRoot | Out-Null
        $previousCargoTarget = $env:CARGO_TARGET_DIR
        $env:CARGO_TARGET_DIR = $labTargetRoot
        try {
            & cargo build --locked --release --manifest-path (Join-Path $repositoryRoot "runtime\ember-lab\Cargo.toml")
            if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $emberLab -PathType Leaf)) {
                throw "The governed Ember Lab runtime could not be built."
            }
        }
        finally {
            $env:CARGO_TARGET_DIR = $previousCargoTarget
        }
    }
    Write-Output ("EMBER_APPLICATION=" + [System.IO.Path]::GetFullPath($application))
    Write-Output ("EMBER_LAB=" + [System.IO.Path]::GetFullPath($emberLab))
    Write-Output ("EMBER_SOURCE_COMMIT=" + $commit)
    Write-Output ("EMBER_STATE_ROOT=" + [System.IO.Path]::GetFullPath($stateRoot))
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
