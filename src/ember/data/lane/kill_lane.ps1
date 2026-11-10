# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
# kill_lane.ps1 -Reason "<why>" [-DryRun] [-SpawnFile <path>]
# Lane-only stop (lead 81558). NEVER selects by process name or cmdline pattern alone.
# A process is stoppable only if ALL hold:
#   1. its PID is in the spawn file written by tick.py spawn() (loops/spawn-pids.jsonl: pid, ts, cmd),
#   2. its creation time is within 30 s of the recorded spawn time (PID-reuse guard),
#   3. its current command line contains the recorded command text,
#   4. every python/hf DESCENDANT of it has a command line under $env:EMBER_LANE_ROOT/scripts (or the wrapper's own cmd).
# If any check fails the entry is REFUSED and listed; a foreign python anywhere is only REPORTED, never killed.
# A receipt row (with a note naming the selector) is appended to vigil/kill-receipts.jsonl BEFORE each kill.
param([Parameter(Mandatory=$true)][string]$Reason, [switch]$DryRun, [string[]]$Only = @(), [string]$SpawnFile = (Join-Path $env:EMBER_LANE_ROOT 'loops\spawn-pids.jsonl'), [string]$ReceiptFile = (Join-Path $env:EMBER_M_ROOT 'avir\infra\vigil\kill-receipts.jsonl'))
$Only = @($Only | ForEach-Object { $_ -split ',' } | Where-Object { $_ })   # -File passes a,b,c as ONE string
$laneRe = 'B:[/\\]M[/\\]data-staging[/\\]scripts|data-staging|scripts/[A-Za-z0-9_./-]+\.(py|sh)'
$procs = @(Get-CimInstance Win32_Process)
$byPid = @{}; foreach ($p in $procs) { $byPid[[int]$p.ProcessId] = $p }
function Descendants([int]$root) {
  $out = @(); $q = New-Object System.Collections.Queue; $q.Enqueue($root)
  while ($q.Count) { $cur = $q.Dequeue(); foreach ($p in $procs) { if ([int]$p.ParentProcessId -eq $cur -and [int]$p.ProcessId -ne $cur) { $out += $p; $q.Enqueue([int]$p.ProcessId) } } }
  return $out
}
$stopped = @(); $refused = @(); $handled = @{}
if (Test-Path $SpawnFile) {
  foreach ($line in Get-Content $SpawnFile) {
    if (-not $line.Trim()) { continue }
    try { $e = $line | ConvertFrom-Json } catch { continue }
    if ($Only.Count -and -not (@($Only | Where-Object { ([string]$e.cmd).Contains($_) }).Count)) { continue }   # -Only: stop just the spawn-file entries whose recorded cmd contains one of these substrings (still PID+creation-time+cmd verified)
    $rootPid = [int]$e.pid
    if (-not $byPid.ContainsKey($rootPid)) {
      # wrapper bash already exited (MSYS exec): adopt the ORPHANED python it started, only if its command line contains the recorded command text AND it was created 0-90 s after the recorded spawn AND its parent no longer exists
      $sp = [DateTimeOffset]::FromUnixTimeSeconds([long][math]::Floor([double]$e.ts)).UtcDateTime
      $nd = ([string]$e.cmd) -replace '^python\s+',''
      $cand = @($procs | Where-Object { $_.Name -match '^python' -and ([string]$_.CommandLine).Contains($nd) -and -not $byPid.ContainsKey([int]$_.ParentProcessId) -and (([datetime]$_.CreationDate).ToUniversalTime() - $sp).TotalSeconds -ge -5 -and (([datetime]$_.CreationDate).ToUniversalTime() - $sp).TotalSeconds -le 90 })
      if ($cand.Count -ne 1) { continue }                          # none, or ambiguous: do nothing
      $rootPid = [int]$cand[0].ProcessId
    }
    $p = $byPid[$rootPid]
    $spawnTime = [DateTimeOffset]::FromUnixTimeSeconds([long][math]::Floor([double]$e.ts)).UtcDateTime
    $created = ([datetime]$p.CreationDate).ToUniversalTime()
    if ([math]::Abs(($created - $spawnTime).TotalSeconds) -gt 30) { $refused += "pid ${rootPid}: creation time does not match recorded spawn (PID reuse?)"; continue }
    $cl = [string]$p.CommandLine; $needle = ([string]$e.cmd); if ($needle.Length -gt 60) { $needle = $needle.Substring(0, 60) }
    if (-not $cl.Contains($needle)) { $refused += "pid ${rootPid}: command line does not contain the recorded command"; continue }
    $desc = Descendants $rootPid; $bad = @()
    foreach ($d in $desc) { if ($d.Name -match '^(python|hf)' -and -not ([string]$d.CommandLine -match $laneRe)) { $bad += $d } }
    if ($bad.Count) { $refused += "pid ${rootPid}: has foreign python/hf descendant(s) " + (($bad | ForEach-Object { $_.ProcessId }) -join ','); continue }
    $tree = @($p) + $desc
    foreach ($t in $tree) {
      $row = [ordered]@{ ts=(Get-Date).ToUniversalTime().ToString('o'); seat=$env:EMBER_SEAT_DATA; pid=[int]$t.ProcessId; reason=$Reason; cmdline=(([string]$t.CommandLine) -replace '\s+',' '); cmdline_verified=$true; selector="spawn-pid-file root pid $rootPid (creation-time + cmd verified, no foreign python/hf descendants); not a name pattern"; dry_run=[bool]$DryRun }
      ($row | ConvertTo-Json -Compress) | Add-Content -Path $ReceiptFile -Encoding utf8
    }
    if (-not $DryRun) { taskkill /PID $rootPid /T /F 2>&1 | Out-Null }
    $stopped += "pid $rootPid (+$($desc.Count) descendants)"
    foreach ($t in $tree) { $handled[[int]$t.ProcessId] = 1 }
  }
}
Start-Sleep -Seconds 2
$procs2 = @(Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^(python|hf)' })
"STOPPED (lane, verified by spawn PID): $($stopped.Count)$(if($DryRun){' [dry run, nothing killed]'})"; $stopped | ForEach-Object { "  $_" }
"REFUSED entries: $($refused.Count)"; $refused | ForEach-Object { "  $_" }
"FOREIGN or remaining python/hf (REPORT ONLY, never killed; tell the owner): $($procs2.Count)"
foreach ($q in $procs2) { $c = (([string]$q.CommandLine) -replace '\s+',' '); "  pid $($q.ProcessId): $($c.Substring(0, [Math]::Min(140, $c.Length)))" }
