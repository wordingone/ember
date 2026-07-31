# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$BunVersion = "1.3.12"
$BunArchiveUrl = "https://github.com/oven-sh/bun/releases/download/bun-v1.3.12/bun-windows-x64.zip"
$BunArchiveSha256 = "841ff9c5dffcaa3a2620d1e3f87ee500f32a4ca830b001cade7a3479609d4a89"
$EmberLauncherMutexName = "Local\EmberCliCanonicalLauncher"

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

function Test-IsOwnedEmberExecutablePath([string]$Candidate, [string]$RepositoryRoot) {
    if ([string]::IsNullOrWhiteSpace($Candidate)) { return $false }
    try {
        $ownedRoot = [System.IO.Path]::GetFullPath((Join-Path $RepositoryRoot ".ember\runtime\ember"))
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

function Stop-StaleOwnedEmberApplications([string]$RepositoryRoot) {
    $stale = @(Get-CimInstance Win32_Process -Filter "Name='Ember.exe'" -ErrorAction Stop |
        Where-Object {
            $_.ProcessId -ne $PID -and
            (Test-IsOwnedEmberExecutablePath ([string]$_.ExecutablePath) $RepositoryRoot)
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

function Stop-EmberLaunch([string]$Message) {
    Write-Host ""
    Write-Host "Ember could not prepare its runtime." -ForegroundColor Red
    Write-Host $Message
    exit 1
}

function Get-VerifiedBun([string]$RepositoryRoot) {
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

    $runtimeParent = Join-Path $RepositoryRoot ".ember\runtime"
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

    $bun = Get-VerifiedBun $repositoryRoot
    $dependenciesReady = Test-Path -LiteralPath (Join-Path $sourceRoot "node_modules\react\package.json") -PathType Leaf
    if (-not $dependenciesReady) {
        Write-Host "Preparing Ember's interface dependencies once..."
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
            throw "Ember CLI exited with code $exitCode."
        }
        return
    }

    $launcherLease = Enter-EmberLauncherLease
    Stop-StaleOwnedEmberApplications $repositoryRoot

    $commit = (& git -C $repositoryRoot rev-parse HEAD 2>$null | Select-Object -First 1).Trim()
    if ($commit -notmatch "^[0-9a-f]{40}$") {
        throw "This repository does not have an exact Git source identity."
    }
    $applicationRoot = Join-Path $repositoryRoot ".ember\runtime\ember\$commit"
    $application = Join-Path $applicationRoot "Ember.exe"
    if (-not (Test-Path -LiteralPath $application -PathType Leaf)) {
        $buildOutput = Join-Path $sourceRoot "ember.exe"
        $buildLog = Join-Path $repositoryRoot ".ember\runtime\ember-build.log"
        New-Item -ItemType Directory -Force -Path $applicationRoot | Out-Null
        try {
            Push-Location $sourceRoot
            try {
                $previousErrorActionPreference = $ErrorActionPreference
                $ErrorActionPreference = "Continue"
                try {
                    & $bun run build *> $buildLog
                }
                finally {
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

    $windowHandle = Get-EmberHostWindowHandle
    Set-EmberWindowToLeftWorkArea $windowHandle | Out-Null

    # Invoke in this shell: no second terminal or dead launcher window may remain underneath.
    & $application
    if ($LASTEXITCODE -ne 0) {
        throw "Ember CLI exited with code $LASTEXITCODE."
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
