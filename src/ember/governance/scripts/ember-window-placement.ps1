# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

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
