$ErrorActionPreference='Stop'
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
function RunBounded([string[]]$ArgumentVector,[int]$WallMilliseconds=900000,[long]$MemoryBytes=536870912,[Threading.EventWaitHandle]$Gate=$null){
  $job=[NikoJobBoundary73960]::CreateJobObject([IntPtr]::Zero,$null)
  if($job -eq [IntPtr]::Zero){throw 'JOB_CREATE_REFUSED'}
  if($MemoryBytes -gt 0){if(-not [NikoJobBoundary73960]::SetCaps($job,[ulong]$MemoryBytes)){throw 'JOB_SET_REFUSED'}}
  else{$lim=[NikoJobBoundary73960+ExtendedLimits]::new();$lim.Basic.LimitFlags=0x2000;if(-not [NikoJobBoundary73960]::SetInformationJobObject($job,9,[ref]$lim,[uint32][Runtime.InteropServices.Marshal]::SizeOf($lim))){throw 'JOB_KILL_LIMIT_REFUSED'}}
  $psi=[Diagnostics.ProcessStartInfo]::new();$psi.FileName=Join-Path $PSHOME 'pwsh.exe';$psi.UseShellExecute=$false;$psi.CreateNoWindow=$true;$psi.WindowStyle=[Diagnostics.ProcessWindowStyle]::Hidden;$psi.RedirectStandardOutput=$true;$psi.RedirectStandardError=$true;$psi.RedirectStandardInput=$true
  foreach($arg in $ArgumentVector){[void]$psi.ArgumentList.Add($arg)}
  foreach($name in @('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS','NUMEXPR_NUM_THREADS','ARROW_NUM_THREADS','POLARS_MAX_THREADS')){$psi.Environment[$name]='1'}
  $p=[Diagnostics.Process]::new();$p.StartInfo=$psi;$started=[DateTime]::UtcNow.ToString('o');$finished=$false;$assigned=$false;$clean=$false;$peak=$null
  try{
    if(-not $p.Start()){throw 'CHILD_START_REFUSED'};$p.StandardInput.Close();$ot=$p.StandardOutput.ReadToEndAsync();$et=$p.StandardError.ReadToEndAsync()
    if(-not [NikoJobBoundary73960]::AssignProcessToJobObject($job,$p.Handle)){throw 'JOB_ASSIGN_REFUSED'};$assigned=$true
    $p.PriorityClass=[Diagnostics.ProcessPriorityClass]::BelowNormal;if($p.PriorityClass -ne [Diagnostics.ProcessPriorityClass]::BelowNormal){throw 'PRIORITY_REFUSED'}
    if($null -ne $Gate){[void]$Gate.Set()}
    $finished=$p.WaitForExit($WallMilliseconds)
    if(-not $finished){[void][NikoJobBoundary73960]::TerminateJobObject($job,124);[void]$p.WaitForExit(10000)}
    if(-not $p.HasExited){throw 'TEARDOWN_UNCLEAN'}
    if(-not ($ot.Wait(10000) -and $et.Wait(10000))){throw 'STREAM_DRAIN_UNVERIFIED'}
    $active=[NikoJobBoundary73960]::ActiveProcesses($job);$clean=($finished -and $active -eq 0)
    return [ordered]@{exit_code=[int]$p.ExitCode;timed_out=(-not $finished);cleanup_verified=$clean;child_pid=[int]$p.Id;start_utc=$started;end_utc=[DateTime]::UtcNow.ToString('o');stdout=[string]$ot.GetAwaiter().GetResult();stderr=[string]$et.GetAwaiter().GetResult();active_job_processes=$active;process_memory_limit_bytes=$MemoryBytes;job_memory_limit_bytes=$MemoryBytes}
  }finally{
    if($null -ne $p -and $p.Id -gt 0 -and -not $p.HasExited){[void][NikoJobBoundary73960]::TerminateProcess($p.Handle,125);[void][NikoJobBoundary73960]::TerminateJobObject($job,125);[void]$p.WaitForExit(10000)}
    [void][NikoJobBoundary73960]::CloseHandle($job);$p.Dispose()
  }
}
function RunHidden($f){
  $gn='Local\\NikoMemoryFixture-'+[Guid]::NewGuid().ToString('N');$gate=[Threading.EventWaitHandle]::new($false,[Threading.EventResetMode]::ManualReset,$gn)
  try{$x=RunBounded -ArgumentVector @('-NoLogo','-NoProfile','-NonInteractive','-File',$f.runner_path,'-BindingPath',$f.binding_path,'-BindingSha256',$f.binding_sha256,'-CommandPath',$f.command_path,'-CommandSha256',$f.command_sha256,'-GateName',$gn) -Gate $gate
    $x.run_dir=Join-Path $f.case_root 'run';$x.refusal_path=Join-Path $f.case_root 'run-refusal.json';$x.fixture=$f;return $x
  }finally{$gate.Dispose()}
}

