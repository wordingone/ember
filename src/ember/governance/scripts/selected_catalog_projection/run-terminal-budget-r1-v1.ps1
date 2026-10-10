$ErrorActionPreference='Stop'
if(@($args).Count -ne 0){throw 'UNEXPECTED_CONTROLLER_ARGUMENT'}
$root='C:\Users\Admin\.codex\visualizations\2026\10\01\01a0f8e5-f04d-7141-af6f-51c1dac8a822\1581-terminal-budget-r1-fixture-leo75391-20261009T1800Z'
$out=Join-Path $root 'fixture-controller-terminal-v1.json'
$controllerWatch=[Diagnostics.Stopwatch]::StartNew()
if([IO.File]::Exists($out) -or [IO.File]::Exists((Join-Path $root 'boundary-validation-v1.json'))){throw 'FIXTURE_ALREADY_EXECUTED'}
if([long]([IO.DriveInfo]::new('C:\')).AvailableFreeSpace -lt 161061273600){throw 'C_FLOOR_REFUSED'}
. (Join-Path $root 'fixture-boundary-v2.ps1')
$gn='Local\NikoTerminalR1-'+[Guid]::NewGuid().ToString('N')
$gate=[Threading.EventWaitHandle]::new($false,[Threading.EventResetMode]::ManualReset,$gn)
try{
  $result=RunBounded -ArgumentVector @('-NoLogo','-NoProfile','-NonInteractive','-File',(Join-Path $root 'run-fixture-script.ps1'),'-ScriptPath',(Join-Path $root 'validate-terminal-budget-r1-v1.ps1'),'-ArgumentsJson','{}','-GateName',$gn) -WallMilliseconds ([int][Math]::Max(0,90000-$controllerWatch.ElapsedMilliseconds)) -MemoryBytes 536870912 -Gate $gate
}finally{$gate.Dispose()}
if([Text.Encoding]::UTF8.GetByteCount([string]$result.stdout) -gt 131072 -or [Text.Encoding]::UTF8.GetByteCount([string]$result.stderr) -gt 131072){throw 'FIXTURE_CAPTURE_CAP'}
$result.schema='niko.terminal_budget_r1.controller_terminal.v1'
$result.controller_elapsed_seconds=$controllerWatch.Elapsed.TotalSeconds
$result.whole_wall_within90_seconds=($controllerWatch.Elapsed.TotalSeconds -le 90)
$result.status=if($result.exit_code -eq 0 -and $result.cleanup_verified -and $result.active_job_processes -eq 0 -and $result.whole_wall_within90_seconds){'PASS_R1_BOUNDARY_CONTROLLER'}else{'R1_FIXTURE_UNACCEPTED'}
$result.Python=$false;$result.production=$false;$result.automatic_retry=$false
$raw=[Text.UTF8Encoding]::new($false).GetBytes(($result|ConvertTo-Json -Depth 8))
$existing=0L
foreach($p in [IO.Directory]::EnumerateFiles($root,'*',[IO.SearchOption]::AllDirectories)){$existing+=[long]([IO.FileInfo]::new($p)).Length}
if($existing -gt (8388608-$raw.LongLength)){throw 'FIXTURE_TOTAL_CAP'}
[IO.File]::WriteAllBytes($out,$raw)
if((Get-FileHash -LiteralPath $out).Hash.ToLowerInvariant() -ne [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($raw)).ToLowerInvariant()){throw 'CONTROLLER_RECEIPT_READBACK'}
[ordered]@{status=$result.status;terminal=$out;sha256=(Get-FileHash -LiteralPath $out).Hash.ToLowerInvariant();exit_code=$result.exit_code;cleanup_verified=$result.cleanup_verified;active_job_processes=$result.active_job_processes}|ConvertTo-Json -Compress
if($result.status -ne 'PASS_R1_BOUNDARY_CONTROLLER'){exit 1}
