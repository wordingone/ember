param([string]$CandidateSourcePath,[string]$CandidateRunnerPath)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'fixture-boundary.ps1')
$started=[DateTime]::UtcNow.ToString('o');$watch=[Diagnostics.Stopwatch]::StartNew()
$free=[long]([IO.DriveInfo]::new('C:\')).AvailableFreeSpace
if($free -lt 161061273600){throw 'SUITE_C_FLOOR'}
$receiptPath=Join-Path $PSScriptRoot 'memory-suite-validation-v1.json'
if(Test-Path -LiteralPath $receiptPath){throw 'SUITE_ALREADY_EXECUTED'}
$legs=[Collections.Generic.List[object]]::new();$status='REFUSED_NOT_COMPLETE';$errorText=''
function Leg([string]$Name,[string]$Script,$Params,[long]$MemoryBytes=536870912){
  if($watch.Elapsed.TotalSeconds -gt 900){throw 'SUITE_WALL_CAP'}
  if([IO.DriveInfo]::new('C:\').AvailableFreeSpace -lt 161061273600){throw 'SUITE_FRESH_C_FLOOR'}
  $gn='Local\NikoMemoryScript-'+[Guid]::NewGuid().ToString('N');$gate=[Threading.EventWaitHandle]::new($false,[Threading.EventResetMode]::ManualReset,$gn)
  try{
    $left=[int][Math]::Max(1,900000-$watch.ElapsedMilliseconds)
    $x=RunBounded -ArgumentVector @('-NoLogo','-NoProfile','-NonInteractive','-File',(Join-Path $PSScriptRoot 'run-fixture-script.ps1'),'-ScriptPath',$Script,'-ArgumentsJson',(ConvertTo-Json -InputObject $Params -Compress),'-GateName',$gn) -WallMilliseconds $left -MemoryBytes $MemoryBytes -Gate $gate
    $x.name=$Name;$legs.Add($x)
    if($x.exit_code -ne 0 -or -not $x.cleanup_verified -or $x.timed_out){throw ('FIXTURE_LEG_REFUSED:'+ $Name)}
  }finally{$gate.Dispose()}
}
try{
  # This scaffold spawns the real 512 MiB baseline and candidate jobs. Do not cap their sum with the scaffold.
  Leg 'baseline-byte-equality-and-global-duplicate-refusals' (Join-Path $PSScriptRoot 'validate-memory-baseline-v1.ps1') @{CandidateSourcePath=$CandidateSourcePath;CandidateRunnerPath=$CandidateRunnerPath} 0
  Leg 'cap-triggering-snapshot' (Join-Path $PSScriptRoot 'validate-cap-snapshot.ps1') @{SourcePath=$CandidateSourcePath;ReceiptPath=(Join-Path $PSScriptRoot 'cap-snapshot-memory-v1.json')}
  Leg 'private-observer-negative-fixtures' (Join-Path $PSScriptRoot 'prior-validate-privateusage.ps1') @{SourcePath=$CandidateSourcePath;ExpectedSha256=((Get-FileHash -LiteralPath $CandidateSourcePath -Algorithm SHA256).Hash.ToLowerInvariant());ReceiptPath=(Join-Path $PSScriptRoot 'observer-memory-v1.json')}
  $syntheticBinding=Join-Path $PSScriptRoot 'synthetic-memory-successor-validation-v1\candidate-records_before_edges-extra0\binding.json'
  Leg 'prediction-negative-fixtures' (Join-Path $PSScriptRoot 'validate-memory-prediction-v1.ps1') @{BindingPath=$syntheticBinding}
  Leg 'scale-through-final-serialization' (Join-Path $PSScriptRoot 'validate-memory-scale-v1.ps1') @{CandidateSourcePath=$CandidateSourcePath;CandidateRunnerPath=$CandidateRunnerPath} 0
  $scale=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'synthetic-memory-scale-v1\scale-validation.json') -Raw|ConvertFrom-Json
  if($scale.status -ne 'PASS_SCALE_FINAL_SERIALIZATION'){throw 'SCALE_STATUS_REFUSED'}
  $status='PASS_MEMORY_SUCCESSOR_SYNTHETIC_ONLY'
}catch{$errorText=$_.Exception.ToString()}
finally{
  $r=[ordered]@{schema='niko.selected_catalog_projection.memory_suite_validation.v1';status=$status;start_utc=$started;end_utc=[DateTime]::UtcNow.ToString('o');elapsed_seconds=$watch.Elapsed.TotalSeconds;c_free_before_bytes=$free;legs=$legs.ToArray();error=$errorText;source_sha256=((Get-FileHash -LiteralPath $CandidateSourcePath -Algorithm SHA256).Hash.ToLowerInvariant());runner_sha256=((Get-FileHash -LiteralPath $CandidateRunnerPath -Algorithm SHA256).Hash.ToLowerInvariant());automatic_retry=$false;production_executed=$false;admission_proved=$false}
  [IO.File]::WriteAllText($receiptPath,(ConvertTo-Json -InputObject $r -Depth 30),[Text.UTF8Encoding]::new($false))
  Write-Output ('SUITE_RECEIPT='+$receiptPath);Write-Output ('SUITE_RECEIPT_SHA256='+((Get-FileHash -LiteralPath $receiptPath -Algorithm SHA256).Hash.ToLowerInvariant()));Write-Output ('SUITE_STATUS='+$status)
}
if($status -ne 'PASS_MEMORY_SUCCESSOR_SYNTHETIC_ONLY'){exit 1}
