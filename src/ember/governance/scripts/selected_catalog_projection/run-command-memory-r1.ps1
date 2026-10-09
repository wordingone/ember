$ErrorActionPreference = 'Stop'
if (@($args).Count -ne 0) { throw 'UNEXPECTED_COMMAND_ARGUMENT' }

$runnerPath = 'C:\Users\Admin\.codex\visualizations\2026\10\01\01a0f8e5-f04d-7141-af6f-51c1dac8a822\1581-memory-terminal-r1-leo75391-20261009T1800Z\run_selected_projection_memory_v1.ps1'
$bindingPath = 'C:\Users\Admin\.codex\visualizations\2026\10\01\01a0f8e5-f04d-7141-af6f-51c1dac8a822\1581-memory-terminal-r1-leo75391-20261009T1800Z\binding-memory-r1.json'
$bindingSha256 = '8cd5c9311d7518e74e3b534da4e7aa18e88a4cf62b958fa1e8d6be2906ebbda6'
$maxWallMilliseconds = 900000
$memoryLimitBytes = 536870912
$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSVersion.Major -lt 7) { throw 'POWERSHELL7_REQUIRED' }

# R1: fixed same-path reservation is counted by every existing root scan.
function Get-RootBudgetBytes([string]$Root,[long]$Limit) {
  if($Limit -lt 0){throw 'ROOT_BUDGET_ARGUMENT'}
  $total=0L
  foreach($path in [IO.Directory]::EnumerateFiles($Root,'*',[IO.SearchOption]::AllDirectories)){
    $length=[long]([IO.FileInfo]::new($path)).Length
    if($length -gt ($Limit-$total)){throw 'CAP_OUTPUT_ROOT'}
    $total+=$length
  }
  return $total
}
function Get-PendingTerminalDocument {
  $encoded=[Text.UTF8Encoding]::new($false).GetBytes('{"schema":"niko.selected_catalog_projection.terminal_reservation.v1","status":"RESERVED_PENDING_UNACCEPTED","reserved_bytes":8192,"result_accepted":false}')
  $document=[byte[]]::new(8192)
  [Array]::Fill[byte]($document,32)
  [Array]::Copy($encoded,0,$document,0,$encoded.Length)
  return ,$document
}
function Initialize-LaunchBudgetRecords([string]$Root,[long]$Limit,[string]$PreflightPath,[byte[]]$PreflightBytes,[string]$TerminalPath,[string]$ExpectedReservationSha) {
  if([IO.Path]::GetFullPath($TerminalPath) -ne [IO.Path]::Combine([IO.Path]::GetFullPath($Root),'run-terminal-memory-r1.json')){throw 'TERMINAL_RESERVATION_PATH'}
  if([IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($PreflightPath)) -ne [IO.Path]::GetFullPath($Root)){throw 'PREFLIGHT_BUDGET_PATH'}
  if([IO.File]::Exists($TerminalPath) -or [IO.File]::Exists($PreflightPath)){throw 'LAUNCH_BUDGET_RECORD_EXISTS'}
  $existing=Get-RootBudgetBytes $Root $Limit
  $remaining=$Limit-$existing
  if($remaining -lt 8192 -or $PreflightBytes.LongLength -gt ($remaining-8192)){throw 'CAP_OUTPUT_LAUNCH_RECORDS'}
  $pending=Get-PendingTerminalDocument
  $pendingSha=[Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($pending)).ToLowerInvariant()
  if($pendingSha -ne $ExpectedReservationSha){throw 'TERMINAL_RESERVATION_HASH'}
  $stream=[IO.FileStream]::new($TerminalPath,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None,4096,[IO.FileOptions]::WriteThrough)
  try{$stream.Write($pending,0,$pending.Length);$stream.Flush($true)}finally{$stream.Dispose()}
  $stream=[IO.FileStream]::new($PreflightPath,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::Read,4096,[IO.FileOptions]::WriteThrough)
  try{$stream.Write($PreflightBytes,0,$PreflightBytes.Length);$stream.Flush($true)}finally{$stream.Dispose()}
  if((Get-FileHash -LiteralPath $TerminalPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedReservationSha -or ([IO.FileInfo]::new($TerminalPath)).Length -ne 8192){throw 'TERMINAL_RESERVATION_READBACK'}
  if((Get-FileHash -LiteralPath $PreflightPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($PreflightBytes)).ToLowerInvariant()){throw 'PREFLIGHT_READBACK'}
  [void](Get-RootBudgetBytes $Root $Limit)
}
function Complete-TerminalReservation([string]$Root,[long]$Limit,[string]$TerminalPath,[string]$ExpectedReservationSha,[object]$Record) {
  if([IO.Path]::GetFullPath($TerminalPath) -ne [IO.Path]::Combine([IO.Path]::GetFullPath($Root),'run-terminal-memory-r1.json')){throw 'TERMINAL_RESERVATION_PATH'}
  $before=Get-RootBudgetBytes $Root $Limit
  $encoded=[Text.UTF8Encoding]::new($false).GetBytes(($Record|ConvertTo-Json -Depth 8))
  $degraded=$false
  if($encoded.LongLength -gt 8192){
    # Keep actual outcome/custody fields in a bounded failure terminal, never a success claim.
    $primaryReason=[string]$Record.reason
    $reasonPrefix=if($primaryReason.Length -gt 256){$primaryReason.Substring(0,256)}else{$primaryReason}
    $fallback=[ordered]@{
      schema='niko.selected_catalog_projection.outer_terminal.v1';status='TERMINAL_FAILURE'
      reason='TERMINAL_RECEIPT_TOO_LARGE';outer_exit_code=125
      primary_outer_exit_code=$Record.outer_exit_code;child_exit_code=$Record.child_exit_code
      outer_pid=$Record.outer_pid;child_pid=$Record.child_pid
      start_utc=$Record.start_utc;end_utc=$Record.end_utc;elapsed_seconds=$Record.elapsed_seconds
      cleanup_verified=$Record.cleanup_verified;active_job_processes=$Record.active_job_processes
      primary_reason_prefix=$reasonPrefix;primary_reason_truncated=($primaryReason.Length -gt 256)
      primary_reason_sha256=[Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($primaryReason))).ToLowerInvariant()
      command_sha256=$Record.command_sha256;binding_sha256=$Record.binding_sha256
      terminal_receipt_reserved_bytes=8192;max_output_bytes=$Limit;result_accepted=$false
    }
    $encoded=[Text.UTF8Encoding]::new($false).GetBytes(($fallback|ConvertTo-Json -Depth 8))
    $degraded=$true
  }
  if($encoded.LongLength -gt 8192){throw 'TERMINAL_FALLBACK_TOO_LARGE'}
  $document=[byte[]]::new(8192)
  [Array]::Fill[byte]($document,32)
  [Array]::Copy($encoded,0,$document,0,$encoded.Length)
  $expectedFinalSha=[Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($document)).ToLowerInvariant()
  $stream=[IO.FileStream]::new($TerminalPath,[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None,4096,[IO.FileOptions]::WriteThrough)
  try{
    if($stream.Length -ne 8192){throw 'TERMINAL_RESERVATION_LENGTH'}
    if([Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($stream)).ToLowerInvariant() -ne $ExpectedReservationSha){throw 'TERMINAL_RESERVATION_HASH'}
    $stream.Position=0
    $stream.Write($document,0,$document.Length);$stream.Flush($true)
    $stream.Position=0
    if($stream.Length -ne 8192 -or [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($stream)).ToLowerInvariant() -ne $expectedFinalSha){throw 'TERMINAL_RECEIPT_READBACK'}
  }finally{$stream.Dispose()}
  $after=Get-RootBudgetBytes $Root $Limit
  if($after -ne $before){throw 'TERMINAL_ROOT_OCCUPANCY_CHANGED'}
  return [pscustomobject]@{persisted=$true;degraded=$degraded;encoded_terminal_bytes=$encoded.LongLength;physical_terminal_bytes=8192;sha256=$expectedFinalSha;root_bytes_before=$before;root_bytes_after=$after}
}

function Assert-SingleLine([string]$name,[string]$value) {
  if ([string]::IsNullOrWhiteSpace($value) -or $value -ne $value.Trim() -or $value.Contains("`r") -or $value.Contains("`n")) { throw ('LITERAL_SINGLE_LINE:' + $name) }
}

Assert-SingleLine 'runnerPath' $runnerPath
Assert-SingleLine 'bindingPath' $bindingPath
Assert-SingleLine 'bindingSha256' $bindingSha256
if ($bindingSha256 -notmatch '^[0-9a-fA-F]{64}$') { throw 'BINDING_SHA_FORMAT' }
$runnerPath = [IO.Path]::GetFullPath($runnerPath)
$bindingPath = [IO.Path]::GetFullPath($bindingPath)
$commandPath = [IO.Path]::GetFullPath($PSCommandPath)
Assert-SingleLine 'normalizedRunnerPath' $runnerPath
Assert-SingleLine 'normalizedBindingPath' $bindingPath
Assert-SingleLine 'commandPath' $commandPath
$actualBinding = (Get-FileHash -LiteralPath $bindingPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualBinding -ne $bindingSha256.ToLowerInvariant()) { throw 'BINDING_HASH' }
$binding = Get-Content -LiteralPath $bindingPath -Raw | ConvertFrom-Json
if ([string]$binding.command_path -ne $commandPath -or [string]$binding.runner_path -ne $runnerPath) { throw 'BOUND_PATH_MISMATCH' }
if ((Get-FileHash -LiteralPath $runnerPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne ([string]$binding.runner_sha256).ToLowerInvariant()) { throw 'RUNNER_HASH' }
$commandSha256 = (Get-FileHash -LiteralPath $commandPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($commandSha256 -notmatch '^[0-9a-f]{64}$') { throw 'COMMAND_SHA_FORMAT' }

$productionLimitBytes = 536870912L
$taskRoot = [IO.Path]::GetDirectoryName($commandPath)
$preflightPath = [IO.Path]::GetFullPath([string]$binding.final_launch_gate_path)
$terminalReceiptPath = [IO.Path]::Combine([IO.Path]::GetDirectoryName($preflightPath),'run-terminal-memory-r1.json')
Assert-SingleLine 'preflightPath' $preflightPath
Assert-SingleLine 'terminalReceiptPath' $terminalReceiptPath
if([long]$binding.terminal_receipt_reserved_bytes -ne 8192 -or [string]$binding.terminal_receipt_path -ne $terminalReceiptPath -or [string]$binding.terminal_receipt_reservation_sha256 -notmatch '^[0-9a-f]{64}$'){throw 'TERMINAL_RESERVATION_BINDING'}
if (-not [IO.Directory]::Exists([IO.Path]::GetDirectoryName($preflightPath))) { throw 'PREFLIGHT_PARENT_MISSING' }
if (Test-Path -LiteralPath $preflightPath) { throw 'PREFLIGHT_ALREADY_EXISTS' }
if (Test-Path -LiteralPath $terminalReceiptPath) { throw 'TERMINAL_RECEIPT_ALREADY_EXISTS' }
if (-not [IO.Directory]::Exists([string]$binding.output_root)) { throw 'OUTPUT_ROOT_MISSING' }
$markerParent = [IO.Path]::GetDirectoryName([string]$binding.marker_path)
$markerParentAvailable = Test-Path -LiteralPath $markerParent -PathType Container
$markerPresent = if ($markerParentAvailable) { Test-Path -LiteralPath ([string]$binding.marker_path) } else { $true }
$predictionBytes = $null
$predictionHash = ''
$predictionLength = -1L
$exportLength = -1L
if ($markerParentAvailable -and -not $markerPresent) {
  $predictionBytes = [IO.File]::ReadAllBytes([string]$binding.prediction_path)
  $predictionLength = [long]$predictionBytes.LongLength
  $predictionHash = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($predictionBytes)).ToLowerInvariant()
  $exportLength = [long](Get-Item -LiteralPath ([string]$binding.export_path) -ErrorAction Stop).Length
}
$cFreeBytes = [long]([IO.DriveInfo]::new('C:\')).AvailableFreeSpace
$outputRootBytes = [long]0
foreach ($filePath in [IO.Directory]::EnumerateFiles([string]$binding.output_root,'*',[IO.SearchOption]::AllDirectories)) {
  $outputRootBytes += [long]([IO.FileInfo]::new($filePath)).Length
}
$runDir = Join-Path ([string]$binding.output_root) 'run'
$refusalPath = Join-Path ([string]$binding.output_root) 'run-refusal.json'
$priorRunStateAbsent = -not (Test-Path -LiteralPath $runDir) -and -not (Test-Path -LiteralPath $refusalPath)
$commandText = [IO.File]::ReadAllText($commandPath)
$capLiteralCount = [regex]::Matches($commandText,'(?m)^\$memoryLimitBytes\s*=\s*536870912\s*$').Count
$capAssignmentCount = [regex]::Matches($commandText,'(?m)^\$memoryLimitBytes\s*=').Count
$hasSetCaps = $commandText -match 'SetCaps\(\$job,\[ulong\]\$memoryLimitBytes\)'
$setsProcess = $commandText -match 'ProcessMemoryLimit=new UIntPtr\(bytes\)'
$setsJob = $commandText -match 'JobMemoryLimit=new UIntPtr\(bytes\)'
$hasOverride = ($commandText -match '(?im)^\s*param\s*\(') -or ($commandText -match '\$memoryLimitBytes\s*=\s*\$env:') -or ($commandText -match ('--max-' + 'private-bytes'))
$commandLimitPass = ($capLiteralCount -eq 1) -and ($capAssignmentCount -eq 1) -and $hasSetCaps -and $setsProcess -and $setsJob -and (-not $hasOverride)
$bindingLimitPass = ([long]$binding.max_private_bytes -eq $productionLimitBytes) -and ([long]$binding.process_memory_limit_bytes -eq $productionLimitBytes) -and ([long]$binding.job_memory_limit_bytes -eq $productionLimitBytes) -and ([long]$binding.max_wall_seconds -eq 900)
$sourceHashCurrent = (Get-FileHash -LiteralPath ([string]$binding.source_path) -Algorithm SHA256).Hash.ToLowerInvariant()
$runnerHashCurrent = (Get-FileHash -LiteralPath $runnerPath -Algorithm SHA256).Hash.ToLowerInvariant()
$sourcePinPass = $sourceHashCurrent -eq ([string]$binding.source_sha256).ToLowerInvariant()
$runnerPinPass = $runnerHashCurrent -eq ([string]$binding.runner_sha256).ToLowerInvariant()
$bindingPinPass = $actualBinding -eq $bindingSha256.ToLowerInvariant()
$predictionPass = ($predictionLength -eq [long]$binding.prediction_bytes) -and ($predictionHash -eq ([string]$binding.prediction_sha256).ToLowerInvariant())
$exportLengthPass = $exportLength -eq [long]$binding.owner_reported_export_bytes
$outputRootPass = $outputRootBytes -le [long]$binding.max_output_bytes
$spacePass = $cFreeBytes -ge [long]$binding.min_C_free_bytes
$markerPass = $markerParentAvailable -and (-not $markerPresent)
$rootPass = $priorRunStateAbsent
$runnerSettingsPass = ([string]$binding.priority -eq 'BelowNormal') -and ([int]$binding.compute_parallelism -eq 1)
$checks = [ordered]@{
  marker_parent_available = $markerParentAvailable
  marker_absent = (-not $markerPresent)
  c_free_at_least_minimum = $spacePass
  prediction_size_and_sha_match = $predictionPass
  export_metadata_length_matches = $exportLengthPass
  output_root_under_cap = $outputRootPass
  no_prior_run_or_refusal = $rootPass
  binding_source_runner_command_pins_match = ($bindingPinPass -and $sourcePinPass -and $runnerPinPass)
  process_job_and_private_guard_are_512_mib = $bindingLimitPass
  command_line_carries_512_mib_with_no_override = $commandLimitPass
  wall_limit_900_seconds = ([long]$binding.max_wall_seconds -eq 900)
  priority_below_normal_and_one_compute_thread = $runnerSettingsPass
}
$gateOk = $markerPass -and $spacePass -and $predictionPass -and $exportLengthPass -and $outputRootPass -and $rootPass -and $bindingPinPass -and $sourcePinPass -and $runnerPinPass -and $bindingLimitPass -and $commandLimitPass -and $runnerSettingsPass
$gateDecision = if ($gateOk) { 'GO' } else { 'REFUSE' }
$finalLaunchGate = [ordered]@{
  schema = 'niko.selected_catalog_projection.final_launch_gate.v1'
  decision = $gateDecision
  evaluated_utc = [DateTime]::UtcNow.ToString('o')
  command_sha256 = $commandSha256
  binding_sha256 = $actualBinding
  source_sha256 = $sourceHashCurrent
  runner_sha256 = $runnerHashCurrent
  prediction_bytes = $predictionLength
  prediction_sha256 = $predictionHash
  export_metadata_bytes = $exportLength
  c_free_bytes = $cFreeBytes
  min_C_free_bytes = [long]$binding.min_C_free_bytes
  marker_parent_available = $markerParentAvailable
  marker_present = $markerPresent
  output_root_bytes_before_run = $outputRootBytes
  output_root_max_bytes = [long]$binding.max_output_bytes
  process_memory_limit_bytes = [long]$binding.process_memory_limit_bytes
  job_memory_limit_bytes = [long]$binding.job_memory_limit_bytes
  private_usage_guard_limit_bytes = [long]$binding.max_private_bytes
  max_wall_seconds = [long]$binding.max_wall_seconds
  compute_parallelism = [int]$binding.compute_parallelism
  priority = [string]$binding.priority
  command_line_carries_512_MiB = $commandLimitPass
  override_path_present = $hasOverride
  terminal_receipt_path = $terminalReceiptPath
  checks = $checks
}
$preflightRecord = [ordered]@{
  schema = 'niko.selected_catalog_projection.preflight.v1'
  created_utc = [DateTime]::UtcNow.ToString('o')
  launch_decision = $gateDecision
  command_path = $commandPath
  command_sha256 = $commandSha256
  binding_path = $bindingPath
  binding_sha256 = $actualBinding
  final_launch_gate = $finalLaunchGate
}
$preflightBytes = [Text.UTF8Encoding]::new($false).GetBytes(($preflightRecord | ConvertTo-Json -Depth 12))
Initialize-LaunchBudgetRecords $taskRoot ([long]$binding.max_output_bytes) $preflightPath $preflightBytes $terminalReceiptPath ([string]$binding.terminal_receipt_reservation_sha256)
if (-not $gateOk) { throw ('FINAL_LAUNCH_GATE_REFUSED:' + (($checks.GetEnumerator() | Where-Object { -not $_.Value } | ForEach-Object Key) -join ',')) }
[Console]::Out.WriteLine("FINAL_LAUNCH_GATE=GO command_sha256=$commandSha256 binding_sha256=$actualBinding private_usage_threshold_bytes=$($binding.max_private_bytes) process_limit_bytes=$($binding.process_memory_limit_bytes) job_limit_bytes=$($binding.job_memory_limit_bytes) c_free_bytes=$cFreeBytes output_root_bytes=$outputRootBytes")
[Console]::Out.Flush()
$jobType = Add-Type -PassThru -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class NikoJobBoundary73960 {
    [StructLayout(LayoutKind.Sequential)] public struct BasicLimits { public long PerProcessUserTimeLimit,PerJobUserTimeLimit; public uint LimitFlags; public UIntPtr MinimumWorkingSetSize,MaximumWorkingSetSize; public uint ActiveProcessLimit; public UIntPtr Affinity; public uint PriorityClass,SchedulingClass; }
    [StructLayout(LayoutKind.Sequential)] public struct IoCounters { public ulong ReadOperationCount,WriteOperationCount,OtherOperationCount,ReadTransferCount,WriteTransferCount,OtherTransferCount; }
    [StructLayout(LayoutKind.Sequential)] public struct ExtendedLimits { public BasicLimits Basic; public IoCounters Io; public UIntPtr ProcessMemoryLimit,JobMemoryLimit,PeakProcessMemoryUsed,PeakJobMemoryUsed; }
    [StructLayout(LayoutKind.Sequential)] public struct Accounting { public long TotalUserTime,TotalKernelTime,ThisPeriodTotalUserTime,ThisPeriodTotalKernelTime; public uint TotalPageFaultCount,TotalProcesses,ActiveProcesses,TotalTerminatedProcesses; }
    [DllImport("kernel32.dll",CharSet=CharSet.Unicode,SetLastError=true)] public static extern IntPtr CreateJobObject(IntPtr attributes,string name);
    [DllImport("kernel32.dll",SetLastError=true)] public static extern bool SetInformationJobObject(IntPtr job,int infoClass,ref ExtendedLimits info,uint length);
    [DllImport("kernel32.dll",SetLastError=true)] public static extern bool AssignProcessToJobObject(IntPtr job,IntPtr process);
    [DllImport("kernel32.dll",SetLastError=true)] public static extern bool TerminateJobObject(IntPtr job,uint exitCode);
    [DllImport("kernel32.dll",SetLastError=true)] public static extern bool TerminateProcess(IntPtr process,uint exitCode);
    [DllImport("kernel32.dll",SetLastError=true)] public static extern bool QueryInformationJobObject(IntPtr job,int infoClass,ref Accounting info,uint length,IntPtr returnLength);
    [DllImport("kernel32.dll",SetLastError=true)] public static extern bool CloseHandle(IntPtr handle);
    public static bool SetCaps(IntPtr job,ulong bytes) { ExtendedLimits x=new ExtendedLimits(); x.Basic.LimitFlags=0x100|0x200|0x2000; x.ProcessMemoryLimit=new UIntPtr(bytes); x.JobMemoryLimit=new UIntPtr(bytes); return SetInformationJobObject(job,9,ref x,(uint)Marshal.SizeOf(typeof(ExtendedLimits))); }
    public static uint ActiveProcesses(IntPtr job) { Accounting x=new Accounting(); if(!QueryInformationJobObject(job,1,ref x,(uint)Marshal.SizeOf(typeof(Accounting)),IntPtr.Zero)) return UInt32.MaxValue; return x.ActiveProcesses; }
}
'@
$jobTypes = @($jobType | Where-Object { $_.FullName -eq 'NikoJobBoundary73960' })
if ($jobTypes.Count -ne 1) { throw 'JOB_TYPE_COMPILE_REFUSED' }
$jobType = $jobTypes[0]
$job = $jobType::CreateJobObject([IntPtr]::Zero,$null)
if ($job -eq [IntPtr]::Zero) { throw 'JOB_CREATE_REFUSED' }
if (-not $jobType::SetCaps($job,[ulong]$memoryLimitBytes)) { [void]$jobType::CloseHandle($job); throw 'JOB_LIMIT_SET_REFUSED' }
$gateName = 'Local\NikoSelectedProjection73960_' + [Guid]::NewGuid().ToString('N')
$gate = [Threading.EventWaitHandle]::new($false,[Threading.EventResetMode]::ManualReset,$gateName)
$pwshPath = (Get-Command pwsh.exe -ErrorAction Stop).Source
Assert-SingleLine 'pwshPath' $pwshPath
$psi = [Diagnostics.ProcessStartInfo]::new($pwshPath)
$psi.UseShellExecute = $false
$psi.CreateNoWindow = $true
$psi.WindowStyle = [Diagnostics.ProcessWindowStyle]::Hidden
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError = $true
$psi.Environment['OMP_NUM_THREADS'] = '1'
$psi.Environment['MKL_NUM_THREADS'] = '1'
$psi.Environment['OPENBLAS_NUM_THREADS'] = '1'
$psi.Environment['NUMEXPR_NUM_THREADS'] = '1'
$psi.Environment['ARROW_NUM_THREADS'] = '1'
$psi.Environment['POLARS_MAX_THREADS'] = '1'
foreach ($arg in @('-NoLogo','-NoProfile','-NonInteractive','-File',$runnerPath,'-BindingPath',$bindingPath,'-BindingSha256',$bindingSha256,'-CommandPath',$commandPath,'-CommandSha256',$commandSha256,'-GateName',$gateName)) { [void]$psi.ArgumentList.Add([string]$arg) }

$child = $null
$stdoutTask = $null
$stderrTask = $null
$processStartUtc = ''
$wall = [Diagnostics.Stopwatch]::new()
$parentExit = 125
$reason = 'LAUNCH_NOT_STARTED'
$cleanupVerified = $false
$activeJobProcesses = [uint32]::MaxValue
try {
  $child = [Diagnostics.Process]::Start($psi)
  if ($null -eq $child) { throw 'PROCESS_START_REFUSED' }
  $processStartUtc = [DateTime]::UtcNow.ToString('o')
  $wall.Start()
  [Console]::Out.WriteLine("RUN_START PID=$($child.Id) observed_utc=$processStartUtc command_sha256=$commandSha256")
  [Console]::Out.Flush()
  $stdoutTask = $child.StandardOutput.ReadToEndAsync()
  $stderrTask = $child.StandardError.ReadToEndAsync()
  if (-not $jobType::AssignProcessToJobObject($job,$child.Handle)) { throw 'JOB_ASSIGN_REFUSED' }
  $child.PriorityClass = [Diagnostics.ProcessPriorityClass]::BelowNormal
  if ($child.PriorityClass -ne [Diagnostics.ProcessPriorityClass]::BelowNormal) { throw 'LAUNCH_PRIORITY_REFUSED' }
  [void]$gate.Set()
  $remaining = [int][Math]::Max(0,$maxWallMilliseconds - $wall.ElapsedMilliseconds)
  if (-not $child.WaitForExit($remaining)) {
    $reason = 'WALL_TIMEOUT'
    $parentExit = 124
    [void]$jobType::TerminateProcess($child.Handle,[uint32]124)
    [void]$jobType::TerminateJobObject($job,[uint32]124)
    [void]$child.WaitForExit(10000)
  } else {
    $parentExit = [int]$child.ExitCode
    $reason = if ($parentExit -eq 0) { 'NONE' } else { 'CHILD_EXIT' }
  }
} catch {
  if ($reason -eq 'LAUNCH_NOT_STARTED') { $reason = [string]$_.Exception.Message }
  if ($null -ne $child) {
    $parentExit = 125
    [void]$jobType::TerminateProcess($child.Handle,[uint32]125)
    [void]$jobType::TerminateJobObject($job,[uint32]125)
    [void]$child.WaitForExit(10000)
  }
} finally {
  if ($null -ne $child) {
    $activeJobProcesses = $jobType::ActiveProcesses($job)
    if ($activeJobProcesses -gt 0 -and $activeJobProcesses -ne [uint32]::MaxValue) {
      [void]$jobType::TerminateJobObject($job,[uint32]$parentExit)
      $cleanupWatch = [Diagnostics.Stopwatch]::StartNew()
      do {
        $activeJobProcesses = $jobType::ActiveProcesses($job)
        if ($activeJobProcesses -eq 0) { break }
        Start-Sleep -Milliseconds 100
      } while ($cleanupWatch.ElapsedMilliseconds -lt 10000)
    }
    if (-not $child.HasExited) { [void]$child.WaitForExit(10000) }
    $cleanupVerified = ($child.HasExited -and $activeJobProcesses -eq 0)
    if (-not $cleanupVerified) { [void]$jobType::CloseHandle($job); $job = [IntPtr]::Zero }
    if ($job -ne [IntPtr]::Zero) { [void]$jobType::CloseHandle($job); $job = [IntPtr]::Zero }
    if ($null -ne $stdoutTask) { try { if ($stdoutTask.Wait(10000)) { [Console]::Out.Write($stdoutTask.GetAwaiter().GetResult()) } else { $cleanupVerified = $false; $parentExit = 125; $reason = 'STDOUT_DRAIN_UNVERIFIED' } } catch { $cleanupVerified = $false; $parentExit = 125; $reason = 'STDOUT_DRAIN_UNVERIFIED' } }
    if ($null -ne $stderrTask) { try { if ($stderrTask.Wait(10000)) { [Console]::Error.Write($stderrTask.GetAwaiter().GetResult()) } else { $cleanupVerified = $false; $parentExit = 125; $reason = 'STDERR_DRAIN_UNVERIFIED' } } catch { $cleanupVerified = $false; $parentExit = 125; $reason = 'STDERR_DRAIN_UNVERIFIED' } }
    if (-not $child.HasExited) { $parentExit = 125; if ($reason -eq 'NONE') { $reason = 'CHILD_WAIT_UNVERIFIED' } }
    if (-not $cleanupVerified) { $parentExit = 125; $reason = 'CLEANUP_UNVERIFIED' }
    $terminalRecord = [ordered]@{
      schema = 'niko.selected_catalog_projection.outer_terminal.v1'
      status = if ($parentExit -eq 0 -and $reason -eq 'NONE') { 'CHILD_EXIT_0' } else { 'TERMINAL_FAILURE' }
      outer_pid = $PID
      child_pid = $child.Id
      child_exit_code = if ($child.HasExited) { [int]$child.ExitCode } else { $null }
      outer_exit_code = $parentExit
      reason = $reason
      start_utc = $processStartUtc
      end_utc = [DateTime]::UtcNow.ToString('o')
      elapsed_seconds = $wall.Elapsed.TotalSeconds
      cleanup_verified = $cleanupVerified
      active_job_processes = $activeJobProcesses
      private_usage_threshold_bytes = [long]$binding.max_private_bytes
      process_memory_limit_bytes = [long]$binding.process_memory_limit_bytes
      job_memory_limit_bytes = [long]$binding.job_memory_limit_bytes
      preflight_path = $preflightPath
      preflight_sha256 = (Get-FileHash -LiteralPath $preflightPath -Algorithm SHA256).Hash.ToLowerInvariant()
      command_sha256 = $commandSha256
      binding_sha256 = $actualBinding
      terminal_receipt_path = $terminalReceiptPath
      terminal_receipt_reserved_bytes = 8192
      max_output_bytes = [long]$binding.max_output_bytes
    }
    try {
      $terminalWrite = Complete-TerminalReservation $taskRoot ([long]$binding.max_output_bytes) $terminalReceiptPath ([string]$binding.terminal_receipt_reservation_sha256) $terminalRecord
      $terminalReceiptPersisted = [bool]$terminalWrite.persisted
      if($terminalWrite.degraded){$reason='TERMINAL_RECEIPT_TOO_LARGE';$parentExit=125}
    } catch {
      $terminalReceiptPersisted = $false
      $reason = 'TERMINAL_RECEIPT_WRITE_FAILED'
      $parentExit = 125
    }
    $terminalUtc = [DateTime]::UtcNow.ToString('o')
    [Console]::Out.WriteLine("RUN_TERMINAL PID=$($child.Id) exit=$parentExit reason=$reason elapsed_seconds=$($wall.Elapsed.TotalSeconds) observed_utc=$terminalUtc cleanup_verified=$cleanupVerified active_job_processes=$activeJobProcesses terminal_receipt_persisted=$terminalReceiptPersisted terminal_receipt_path=$terminalReceiptPath")
    [Console]::Out.Flush()
    $child.Dispose()
  } else {
    if ($job -ne [IntPtr]::Zero) { [void]$jobType::CloseHandle($job) }
  }
  if ($null -ne $gate) { $gate.Dispose() }
}
exit $parentExit
