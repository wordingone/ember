// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// tools/computer-use-ps.ts -- the PowerShell 5.1 / .NET payload behind the
// Computer tool. Pure ASCII on purpose (PowerShell 5.1 reads a BOM-less script
// file as ANSI). No backticks and no template placeholders inside: it is a
// String.raw literal. Reads EMBER_CU_ACTION / EMBER_CU_ARGS (JSON) from the
// environment and prints exactly one JSON object as the last stdout line.
//
// Non-intrusive primitives only: EnumWindows, PrintWindow(PW_RENDERFULLCONTENT),
// UI Automation patterns, PostMessage(WM_CLOSE). The only real-input code
// (type_text / click_at via SendInput) is reachable solely when the TS side has
// passed the EMBER_COMPUTER_REAL_INPUT gate.

export const COMPUTER_USE_PS_SCRIPT = String.raw`
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes, System.Drawing
Add-Type -TypeDefinition @"
using System;
using System.Text;
using System.Collections.Generic;
using System.Runtime.InteropServices;
public static class CuNative {
  public delegate bool EnumProc(IntPtr h, IntPtr l);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
  [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)] public struct STARTUPINFO {
    public int cb; public string lpReserved; public string lpDesktop; public string lpTitle;
    public int dwX, dwY, dwXSize, dwYSize, dwXCountChars, dwYCountChars, dwFillAttribute, dwFlags;
    public short wShowWindow, cbReserved2; public IntPtr lpReserved2, hStdInput, hStdOutput, hStdError; }
  [StructLayout(LayoutKind.Sequential)] public struct PROCESS_INFORMATION {
    public IntPtr hProcess, hThread; public int dwProcessId, dwThreadId; }
  [StructLayout(LayoutKind.Sequential)] public struct INPUT { public uint type; public INPUTUNION u; }
  [StructLayout(LayoutKind.Explicit)] public struct INPUTUNION {
    [FieldOffset(0)] public MOUSEINPUT mi; [FieldOffset(0)] public KEYBDINPUT ki; }
  [StructLayout(LayoutKind.Sequential)] public struct MOUSEINPUT {
    public int dx, dy; public uint mouseData, dwFlags, time; public IntPtr dwExtraInfo; }
  [StructLayout(LayoutKind.Sequential)] public struct KEYBDINPUT {
    public ushort wVk, wScan; public uint dwFlags, time; public IntPtr dwExtraInfo; }
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc p, IntPtr l);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern int GetWindowTextLength(IntPtr h);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
  [DllImport("user32.dll")] public static extern bool IsWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr hdc, uint flags);
  [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h, uint msg, IntPtr w, IntPtr l);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern IntPtr GetWindow(IntPtr h, uint cmd);
  [DllImport("user32.dll")] public static extern int GetSystemMetrics(int i);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll", SetLastError=true)] public static extern uint SendInput(uint n, INPUT[] inputs, int size);
  [DllImport("dwmapi.dll")] public static extern int DwmGetWindowAttribute(IntPtr h, int a, out int v, int sz);
  [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
  public static extern bool CreateProcessW(string app, StringBuilder cmd, IntPtr pa, IntPtr ta, bool inherit,
    uint flags, IntPtr env, string cwd, ref STARTUPINFO si, out PROCESS_INFORMATION pi);
  [DllImport("kernel32.dll")] public static extern bool CloseHandle(IntPtr h);
  public static List<IntPtr> TopLevel() {
    var l = new List<IntPtr>();
    EnumWindows(delegate(IntPtr h, IntPtr p) { l.Add(h); return true; }, IntPtr.Zero);
    return l;
  }
  public static string Title(IntPtr h) {
    int n = GetWindowTextLength(h);
    if (n <= 0) return "";
    var sb = new StringBuilder(n + 2);
    GetWindowText(h, sb, sb.Capacity);
    return sb.ToString();
  }
  public static bool Cloaked(IntPtr h) {
    int v = 0;
    try { DwmGetWindowAttribute(h, 14, out v, 4); } catch { return false; }
    return v != 0;
  }
  // Launch with SW_SHOWMINNOACTIVE so the new window does not take the foreground.
  public static int Launch(string cmdline, string cwd, short show) {
    var si = new STARTUPINFO(); si.cb = System.Runtime.InteropServices.Marshal.SizeOf(si);
    si.dwFlags = 1; si.wShowWindow = show;
    PROCESS_INFORMATION pi;
    var sb = new StringBuilder(cmdline);
    if (!CreateProcessW(null, sb, IntPtr.Zero, IntPtr.Zero, false, 0, IntPtr.Zero,
        string.IsNullOrEmpty(cwd) ? null : cwd, ref si, out pi)) return -Marshal.GetLastWin32Error();
    CloseHandle(pi.hProcess); CloseHandle(pi.hThread);
    return pi.dwProcessId;
  }
  public static uint SendUnicode(string text) {
    var list = new List<INPUT>();
    foreach (char c in text) {
      for (int up = 0; up < 2; up++) {
        var i = new INPUT(); i.type = 1; i.u.ki.wScan = c; i.u.ki.dwFlags = 4u | (up == 1 ? 2u : 0u);
        list.Add(i);
      }
    }
    return SendInput((uint)list.Count, list.ToArray(), System.Runtime.InteropServices.Marshal.SizeOf(typeof(INPUT)));
  }
  public static uint Click(int x, int y, bool right) {
    SetCursorPos(x, y);
    uint down = right ? 0x8u : 0x2u, upf = right ? 0x10u : 0x4u;
    var a = new INPUT[2];
    a[0].type = 0; a[0].u.mi.dwFlags = down; a[1].type = 0; a[1].u.mi.dwFlags = upf;
    return SendInput(2, a, System.Runtime.InteropServices.Marshal.SizeOf(typeof(INPUT)));
  }
}
"@
[void][CuNative]::SetProcessDPIAware()

$A = $env:EMBER_CU_ARGS | ConvertFrom-Json
$Action = $env:EMBER_CU_ACTION
Add-Type -AssemblyName UIAutomationClient

function Fail($kind, $msg) { throw ('CUERR|' + $kind + '|' + $msg) }
function Has($name) { return ($null -ne $A.PSObject.Properties[$name]) -and ($null -ne $A.$name) -and ("$($A.$name)" -ne '') }
function Emit($obj) { [Console]::Out.WriteLine(($obj | ConvertTo-Json -Depth 8 -Compress)) }

function Proc-Of($h) {
  $procId = [uint32]0
  [void][CuNative]::GetWindowThreadProcessId($h, [ref]$procId)
  $pname = ''
  try { $pname = [System.Diagnostics.Process]::GetProcessById([int]$procId).ProcessName } catch {}
  return @{ pid = [int]$procId; name = $pname }
}

function Win-Info($h) {
  $r = New-Object CuNative+RECT
  [void][CuNative]::GetWindowRect($h, [ref]$r)
  $p = Proc-Of $h
  return [ordered]@{
    hwnd = [int64]$h; title = [CuNative]::Title($h); process = $p.name; pid = $p.pid
    bounds = @($r.L, $r.T, ($r.R - $r.L), ($r.B - $r.T))
    visible = [bool][CuNative]::IsWindowVisible($h); minimized = [bool][CuNative]::IsIconic($h)
    cloaked = [bool][CuNative]::Cloaked($h)
  }
}

function All-Windows($includeHidden) {
  $out = @()
  foreach ($h in [CuNative]::TopLevel()) {
    $t = [CuNative]::Title($h)
    if ($t -eq '') { continue }
    $vis = [CuNative]::IsWindowVisible($h)
    if (-not $includeHidden) {
      if (-not $vis) { continue }
      if ([CuNative]::Cloaked($h)) { continue }
    }
    $out += , (Win-Info $h)
  }
  return $out
}

function Resolve-Window {
  if (Has 'hwnd') {
    $h = [IntPtr][int64]$A.hwnd
    if (-not [CuNative]::IsWindow($h)) { Fail 'window_gone' ('Window hwnd ' + $A.hwnd + ' no longer exists. Call list_windows for current windows.') }
    return $h
  }
  if (Has 'window') {
    $needle = "$($A.window)".ToLower()
    $m = @(All-Windows $false | Where-Object { $_.title.ToLower().Contains($needle) })
    if ($m.Count -eq 0) {
      $titles = (All-Windows $false | ForEach-Object { '"' + $_.title + '"' }) -join ', '
      Fail 'window_not_found' ('No visible window title contains "' + $A.window + '". Open windows: ' + $titles)
    }
    if ($m.Count -gt 1) {
      $titles = ($m | ForEach-Object { '' + $_.hwnd + ' "' + $_.title + '"' }) -join '; '
      Fail 'window_ambiguous' ('Several windows match "' + $A.window + '": ' + $titles + '. Pass hwnd.')
    }
    return [IntPtr][int64]$m[0].hwnd
  }
  Fail 'bad_args' 'This action needs hwnd (or window = a title substring).'
}

# ---------------- UI Automation helpers ----------------
Add-Type -AssemblyName UIAutomationTypes
$UIA = [System.Windows.Automation.AutomationElement]
$TS = [System.Windows.Automation.TreeScope]

function Ctype($el) { return ($el.Current.ControlType.ProgrammaticName -replace '^ControlType\.', '') }
function Cached-Type($el) { return ($el.Cached.ControlType.ProgrammaticName -replace '^ControlType\.', '') }

function Pattern-Names($el) {
  $n = @()
  try { foreach ($p in $el.GetSupportedPatterns()) { $n += ($p.ProgrammaticName -replace 'PatternIdentifiers\.Pattern$', '' -replace 'Identifiers\.Pattern$', '') } } catch {}
  return $n
}

function Get-Pat($el, $pat) {
  $o = $null
  if ($el.TryGetCurrentPattern($pat, [ref]$o)) { return $o }
  return $null
}

function Elem-Value($el, $max) {
  $v = $null
  $vp = Get-Pat $el ([System.Windows.Automation.ValuePattern]::Pattern)
  if ($null -ne $vp) { try { $v = $vp.Current.Value } catch {} }
  if ($null -eq $v) {
    $tp = Get-Pat $el ([System.Windows.Automation.TextPattern]::Pattern)
    if ($null -ne $tp) { try { $v = $tp.DocumentRange.GetText($max + 1) } catch {} }
  }
  if ($null -eq $v) { return $null }
  if ($v.Length -gt $max) { $v = $v.Substring(0, $max) + '...' }
  return ($v -replace "\r\n", '\n' -replace "\n", '\n' -replace "\r", '\n')
}

function Fmt-El($el, $depth) {
  $c = $el.Current
  $r = $c.BoundingRectangle
  $b = if ($r.IsEmpty -or [double]::IsInfinity($r.X)) { 'offscreen' } else { ('' + [int]$r.X + ',' + [int]$r.Y + ',' + [int]$r.Width + ',' + [int]$r.Height) }
  $s = (' ' * ($depth * 2)) + (Ctype $el)
  if ($c.Name -ne '') { $s += ' "' + ($c.Name -replace '"', "'") + '"' }
  if ($c.AutomationId -ne '') { $s += ' #' + $c.AutomationId }
  $s += ' [' + $b + ']'
  if (-not $c.IsEnabled) { $s += ' disabled' }
  $pn = Pattern-Names $el
  if ($pn.Count -gt 0) { $s += ' patterns=' + ($pn -join ',') }
  $val = Elem-Value $el 300
  if ($null -ne $val -and $val -ne '') { $s += ' value="' + ($val -replace '"', "'") + '"' }
  return $s
}

function Seg-Parse($seg) {
  $seg = $seg.Trim()
  $o = @{ aid = $null; name = $null; type = $null }
  if ($seg.StartsWith('#')) { $o.aid = $seg.Substring(1); return $o }
  if ($seg -match '^([A-Za-z]+):(.*)$') {
    $o.type = $Matches[1]; $rest = $Matches[2].Trim()
    if ($rest.StartsWith('#')) { $o.aid = $rest.Substring(1) } elseif ($rest -ne '') { $o.name = $rest }
    return $o
  }
  $o.name = $seg
  return $o
}

function Close-Matches($pool, $want, $max) {
  $w = "$want".ToLower()
  $toks = @($w -split '[^a-z0-9]+' | Where-Object { $_ -ne '' })
  $scored = @()
  foreach ($e in $pool) {
    $n = $e.Cached.Name; $aid = $e.Cached.AutomationId
    $hay = ($n + ' ' + $aid).ToLower()
    $sc = 0
    if ($w -ne '' -and ($hay.Contains($w) -or ($n -ne '' -and $w.Contains($n.ToLower())))) { $sc += 3 }
    foreach ($t in $toks) { if ($hay.Contains($t)) { $sc += 1 } }
    if ($sc -gt 0) { $scored += , @($sc, $e) }
  }
  $top = @($scored | Sort-Object { - $_[0] } | Select-Object -First $max)
  return @($top | ForEach-Object {
    $e = $_[1]
    $t = Cached-Type $e
    $x = $t
    if ($e.Cached.Name -ne '') { $x += ' "' + $e.Cached.Name + '"' }
    if ($e.Cached.AutomationId -ne '') { $x += ' #' + $e.Cached.AutomationId }
    $x
  })
}

function Find-Element($root) {
  $cr = New-Object System.Windows.Automation.CacheRequest
  $cr.Add($UIA::NameProperty); $cr.Add($UIA::AutomationIdProperty); $cr.Add($UIA::ControlTypeProperty); $cr.Add($UIA::IsEnabledProperty)
  $segs = @()
  if (Has 'element') { $segs = @("$($A.element)" -split '\s*>\s*' | Where-Object { $_ -ne '' } | ForEach-Object { Seg-Parse $_ }) }
  elseif ((Has 'automation_id') -or (Has 'name') -or (Has 'control_type')) {
    $o = @{ aid = $null; name = $null; type = $null }
    if (Has 'automation_id') { $o.aid = "$($A.automation_id)" }
    if (Has 'name') { $o.name = "$($A.name)" }
    if (Has 'control_type') { $o.type = "$($A.control_type)" }
    $segs = @($o)
  } else {
    if ($script:Kind -eq 'set_value') {
      $vp = New-Object System.Windows.Automation.PropertyCondition($UIA::IsValuePatternAvailableProperty, $true)
      $ty = New-Object System.Windows.Automation.OrCondition((New-Object System.Windows.Automation.PropertyCondition($UIA::ControlTypeProperty, [System.Windows.Automation.ControlType]::Document)), (New-Object System.Windows.Automation.PropertyCondition($UIA::ControlTypeProperty, [System.Windows.Automation.ControlType]::Edit)))
      $f = $root.FindFirst($TS::Descendants, (New-Object System.Windows.Automation.AndCondition($vp, $ty)))
      if ($null -ne $f) { return $f }
    }
    Fail 'bad_args' 'This action needs element (e.g. "#TextBox" or "Edit:Text editor" or "Pane > Button:Save"), or automation_id / name / control_type.'
  }
  $scope = $root
  $want = ''
  for ($i = 0; $i -lt $segs.Count; $i++) {
    $sg = $segs[$i]
    $want = if ($sg.aid) { $sg.aid } elseif ($sg.name) { $sg.name } else { $sg.type }
    $cr.Activate() | Out-Null
    try { $pool = $scope.FindAll($TS::Descendants, [System.Windows.Automation.Condition]::TrueCondition) } finally { $cr.Pop() }
    $cand = @()
    foreach ($e in $pool) {
      if ($sg.type -and ((Cached-Type $e).ToLower() -ne $sg.type.ToLower())) { continue }
      if ($sg.aid -and ($e.Cached.AutomationId -ne $sg.aid)) { continue }
      $cand += $e
    }
    if ($sg.name) {
      $nl = $sg.name.ToLower()
      $exact = @($cand | Where-Object { $_.Cached.Name.ToLower() -eq $nl })
      if ($exact.Count -gt 0) { $cand = $exact }
      else {
        $part = @($cand | Where-Object { $_.Cached.Name.ToLower().Contains($nl) })
        if ($part.Count -eq 1 -or ($part.Count -gt 1 -and $i -lt ($segs.Count - 1))) { $cand = $part } else { $cand = @() }
      }
    }
    if ($cand.Count -eq 0) {
      $near = @(Close-Matches $pool $want 8)
      $msg = 'Element not found: segment "' + $want + '" (of "' + (($segs | ForEach-Object { if ($_.aid) { '#' + $_.aid } elseif ($_.name) { $_.name } else { $_.type } }) -join ' > ') + '").'
      if ($near.Count -gt 0) { $msg += ' Close matches: ' + ($near -join ' | ') } else { $msg += ' No similar elements; call ui_tree to see what is there.' }
      Fail 'element_not_found' $msg
    }
    $idx = 0
    if ($i -eq ($segs.Count - 1) -and (Has 'index')) { $idx = [int]$A.index }
    if ($idx -ge $cand.Count) { Fail 'element_not_found' ('index ' + $idx + ' out of range; ' + $cand.Count + ' elements matched "' + $want + '".') }
    $scope = $cand[$idx]
  }
  return $scope
}

function Need-Pattern($el, $pat, $label) {
  $p = Get-Pat $el $pat
  if ($null -eq $p) {
    $have = (Pattern-Names $el) -join ','
    $msg = 'Element does not support ' + $label + '. Its patterns: ' + $(if ($have) { $have } else { '(none)' }) + '.'
    try {
      $prop = $UIA::('Is' + $label + 'AvailableProperty')
      $cond = New-Object System.Windows.Automation.PropertyCondition($prop, $true)
      $alts = @($script:RootEl.FindAll($TS::Descendants, $cond) | Select-Object -First 6 | ForEach-Object {
        $x = Ctype $_
        if ($_.Current.Name -ne '') { $x += ' "' + $_.Current.Name + '"' }
        if ($_.Current.AutomationId -ne '') { $x += ' #' + $_.Current.AutomationId }
        $x })
      if ($alts.Count -gt 0) { $msg += ' Elements in this window that DO support it: ' + ($alts -join ' | ') + '. Use ControlType:Name to target one (e.g. Document:Text editor).' }
    } catch {}
    Fail 'pattern_unsupported' $msg
  }
  return $p
}

# ---------------- actions ----------------
function Do-Screenshot {
  $maxW = 1280
  if (Has 'max_width') { $maxW = [Math]::Min(1280, [int]$A.max_width) }
  $target = 'screen'
  $h = [IntPtr]::Zero
  if ((Has 'hwnd') -or (Has 'window')) { $h = Resolve-Window; $target = 'window' }
  $note = $null
  if ($target -eq 'window') {
    $r = New-Object CuNative+RECT
    [void][CuNative]::GetWindowRect($h, [ref]$r)
    $w = $r.R - $r.L; $ht = $r.B - $r.T
    if ([CuNative]::IsIconic($h)) { $note = 'window is minimized; the image may be blank. Restore it (not done automatically) or use ui_tree.' }
    if ($w -le 0 -or $ht -le 0) { Fail 'bad_window' 'Window has an empty rectangle (minimized or hidden).' }
    $bmp = New-Object System.Drawing.Bitmap $w, $ht, ([System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $hdc = $g.GetHdc()
    $ok = [CuNative]::PrintWindow($h, $hdc, 2)
    $g.ReleaseHdc($hdc); $g.Dispose()
    if (-not $ok) { Fail 'printwindow_failed' 'PrintWindow returned false for this window.' }
  } else {
    $w = [CuNative]::GetSystemMetrics(0); $ht = [CuNative]::GetSystemMetrics(1)
    $bmp = New-Object System.Drawing.Bitmap $w, $ht, ([System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.CopyFromScreen(0, 0, 0, 0, (New-Object System.Drawing.Size $w, $ht))
    $g.Dispose()
  }
  $outW = $w; $outH = $ht
  if ($w -gt $maxW) {
    $outW = $maxW; $outH = [int][Math]::Round($ht * ($maxW / $w))
    $small = New-Object System.Drawing.Bitmap $outW, $outH, ([System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
    $g2 = [System.Drawing.Graphics]::FromImage($small)
    $g2.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $g2.DrawImage($bmp, 0, 0, $outW, $outH)
    $g2.Dispose(); $bmp.Dispose(); $bmp = $small
  }
  $dir = Split-Path -Parent $A.save_path
  if (-not (Test-Path $dir)) { [void](New-Item -ItemType Directory -Force -Path $dir) }
  $bmp.Save($A.save_path, [System.Drawing.Imaging.ImageFormat]::Png)
  $bmp.Dispose()
  $res = [ordered]@{ ok = $true; target = $target; path = $A.save_path; width = $outW; height = $outH; original_width = $w; original_height = $ht }
  if ($note) { $res.note = $note }
  if ($target -eq 'window') { $res.window = Win-Info $h }
  Emit $res
}

function Do-UiTree {
  $h = Resolve-Window
  $root = $UIA::FromHandle($h)
  $maxDepth = 6; $maxNodes = 150
  if (Has 'depth') { $maxDepth = [Math]::Min(12, [int]$A.depth) }
  if (Has 'max_nodes') { $maxNodes = [Math]::Min(600, [int]$A.max_nodes) }
  $walker = [System.Windows.Automation.TreeWalker]::ControlViewWalker
  $lines = New-Object System.Collections.ArrayList
  $state = @{ n = 0; cut = 0 }
  function Walk($el, $d) {
    if ($state.n -ge $maxNodes) { $state.cut++; return }
    [void]$lines.Add((Fmt-El $el $d)); $state.n++
    if ($d -ge $maxDepth) {
      $k = $walker.GetFirstChild($el); if ($null -ne $k) { [void]$lines.Add(((' ' * (($d + 1) * 2)) + '... (depth cap; pass element-rooted ui_tree or larger depth)')) }
      return
    }
    $c = $walker.GetFirstChild($el)
    while ($null -ne $c) { Walk $c ($d + 1); $c = $walker.GetNextSibling($c) }
  }
  $startEl = $root
  if ((Has 'element') -or (Has 'automation_id') -or (Has 'name')) { $startEl = Find-Element $root }
  Walk $startEl 0
  $NL = [string][char]10
  $txt = ($lines -join $NL)
  if ($state.cut -gt 0) { $txt += $NL + '... (node cap ' + $maxNodes + ' reached; ' + $state.cut + '+ more elements not shown; raise max_nodes or target a sub-element)' }
  Emit ([ordered]@{ ok = $true; window = (Win-Info $h); nodes = $state.n; tree = $txt })
}

function Assert-Owned($h, $allowSameProcess) {
  $owned = @(); if ($null -ne $A.owned) { $owned = @($A.owned | ForEach-Object { [int64]$_ }) }
  $ok = $owned -contains [int64]$h
  if (-not $ok) {
    $own = [CuNative]::GetWindow($h, 4)
    if ($own -ne [IntPtr]::Zero -and ($owned -contains [int64]$own)) { $ok = $true }
  }
  if (-not $ok -and $allowSameProcess -and $null -ne $A.owned_pids) {
    $pids = @($A.owned_pids | ForEach-Object { [int]$_ })
    $pp = Proc-Of $h
    if ($pp.name -ne 'ApplicationFrameHost' -and ($pids -contains [int]$pp.pid)) { $ok = $true }
  }
  if (-not $ok) { Fail 'not_owned' ('Refusing to act on this window: it was not opened by the Computer tool in this session (or is not a dialog/window of a program it opened). ' + $Action + ' only changes windows that open_app opened; list_windows, ui_tree and screenshot work on any window.') }
}

function Do-Uia($kind) {
  $h = Resolve-Window
  Assert-Owned $h $true
  $root = $UIA::FromHandle($h)
  $script:RootEl = $root
  $script:Kind = $kind
  $el = Find-Element $root
  $desc = (Ctype $el) + ' "' + $el.Current.Name + '"'
  if (-not $el.Current.IsEnabled) { Fail 'element_disabled' ($desc + ' is disabled.') }
  switch ($kind) {
    'invoke' {
      $p = Get-Pat $el ([System.Windows.Automation.InvokePattern]::Pattern)
      if ($null -ne $p) { $p.Invoke(); Emit ([ordered]@{ ok = $true; message = ('Invoked ' + $desc) }); return }
      $p = Get-Pat $el ([System.Windows.Automation.SelectionItemPattern]::Pattern)
      if ($null -ne $p) { $p.Select(); Emit ([ordered]@{ ok = $true; message = ('Selected ' + $desc + ' (no InvokePattern)') }); return }
      [void](Need-Pattern $el ([System.Windows.Automation.InvokePattern]::Pattern) 'InvokePattern')
    }
    'set_value' {
      if (($null -eq $A.PSObject.Properties['value'] -or $null -eq $A.value) -and -not (Has 'text')) { Fail 'bad_args' 'set_value needs value (the new text).' }
      $v = if ($null -ne $A.PSObject.Properties['value'] -and $null -ne $A.value) { "$($A.value)" } else { "$($A.text)" }
      $p = Need-Pattern $el ([System.Windows.Automation.ValuePattern]::Pattern) 'ValuePattern'
      if ($p.Current.IsReadOnly) { Fail 'read_only' ($desc + ' is read-only.') }
      $p.SetValue($v)
      $back = Elem-Value $el 200
      Emit ([ordered]@{ ok = $true; message = ('Set value of ' + $desc); value_now = $back })
    }
    'toggle' {
      $p = Need-Pattern $el ([System.Windows.Automation.TogglePattern]::Pattern) 'TogglePattern'
      $want = $null
      if (Has 'state') { $want = "$($A.state)".ToLower() }
      $n = 0
      while ($n -lt 3) {
        $cur = "$($p.Current.ToggleState)".ToLower()
        if ($null -eq $want -and $n -ge 1) { break }
        if ($null -ne $want -and ($cur -eq $want -or ($want -eq 'true' -and $cur -eq 'on') -or ($want -eq 'false' -and $cur -eq 'off'))) { break }
        $p.Toggle(); $n++
      }
      Emit ([ordered]@{ ok = $true; message = ('Toggled ' + $desc); state = "$($p.Current.ToggleState)" })
    }
    'select' {
      $p = Get-Pat $el ([System.Windows.Automation.SelectionItemPattern]::Pattern)
      if ($null -ne $p) { $p.Select(); Emit ([ordered]@{ ok = $true; message = ('Selected ' + $desc) }); return }
      $vp = Get-Pat $el ([System.Windows.Automation.ValuePattern]::Pattern)
      if ($null -ne $vp -and (Has 'value')) { $vp.SetValue("$($A.value)"); Emit ([ordered]@{ ok = $true; message = ('Set ' + $desc + ' to the given value') }); return }
      [void](Need-Pattern $el ([System.Windows.Automation.SelectionItemPattern]::Pattern) 'SelectionItemPattern')
    }
    'expand' {
      $p = Need-Pattern $el ([System.Windows.Automation.ExpandCollapsePattern]::Pattern) 'ExpandCollapsePattern'
      if ((Has 'state') -and "$($A.state)".ToLower().StartsWith('collapse')) { $p.Collapse() } else { $p.Expand() }
      Emit ([ordered]@{ ok = $true; message = ('Now ' + $p.Current.ExpandCollapseState + ': ' + $desc) })
    }
    'scroll' {
      $dir = 'down'; if (Has 'direction') { $dir = "$($A.direction)".ToLower() }
      $amt = 1; if (Has 'amount') { $amt = [Math]::Max(1, [Math]::Min(50, [int]$A.amount)) }
      $p = Get-Pat $el ([System.Windows.Automation.ScrollPattern]::Pattern)
      if ($null -eq $p) {
        $si = Get-Pat $el ([System.Windows.Automation.ScrollItemPattern]::Pattern)
        if ($null -ne $si) { $si.ScrollIntoView(); Emit ([ordered]@{ ok = $true; message = ('Scrolled ' + $desc + ' into view') }); return }
        [void](Need-Pattern $el ([System.Windows.Automation.ScrollPattern]::Pattern) 'ScrollPattern')
      }
      $SA = [System.Windows.Automation.ScrollAmount]
      $none = $SA::NoAmount
      for ($i = 0; $i -lt $amt; $i++) {
        switch ($dir) {
          'down'  { $p.Scroll($none, $SA::LargeIncrement) }
          'up'    { $p.Scroll($none, $SA::LargeDecrement) }
          'right' { $p.Scroll($SA::LargeIncrement, $none) }
          'left'  { $p.Scroll($SA::LargeDecrement, $none) }
          default { Fail 'bad_args' 'direction must be up, down, left or right.' }
        }
      }
      Emit ([ordered]@{ ok = $true; message = ('Scrolled ' + $dir + ' x' + $amt + ': ' + $desc); vertical_percent = $p.Current.VerticalScrollPercent })
    }
  }
}

function Do-OpenApp {
  if (-not (Has 'exe')) { Fail 'bad_args' 'open_app needs exe (e.g. "notepad").' }
  $exe = "$($A.exe)"
  $before = @{}
  foreach ($h in [CuNative]::TopLevel()) { $before[[int64]$h] = $true }
  $fg0 = [CuNative]::GetForegroundWindow()
  $cmd = $exe
  if ($exe -match '[\\/]' -or $exe -match '\s') { $cmd = '"' + $exe + '"' }
  if (Has 'args') { $cmd += ' ' + $A.args }
  $cwd = $null; if (Has 'cwd') { $cwd = "$($A.cwd)" }
  $launchPid = [CuNative]::Launch($cmd, $cwd, 7)
  $viaShell = $false
  if ($launchPid -le 0) {
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $exe; if (Has 'args') { $psi.Arguments = "$($A.args)" }
    $psi.UseShellExecute = $true; $psi.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Minimized
    $pr = [System.Diagnostics.Process]::Start($psi)
    $launchPid = if ($null -ne $pr) { $pr.Id } else { 0 }
    $viaShell = $true
  }
  $base = [System.IO.Path]::GetFileNameWithoutExtension($exe).ToLower()
  $timeout = 10000; if (Has 'wait_ms') { $timeout = [Math]::Min(30000, [int]$A.wait_ms) }
  $sw = [System.Diagnostics.Stopwatch]::StartNew()
  $found = $null
  $uwpAlias = @{ 'calc' = 'calculator'; 'calculator' = 'calculator'; 'ms-settings' = 'settings' }
  while ($sw.ElapsedMilliseconds -lt $timeout -and $null -eq $found) {
    $cands = @()
    $afh = @()
    foreach ($h in [CuNative]::TopLevel()) {
      if ($before.ContainsKey([int64]$h)) { continue }
      if ([CuNative]::Title($h) -eq '') { continue }
      if (-not [CuNative]::IsWindowVisible($h) -and -not [CuNative]::IsIconic($h)) { continue }
      if ([CuNative]::Cloaked($h)) { continue }
      $p = Proc-Of $h
      $score = 0
      if ($p.pid -eq $launchPid) { $score = 2 } elseif ($p.name.ToLower() -eq $base) { $score = 1 }
      elseif ($p.name -eq 'ApplicationFrameHost') {
        # UWP apps (Calculator, Settings...) are framed by ApplicationFrameHost, never by the launched pid.
        $tl = [CuNative]::Title($h).ToLower()
        $names = @($base); if ($uwpAlias.ContainsKey($base)) { $names += $uwpAlias[$base] }
        foreach ($n in $names) { if ($n -ne '' -and $tl.Contains($n)) { $score = 1 } }
        if ($score -eq 0) { $afh += , $h }
      }
      if ($score -gt 0) { $cands += , @($score, $h) }
    }
    if ($cands.Count -gt 0) { $found = ($cands | Sort-Object { - $_[0] } | Select-Object -First 1)[1] }
    elseif ($afh.Count -eq 1 -and $sw.ElapsedMilliseconds -gt 3000) { $found = $afh[0] }
    else { Start-Sleep -Milliseconds 150 }
  }
  if ($null -eq $found) {
    Emit ([ordered]@{ ok = $false; kind = 'no_window'; error = ('Started "' + $exe + '" (pid ' + $launchPid + ') but no new top-level window appeared within ' + $timeout + ' ms. It may be a console/background process, or still loading; call list_windows.'); pid = $launchPid })
    return
  }
  if ([CuNative]::IsIconic($found)) { [void][CuNative]::ShowWindow($found, 4) }
  $stole = $false
  for ($k = 0; $k -lt 4; $k++) {
    if ([CuNative]::GetForegroundWindow() -eq $found -and $fg0 -ne [IntPtr]::Zero -and [CuNative]::IsWindow($fg0)) {
      $stole = $true; [void][CuNative]::SetForegroundWindow($fg0)
    }
    Start-Sleep -Milliseconds 120
  }
  $fgRestored = ([CuNative]::GetForegroundWindow() -ne $found)
  $info = Win-Info $found
  Emit ([ordered]@{ ok = $true; launched_pid = $launchPid; via_shell = $viaShell; window = $info; foreground_taken_then_restored = $stole; foreground_restored = $fgRestored })
}

function Do-CloseWindow {
  $h = Resolve-Window
  Assert-Owned $h $false
  $title = [CuNative]::Title($h)
  [void][CuNative]::PostMessage($h, 0x10, [IntPtr]::Zero, [IntPtr]::Zero)
  $sw = [System.Diagnostics.Stopwatch]::StartNew()
  while ($sw.ElapsedMilliseconds -lt 4000 -and [CuNative]::IsWindow($h)) { Start-Sleep -Milliseconds 100 }
  $gone = -not [CuNative]::IsWindow($h)
  $res = [ordered]@{ ok = $true; closed = $gone; hwnd = [int64]$h; title = $title }
  if (-not $gone) {
    $dlg = @()
    foreach ($w in [CuNative]::TopLevel()) {
      if ([CuNative]::GetWindow($w, 4) -eq $h -and [CuNative]::IsWindowVisible($w)) { $dlg += , (Win-Info $w) }
    }
    $res.message = 'WM_CLOSE sent but the window is still open (probably a save/confirm dialog).'
    $res.owned_dialogs = $dlg
  }
  Emit $res
}

function Do-Real($kind) {
  if ($env:EMBER_COMPUTER_REAL_INPUT -ne '1') { Fail 'real_input_disabled' 'Real input is disabled (set EMBER_COMPUTER_REAL_INPUT=1).' }
  if ($kind -eq 'type_text') {
    if ((Has 'hwnd') -or (Has 'window')) { $h = Resolve-Window; [void][CuNative]::SetForegroundWindow($h) ; Start-Sleep -Milliseconds 150 }
    $n = [CuNative]::SendUnicode("$($A.text)")
    Emit ([ordered]@{ ok = $true; message = ('Typed ' + "$($A.text)".Length + ' chars via SendInput'); events = $n })
  } else {
    $n = [CuNative]::Click([int]$A.x, [int]$A.y, ((Has 'button') -and "$($A.button)" -eq 'right'))
    Emit ([ordered]@{ ok = $true; message = ('Clicked at ' + $A.x + ',' + $A.y + ' via SendInput'); events = $n })
  }
}

try {
  switch ($Action) {
    'list_windows' { Emit ([ordered]@{ ok = $true; windows = @(All-Windows ([bool]$A.include_hidden)) }) }
    'screenshot' { Do-Screenshot }
    'ui_tree' { Do-UiTree }
    'invoke' { Do-Uia 'invoke' }
    'set_value' { Do-Uia 'set_value' }
    'toggle' { Do-Uia 'toggle' }
    'select' { Do-Uia 'select' }
    'expand' { Do-Uia 'expand' }
    'scroll' { Do-Uia 'scroll' }
    'open_app' { Do-OpenApp }
    'close_window' { Do-CloseWindow }
    'type_text' { Do-Real 'type_text' }
    'click_at' { Do-Real 'click_at' }
    default { Fail 'bad_args' ('Unknown action ' + $Action) }
  }
} catch {
  $m = $_.Exception.Message
  if ($m -like 'CUERR|*') {
    $parts = $m.Split('|', 3)
    Emit ([ordered]@{ ok = $false; kind = $parts[1]; error = $parts[2] })
  } else {
    Emit ([ordered]@{ ok = $false; kind = 'powershell_exception'; error = $m; at = ($_.InvocationInfo.PositionMessage) })
  }
}
`;
