# launch-resident.ps1 — teardown-first ember-resident launch (NCK-VIS spec v1)
# Closes all WT tabs + kills python process before opening exactly one new tab.
# No stacking, no duplicates.
param(
    [string]$Config = "config/nck-c10.json",
    [string]$EmberDir = "<local-path>",
    [int]$PlaceX = 1720,
    [int]$PlaceY = 0
)

$ErrorActionPreference = "Stop"
$KillReceipts = "<local-path>"

function Append-KillReceipt($pids_arr, $rule, $survivors) {
    $ts = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    $pidJson = ($pids_arr | ForEach-Object { [string]$_ }) -join ","
    $line = "{`"ts`":`"$ts`",`"script`":`"launch-resident.ps1`",`"pids`":[$pidJson],`"match_rule`":`"$rule`",`"survivors_expected`":`"$survivors`"}"
    Add-Content $KillReceipts $line
}

Add-Type @"
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
public class WtWin {
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc cb, IntPtr lp);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr hWnd, int msg, IntPtr wParam, IntPtr lParam);
    [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr h, IntPtr after, int x, int y, int w, int ht, uint flags);
    public delegate bool EnumWindowsProc(IntPtr h, IntPtr lp);
    public const int WM_CLOSE = 0x0010;
    public const uint SWP_NOSIZE = 0x0001;
    public const uint SWP_NOZORDER = 0x0004;
    public static List<long> FindByTitle(string match) {
        var r = new List<long>();
        EnumWindows((h, lp) => {
            if (!IsWindowVisible(h)) return true;
            var sb = new StringBuilder(256);
            GetWindowText(h, sb, 256);
            if (sb.ToString().Contains(match)) r.Add(h.ToInt64());
            return true;
        }, IntPtr.Zero);
        return r;
    }
    public static void CloseWindow(long hwnd) { PostMessage((IntPtr)hwnd, WM_CLOSE, IntPtr.Zero, IntPtr.Zero); }
    public static void MoveWindow(long hwnd, int x, int y) {
        SetWindowPos((IntPtr)hwnd, IntPtr.Zero, x, y, 0, 0, SWP_NOSIZE | SWP_NOZORDER);
    }
}
"@

# ── 1. Kill all running c10_resident.py python processes ─────────────────────
$existing = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match "c10_resident" })
if ($existing.Count -gt 0) {
    $pids = $existing | ForEach-Object { $_.ProcessId }
    Append-KillReceipt $pids "python.exe CommandLine contains c10_resident" "other python processes unaffected"
    $existing | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Write-Host "Killed $($existing.Count) c10_resident process(es): $($pids -join ', ')"
} else {
    Write-Host "No existing c10_resident processes found."
}

# ── 2. Wait for processes to fully die (WT shows dead-process, no confirm dialog) ──
Start-Sleep -Seconds 2

# ── 3. Close all WT windows/tabs titled 'ember-resident' (retry loop) ────────
$maxTries = 5
for ($try = 1; $try -le $maxTries; $try++) {
    $wtWins = [WtWin]::FindByTitle("ember-resident")
    if ($wtWins.Count -eq 0) { Write-Host "All ember-resident WT windows closed."; break }
    foreach ($hwnd in $wtWins) {
        [WtWin]::CloseWindow($hwnd) | Out-Null
        Write-Host "Sent WM_CLOSE to HWND=$hwnd (try $try)"
    }
    Start-Sleep -Seconds 2
}
$remaining = [WtWin]::FindByTitle("ember-resident")
if ($remaining.Count -gt 0) {
    Write-Host "WARNING: $($remaining.Count) ember-resident window(s) still open after $maxTries tries."
}

# ── 4. Open exactly one new WT window titled 'ember-resident' ────────────────
$wt = "$env:LOCALAPPDATA\Microsoft\WindowsApps\wt.exe"
if (-not (Test-Path $wt)) {
    $wtCmd = Get-Command wt -ErrorAction SilentlyContinue
    if ($wtCmd) { $wt = $wtCmd.Source } else { Write-Error "wt.exe not found"; exit 1 }
}

# --window new forces a new window even if WT is in single-instance mode
$wtArgs = "--window new --title ember-resident --suppressApplicationTitle -d `"$EmberDir`" python scripts/nck/c10_resident.py --config $Config"
Start-Process -FilePath $wt -ArgumentList $wtArgs
Write-Host "Launched ember-resident (new WT window)."

# ── 5. Wait for new window to appear, then place it ─────────────────────────
Start-Sleep -Seconds 3
$newWins = [WtWin]::FindByTitle("ember-resident")
if ($newWins.Count -eq 1) {
    [WtWin]::MoveWindow($newWins[0], $PlaceX, $PlaceY) | Out-Null
    Write-Host "Placed ember-resident at ($PlaceX,$PlaceY)."
} elseif ($newWins.Count -eq 0) {
    Write-Host "WARNING: ember-resident window not found after launch — placement skipped."
} else {
    Write-Host "WARNING: $($newWins.Count) ember-resident windows found — placement skipped (ambiguous)."
}
