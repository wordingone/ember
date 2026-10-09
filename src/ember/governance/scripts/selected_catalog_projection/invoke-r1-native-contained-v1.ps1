$ErrorActionPreference='Stop'
$root='C:\Users\Admin\.codex\visualizations\2026\10\01\01a0f8e5-f04d-7141-af6f-51c1dac8a822\1581-terminal-budget-r1-fixture-leo75391-20261009T1800Z'
$prod='C:\Users\Admin\.codex\visualizations\2026\10\01\01a0f8e5-f04d-7141-af6f-51c1dac8a822\1581-memory-terminal-r1-leo75391-20261009T1800Z'
$terminalDir=Join-Path $root 'r1-outer-terminal-v1'
if(Test-Path -LiteralPath $terminalDir){throw 'SUITE_TERMINAL_ROOT_EXISTS'}
if([IO.DriveInfo]::new('C:\').AvailableFreeSpace -lt 161061273600){throw 'CONTROLLER_C_FLOOR'}
[void][IO.Directory]::CreateDirectory($terminalDir)
Add-Type -TypeDefinition @'
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
function QuoteArgument([string]$value){
  if($value.Length -eq 0){return '""'}
  if($value -notmatch '[\s"]'){return $value}
  $builder=[Text.StringBuilder]::new();[void]$builder.Append('"');$slashes=0
  foreach($character in $value.ToCharArray()){
    if($character -eq '\'){$slashes++;continue}
    if($character -eq '"'){[void]$builder.Append(('\'*(2*$slashes+1)));[void]$builder.Append('"');$slashes=0;continue}
    if($slashes -gt 0){[void]$builder.Append(('\'*$slashes));$slashes=0};[void]$builder.Append($character)
  }
  if($slashes -gt 0){[void]$builder.Append(('\'*(2*$slashes)))};[void]$builder.Append('"');return $builder.ToString()
}
$gn='Local\NikoMemorySuite-'+[Guid]::NewGuid().ToString('N');$gate=[Threading.EventWaitHandle]::new($false,[Threading.EventResetMode]::ManualReset,$gn)
$job=[NikoJobBoundary73960]::CreateJobObject([IntPtr]::Zero,$null);if($job -eq [IntPtr]::Zero){throw 'CONTROLLER_JOB_CREATE'}
$limits=[NikoJobBoundary73960+ExtendedLimits]::new();$limits.Basic.LimitFlags=0x2000
if(-not [NikoJobBoundary73960]::SetInformationJobObject($job,9,[ref]$limits,[uint32][Runtime.InteropServices.Marshal]::SizeOf($limits))){throw 'CONTROLLER_JOB_KILL_LIMIT'}
$psi=[Diagnostics.ProcessStartInfo]::new();$psi.FileName='C:\Users\Admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\powershell\pwsh.exe'
$psi.WorkingDirectory=$root;$psi.UseShellExecute=$false;$psi.CreateNoWindow=$true;$psi.WindowStyle=[Diagnostics.ProcessWindowStyle]::Hidden;$psi.RedirectStandardInput=$true;$psi.RedirectStandardOutput=$true;$psi.RedirectStandardError=$true
$params=@{}
$argsVector=@('-NoLogo','-NoProfile','-NonInteractive','-File',(Join-Path $root 'run-fixture-script.ps1'),'-ScriptPath',(Join-Path $root 'run-terminal-budget-r1-v1.ps1'),'-ArgumentsJson',(ConvertTo-Json -InputObject $params -Compress),'-GateName',$gn)
$psi.Arguments=(($argsVector|ForEach-Object{QuoteArgument $_}) -join ' ')
$p=[Diagnostics.Process]::new();$p.StartInfo=$psi;$started=[DateTime]::UtcNow.ToString('o');$rc=125;$finished=$false;$stdout='';$stderr='';$active=[uint32]::MaxValue
try{
  if(-not $p.Start()){throw 'CONTROLLER_START_REFUSED'}
  $p.StandardInput.Close();$ot=$p.StandardOutput.ReadToEndAsync();$et=$p.StandardError.ReadToEndAsync()
  if(-not [NikoJobBoundary73960]::AssignProcessToJobObject($job,$p.Handle)){throw 'CONTROLLER_JOB_ASSIGN'}
  $p.PriorityClass=[Diagnostics.ProcessPriorityClass]::BelowNormal
  [void]$gate.Set();[Console]::WriteLine('R1_START PID='+$p.Id+' UTC='+$started);[Console]::Out.Flush()
  $finished=$p.WaitForExit(90000)
  if(-not $finished){[void][NikoJobBoundary73960]::TerminateJobObject($job,124);[void]$p.WaitForExit(10000)}
  if(-not $p.HasExited){throw 'CONTROLLER_UNCLEAN'}
  if(-not ($ot.Wait(10000) -and $et.Wait(10000))){throw 'CONTROLLER_STREAM_DRAIN'}
  $rc=[int]$p.ExitCode;$stdout=[string]$ot.GetAwaiter().GetResult();$stderr=[string]$et.GetAwaiter().GetResult();$active=[NikoJobBoundary73960]::ActiveProcesses($job)
}finally{
  if(-not $p.HasExited){[void][NikoJobBoundary73960]::TerminateProcess($p.Handle,125);[void][NikoJobBoundary73960]::TerminateJobObject($job,125);[void]$p.WaitForExit(10000)}
  if([Text.Encoding]::UTF8.GetByteCount($stdout) -gt 131072 -or [Text.Encoding]::UTF8.GetByteCount($stderr) -gt 131072){throw 'R1_CAPTURE_CAP'}
  $occupied=0L
  foreach($fp in [IO.Directory]::EnumerateFiles($root,'*',[IO.SearchOption]::AllDirectories)){$occupied+=[long]([IO.FileInfo]::new($fp)).Length}
  if($occupied -gt (8388608-[Text.Encoding]::UTF8.GetByteCount($stdout)-[Text.Encoding]::UTF8.GetByteCount($stderr)-65536)){throw 'R1_OUTER_ARTIFACT_CAP'}
  $utf8=[Text.UTF8Encoding]::new($false)
  [IO.File]::WriteAllText((Join-Path $terminalDir 'stdout.txt'),$stdout,$utf8);[IO.File]::WriteAllText((Join-Path $terminalDir 'stderr.txt'),$stderr,$utf8)
  $r=[ordered]@{schema='niko.r1_outer_controller_terminal.v1';start_utc=$started;end_utc=[DateTime]::UtcNow.ToString('o');child_pid=$p.Id;exit_code=$rc;completed_before_90_seconds=$finished;cleanup_verified=($p.HasExited -and $finished -and $active -eq 0);active_job_processes=$active;stdout_path=(Join-Path $terminalDir 'stdout.txt');stderr_path=(Join-Path $terminalDir 'stderr.txt');production_executed=$false;automatic_retry=$false;validation_runtime_read_write_boundary='C only; no Python; each projection child has its own 512MiB process/job cap, scaffold job is kill-on-close only'}
  [IO.File]::WriteAllText((Join-Path $terminalDir 'terminal.json'),(ConvertTo-Json -InputObject $r -Depth 20),$utf8)
  [void][NikoJobBoundary73960]::CloseHandle($job);$gate.Dispose();$p.Dispose()
}
ConvertTo-Json -InputObject $r -Depth 20
if(-not $r.cleanup_verified){exit 125};exit $rc
