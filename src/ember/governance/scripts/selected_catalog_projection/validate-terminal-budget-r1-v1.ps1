$ErrorActionPreference='Stop'
if(@($args).Count -ne 0){throw 'UNEXPECTED_FIXTURE_ARGUMENT'}
$fixtureRoot='C:\Users\Admin\.codex\visualizations\2026\10\01\01a0f8e5-f04d-7141-af6f-51c1dac8a822\1581-terminal-budget-r1-fixture-leo75391-20261009T1800Z'
$productRoot='C:\Users\Admin\.codex\visualizations\2026\10\01\01a0f8e5-f04d-7141-af6f-51c1dac8a822\1581-memory-terminal-r1-leo75391-20261009T1800Z'
$sourcePath=Join-Path $productRoot 'selected_projection_memory_r1.cs'
$commandPath=Join-Path $productRoot 'run-command-memory-r1.ps1'
$legacyCommand='C:\Users\Admin\.codex\visualizations\2026\10\01\01a0f8e5-f04d-7141-af6f-51c1dac8a822\1581-memory-successor-leo75037-20261009T1718Z\run-command-memory-v1.ps1'
$reserveSha='0ace1e1d248552ef7c10eb951d56907c6f4da6f20025ddb1d61d3f8994fa5cb3'
$limit=131072L
$maxFixtureBytes=8388608L
$fixtureStart=[DateTime]::UtcNow.ToString('o')
$watch=[Diagnostics.Stopwatch]::StartNew()
$cFree=[long]([IO.DriveInfo]::new('C:\')).AvailableFreeSpace
if($cFree -lt 161061273600){throw 'C_FLOOR_REFUSED'}
if([Diagnostics.Process]::GetCurrentProcess().PriorityClass -ne [Diagnostics.ProcessPriorityClass]::BelowNormal){throw 'PRIORITY_REFUSED'}
if((Get-FileHash -LiteralPath $sourcePath).Hash.ToLowerInvariant() -ne '43f93066866ad44d9e2ec8fe06888d6d914321a3a18aa969affb5aaa5670a390'){throw 'SOURCE_PIN'}
if((Get-FileHash -LiteralPath $commandPath).Hash.ToLowerInvariant() -ne '4a8629dc5928c110bffbdc2b4b0b02e897a5342832c29712a8eec078390dc702'){throw 'COMMAND_PIN'}
if((Get-FileHash -LiteralPath $legacyCommand).Hash.ToLowerInvariant() -ne 'b55e0f5bd1547c0092766f98e4a3234a6201302d1e1d8a865c1250feb21b464b'){throw 'LEGACY_PIN'}
$initialBytes=0L
foreach($p in [IO.Directory]::EnumerateFiles($fixtureRoot,'*',[IO.SearchOption]::AllDirectories)){$initialBytes+=[long]([IO.FileInfo]::new($p)).Length}
$script:accountedWritesUpper=0L
$assertions=[Collections.Generic.List[object]]::new()
function Account([long]$Bytes){
  if($Bytes -lt 0 -or $Bytes -gt ($maxFixtureBytes-$initialBytes-$script:accountedWritesUpper)){throw 'FIXTURE_WRITE_CAP'}
  $script:accountedWritesUpper+=$Bytes
  if($watch.Elapsed.TotalSeconds -gt 90){throw 'FIXTURE_WALL'}
}
function Assert([string]$Name,[bool]$Pass,[object]$Evidence=$null){
  $assertions.Add([pscustomobject]@{name=$Name;pass=$Pass;evidence=$Evidence})
  if(-not $Pass){throw ('ASSERTION_FAILED:'+ $Name)}
}
function NewCase([string]$Name){
  $root=Join-Path $fixtureRoot $Name
  if([IO.Directory]::Exists($root)){throw ('CASE_EXISTS:'+ $Name)}
  [void][IO.Directory]::CreateDirectory($root)
  return $root
}
function WriteFixture([string]$Path,[byte[]]$Bytes){
  Account $Bytes.LongLength
  $stream=[IO.FileStream]::new($Path,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None,65536,[IO.FileOptions]::WriteThrough)
  try{$stream.Write($Bytes,0,$Bytes.Length);$stream.Flush($true)}finally{$stream.Dispose()}
}
function NewRecord([int]$Exit,[string]$Reason,[string]$Root){
  return [ordered]@{
    schema='niko.selected_catalog_projection.outer_terminal.v1'
    fixture_simulation=$true;status=if($Exit -eq 0){'CHILD_EXIT_0'}else{'TERMINAL_FAILURE'}
    outer_pid=$PID;child_pid=$PID;child_exit_code=$Exit;outer_exit_code=$Exit
    reason=$Reason;start_utc=$fixtureStart;end_utc=[DateTime]::UtcNow.ToString('o')
    elapsed_seconds=$watch.Elapsed.TotalSeconds;cleanup_verified=$true;active_job_processes=0
    private_usage_threshold_bytes=536870912;process_memory_limit_bytes=536870912;job_memory_limit_bytes=536870912
    preflight_path=(Join-Path $Root 'preflight.json');preflight_sha256=('a'*64)
    command_sha256='4a8629dc5928c110bffbdc2b4b0b02e897a5342832c29712a8eec078390dc702'
    binding_sha256='8cd5c9311d7518e74e3b534da4e7aa18e88a4cf62b958fa1e8d6be2906ebbda6'
    terminal_receipt_path=(Join-Path $Root 'run-terminal-memory-r1.json')
    terminal_receipt_reserved_bytes=8192;max_output_bytes=$limit;result_accepted=$false
  }
}
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($commandPath,[ref]$tokens,[ref]$errors)
if(@($errors).Count -ne 0){throw 'PRODUCT_COMMAND_PARSE'}
$names=@('Get-RootBudgetBytes','Get-PendingTerminalDocument','Initialize-LaunchBudgetRecords','Complete-TerminalReservation')
$definitions=[Collections.Generic.List[string]]::new()
foreach($name in $names){
  $nodes=@($ast.FindAll({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name},$true))
  if($nodes.Count -ne 1){throw ('PRODUCT_FUNCTION_COUNT:'+ $name)}
  $definitions.Add($nodes[0].Extent.Text)
}
. ([scriptblock]::Create(($definitions -join [Environment]::NewLine)))
Add-Type -Path $sourcePath
$runnerType=[NikoSelectedProjection.Runner]
$allFlags=[Reflection.BindingFlags]'Public,NonPublic,Instance,Static'
$bindingType=$runnerType.GetNestedType('Binding',$allFlags)
$budgetType=$runnerType.GetNestedType('OutputBudget',$allFlags)
$outputType=$runnerType.GetNestedType('BoundedOutput',$allFlags)
$verify=$runnerType.GetMethod('VerifyTerminalReservation',$allFlags)
$runtime=$runnerType.GetMethod('RuntimePhase',$allFlags)
$private=$runnerType.GetMethods($allFlags)|Where-Object{$_.Name -eq 'ObservePrivateUsage' -and $_.GetParameters().Count -eq 0}
$stageField=$runnerType.GetField('StagingRoot',$allFlags)
if($null -eq $verify -or $null -eq $bindingType -or $null -eq $stageField){throw 'SOURCE_R1_METHODS'}
function NewBinding([string]$Root){
  $b=[Activator]::CreateInstance($bindingType,$true)
  $b.output_root=$Root;$b.max_output_bytes=$limit;$b.max_wall_seconds=90
  $b.max_private_bytes=536870912;$b.max_total_bytes_read=0;$b.min_C_free_bytes=161061273600
  $b.marker_path=Join-Path $fixtureRoot 'no-marker.fixture'
  $b.terminal_receipt_path=Join-Path $Root 'run-terminal-memory-r1.json'
  $b.terminal_receipt_reserved_bytes=8192;$b.terminal_receipt_reservation_sha256=$reserveSha
  return $b
}
function SourceVerify($Binding){[void]$verify.Invoke($null,[object[]]@($Binding))}
function Refusal([scriptblock]$Action,[string]$Expected){
  $observed=''
  try{& $Action}catch{
    $cursor=$_.Exception
    while($null -ne $cursor.InnerException){$cursor=$cursor.InnerException}
    $observed=[string]$cursor.Message
  }
  if($observed -ne $Expected){throw ('EXPECTED_REFUSAL:'+ $Expected +':OBSERVED:'+ $observed)}
  return $observed
}
function InitCase([string]$Root,[byte[]]$Preflight,[long]$PayloadRoom){
  $fill=$limit-8192-$Preflight.LongLength-$PayloadRoom
  if($fill -lt 0){throw 'CASE_FILL'}
  WriteFixture (Join-Path $Root 'retained-evidence.bin') ([byte[]]::new([int]$fill))
  Account (8192+$Preflight.LongLength)
  Initialize-LaunchBudgetRecords $Root $limit (Join-Path $Root 'preflight.json') $Preflight (Join-Path $Root 'run-terminal-memory-r1.json') $reserveSha
}
# Establish actual child JobObject/GC runtime and successful PrivateUsage observations.
$probeRoot=NewCase 'runtime-probe'
$probeBinding=NewBinding $probeRoot
[void]$runtime.Invoke($null,[object[]]@('r1_fixture_start',$probeBinding))
$privateStart=[long]$private.Invoke($null,@())
Assert 'actual_private_start_under512' ($privateStart -le 536870912) $privateStart
# RED: execute the predecessor's actual two-line terminal write at a full tiny root.
$redRoot=NewCase 'legacy-red'
WriteFixture (Join-Path $redRoot 'retained-output.bin') ([byte[]]::new([int]$limit))
$terminalRecord=NewRecord 0 'NONE' $redRoot
$terminalReceiptPath=Join-Path $redRoot 'run-terminal-memory-r1.json'
$legacyText=[IO.File]::ReadAllText($legacyCommand)
$legacyPattern='(?m)^      \$terminalJson = \$terminalRecord \| ConvertTo-Json -Depth 8\n      \[IO.File\]::WriteAllText\(\$terminalReceiptPath,\$terminalJson,\[Text.UTF8Encoding\]::new\(\$false\)\)'
$legacyMatch=[regex]::Match($legacyText,$legacyPattern)
if(-not $legacyMatch.Success){throw 'LEGACY_TERMINAL_BLOCK_UNHELD'}
$redBytes=[Text.Encoding]::UTF8.GetByteCount(($terminalRecord|ConvertTo-Json -Depth 8))
Account $redBytes
. ([scriptblock]::Create($legacyMatch.Value))
$redOccupancy=0L
foreach($p in [IO.Directory]::EnumerateFiles($redRoot,'*',[IO.SearchOption]::AllDirectories)){$redOccupancy+=[long]([IO.FileInfo]::new($p)).Length}
Assert 'legacy_terminal_overruns_full_root_expected_red' ($redOccupancy -eq ($limit+$redBytes) -and $redBytes -gt 0) ([ordered]@{root_limit=$limit;root_bytes=$redOccupancy;terminal_bytes=$redBytes;production=$false})
# Preflight AND reservation cannot exceed the cap; one-byte insufficient space writes neither.
$preflight=[Text.Encoding]::UTF8.GetBytes('{"fixture":"r1","status":"GO"}')
$denyRoot=NewCase 'prelaunch-one-byte-short'
WriteFixture (Join-Path $denyRoot 'retained-evidence.bin') ([byte[]]::new([int]($limit-8192-$preflight.Length+1)))
Account (8192+$preflight.Length)
$denied=Refusal {Initialize-LaunchBudgetRecords $denyRoot $limit (Join-Path $denyRoot 'preflight.json') $preflight (Join-Path $denyRoot 'run-terminal-memory-r1.json') $reserveSha} 'CAP_OUTPUT_LAUNCH_RECORDS'
Assert 'prelaunch_checked_both_before_either_write' (-not [IO.File]::Exists((Join-Path $denyRoot 'preflight.json')) -and -not [IO.File]::Exists((Join-Path $denyRoot 'run-terminal-memory-r1.json'))) $denied
# A prelaunch failure/crash leaves explicitly pending/unaccepted evidence.
$pendingRoot=NewCase 'prelaunch-pending'
InitCase $pendingRoot $preflight 0
SourceVerify (NewBinding $pendingRoot)
$pendingRecord=Get-Content -Raw -LiteralPath (Join-Path $pendingRoot 'run-terminal-memory-r1.json')|ConvertFrom-Json
Assert 'pending_remains_unaccepted_before_child' ($pendingRecord.status -eq 'RESERVED_PENDING_UNACCEPTED' -and $pendingRecord.result_accepted -eq $false) $pendingRecord.status
# GREEN success/refusal: exercise the actual source budget writer and same-path terminal finalizer.
foreach($case in @([pscustomobject]@{name='source-success';room=64;exit=0;reason='NONE'},[pscustomobject]@{name='source-refusal-staging';room=32;exit=1;reason='CAP_OUTPUT'})){
  $root=NewCase $case.name
  InitCase $root $preflight $case.room
  $b=NewBinding $root
  SourceVerify $b
  $stage=Join-Path $root 'staging-unaccepted';[void][IO.Directory]::CreateDirectory($stage);$stageField.SetValue($null,$stage)
  $budget=[Activator]::CreateInstance($budgetType,$true)
  $budget.B=$b;$budget.Watch=[Diagnostics.Stopwatch]::StartNew();$budget.InputBytes=0
  $budget.BaseBytes=Get-RootBudgetBytes $root $limit;$budget.WrittenBytes=0
  $constructor=$outputType.GetConstructor($allFlags,$null,[type[]]@($budgetType,[string]),$null)
  $output=$constructor.Invoke([object[]]@($budget,'boundary-output.bin'))
  try{
    Account $case.room
    $payload=[byte[]]::new([int]$case.room)
    $output.Write($payload,0,$payload.Length)
    if($case.exit -ne 0){
      $priorLength=$output.Length;Account 1
      $over=Refusal {$output.Write([byte[]]@(1),0,1)} 'CAP_OUTPUT'
      Assert 'source_one_byte_beyond_capacity_refuses_before_write' ($output.Length -eq $priorLength) $over
    }
    $outputType.GetMethod('Finish',$allFlags).Invoke($output,@())|Out-Null
  }finally{$output.Dispose()}
  Assert ($case.name+'_source_root_exact_cap') ((Get-RootBudgetBytes $root $limit) -eq $limit) $limit
  SourceVerify $b
  if($case.exit -eq 0){[IO.Directory]::Move($stage,(Join-Path $root 'run'))}
  else{Assert 'source_refusal_keeps_staging_unaccepted' ([IO.Directory]::Exists($stage) -and -not [IO.Directory]::Exists((Join-Path $root 'run'))) $stage}
  $record=NewRecord $case.exit $case.reason $root
  Account 8192
  $final=Complete-TerminalReservation $root $limit (Join-Path $root 'run-terminal-memory-r1.json') $reserveSha $record
  $actual=Get-Content -Raw -LiteralPath (Join-Path $root 'run-terminal-memory-r1.json')|ConvertFrom-Json
  Assert ($case.name+'_terminal_truthful_exit') ($actual.child_exit_code -eq $case.exit -and $actual.outer_exit_code -eq $case.exit -and $actual.reason -eq $case.reason) $actual.status
  Assert ($case.name+'_same_path_no_growth_final_hash_verified') ($final.persisted -and -not $final.degraded -and $final.root_bytes_before -eq $limit -and $final.root_bytes_after -eq $limit -and $final.physical_terminal_bytes -eq 8192 -and $final.encoded_terminal_bytes -le 8192) $final
}
# Missing, truncated and tampered reservation all refuse before source promotion.
foreach($variant in @('missing','truncated','tampered')){
  $root=NewCase ('reserve-'+$variant);$b=NewBinding $root
  $pending=Get-PendingTerminalDocument
  if($variant -eq 'truncated'){WriteFixture $b.terminal_receipt_path $pending[0..8190]}
  elseif($variant -eq 'tampered'){$pending[0]=0;WriteFixture $b.terminal_receipt_path $pending}
  $stage=Join-Path $root 'staging-unaccepted';[void][IO.Directory]::CreateDirectory($stage)
  $expected=if($variant -eq 'tampered'){'TERMINAL_RESERVATION_HASH'}else{'TERMINAL_RESERVATION_LENGTH'}
  $refusal=Refusal {SourceVerify $b} $expected
  Assert ('source_'+$variant+'_reserve_refused_staging_retained') ([IO.Directory]::Exists($stage) -and -not [IO.Directory]::Exists((Join-Path $root 'run'))) $refusal
}
# Oversized terminal becomes a bounded truthful failure with its primary outcome retained.
$largeRoot=NewCase 'oversized-terminal'
InitCase $largeRoot $preflight 0
$largeRecord=NewRecord 0 ('unbounded-reason-'*2048) $largeRoot
Account 8192
$largeFinal=Complete-TerminalReservation $largeRoot $limit (Join-Path $largeRoot 'run-terminal-memory-r1.json') $reserveSha $largeRecord
$largeActual=Get-Content -Raw -LiteralPath (Join-Path $largeRoot 'run-terminal-memory-r1.json')|ConvertFrom-Json
Assert 'oversized_terminal_is_truthful_failure_not_success' ($largeFinal.persisted -and $largeFinal.degraded -and $largeActual.status -eq 'TERMINAL_FAILURE' -and $largeActual.outer_exit_code -eq 125 -and $largeActual.primary_outer_exit_code -eq 0 -and $largeActual.result_accepted -eq $false -and $largeActual.primary_reason_truncated) $largeActual.reason
Assert 'oversized_terminal_remains_within_reserved_root' ($largeFinal.root_bytes_before -eq $limit -and $largeFinal.root_bytes_after -eq $limit -and $largeFinal.encoded_terminal_bytes -le 8192) $largeFinal
# Parent refuses a tampered reservation without writing an invented terminal.
$tamperRoot=NewCase 'parent-tampered-reserve'
InitCase $tamperRoot $preflight 0
$tamperPath=Join-Path $tamperRoot 'run-terminal-memory-r1.json'
$stream=[IO.FileStream]::new($tamperPath,[IO.FileMode]::Open,[IO.FileAccess]::Write,[IO.FileShare]::None)
try{Account 1;$stream.WriteByte(0);$stream.Flush($true)}finally{$stream.Dispose()}
$tamperBefore=(Get-FileHash -LiteralPath $tamperPath).Hash.ToLowerInvariant()
$rec=NewRecord 1 'CHILD_EXIT' $tamperRoot;Account 8192
$parentRefused=Refusal {Complete-TerminalReservation $tamperRoot $limit $tamperPath $reserveSha $rec} 'TERMINAL_RESERVATION_HASH'
Assert 'parent_tamper_refusal_no_terminal_rewrite' ((Get-FileHash -LiteralPath $tamperPath).Hash.ToLowerInvariant() -eq $tamperBefore) $parentRefused
# Physical write-sharing failure preserves the pending marker and never reports persisted success.
$shareRoot=NewCase 'parent-sharing-refusal'
InitCase $shareRoot $preflight 0
$sharePath=Join-Path $shareRoot 'run-terminal-memory-r1.json'
$held=[IO.FileStream]::new($sharePath,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
$shareRefused=$false
try{Account 8192;try{[void](Complete-TerminalReservation $shareRoot $limit $sharePath $reserveSha (NewRecord 1 'CHILD_EXIT' $shareRoot))}catch{$shareRefused=$true}}finally{$held.Dispose()}
$sharePending=Get-Content -Raw -LiteralPath $sharePath|ConvertFrom-Json
Assert 'sharing_failure_preserves_truthful_pending_not_persisted' ($shareRefused -and $sharePending.status -eq 'RESERVED_PENDING_UNACCEPTED' -and -not $sharePending.result_accepted) $sharePending.status
[void]$runtime.Invoke($null,[object[]]@('r1_fixture_end',$probeBinding))
$privateEnd=[long]$private.Invoke($null,@())
Assert 'actual_private_end_under512' ($privateEnd -le 536870912) $privateEnd
$phaseList=$runnerType.GetField('RuntimePhases',$allFlags).GetValue($null)
$phases=$phaseList.ToArray()
Assert 'actual_native_job512_caps_and_phase_peaks' ($phases.Count -eq 2 -and @($phases|Where-Object{$_.process_memory_limit_bytes -ne 536870912 -or $_.job_memory_limit_bytes -ne 536870912 -or $_.job_peak_process_memory_bytes -gt 536870912 -or $_.job_peak_memory_bytes -gt 536870912}).Count -eq 0) $phases.Count
$occupancy=0L
foreach($p in [IO.Directory]::EnumerateFiles($fixtureRoot,'*',[IO.SearchOption]::AllDirectories)){$occupancy+=[long]([IO.FileInfo]::new($p)).Length}
Assert 'fixture_occupancy_and_cumulative_upper_within8MiB' ($occupancy -le $maxFixtureBytes -and ($initialBytes+$script:accountedWritesUpper) -le $maxFixtureBytes) ([ordered]@{occupancy=$occupancy;accounted_cumulative_writer_upper=$script:accountedWritesUpper;initial_bytes=$initialBytes;ceiling=$maxFixtureBytes})
$receipt=[ordered]@{
  schema='niko.terminal_budget_r1.boundary_validation.v1';status='PASS_R1_BOUNDARY_ONLY'
  authority='Leo75391/75526, CPU tenant declared to Eli before execution'
  start_utc=$fixtureStart;end_utc=[DateTime]::UtcNow.ToString('o');elapsed_seconds=$watch.Elapsed.TotalSeconds
  source_path=$sourcePath;source_sha256='43f93066866ad44d9e2ec8fe06888d6d914321a3a18aa969affb5aaa5670a390'
  command_path=$commandPath;command_sha256='4a8629dc5928c110bffbdc2b4b0b02e897a5342832c29712a8eec078390dc702'
  production_root_ceiling_unchanged=134217728;synthetic_root_ceiling=$limit;terminal_reservation_bytes=8192
  assertions=$assertions.ToArray();assertion_count=$assertions.Count;all_assertions_pass=$true
  initial_fixture_bytes=$initialBytes;accounted_cumulative_writer_upper_bytes=$script:accountedWritesUpper
  fixture_occupancy_before_receipt=$occupancy;fixture_cap_bytes=$maxFixtureBytes
  c_floor_preflight_bytes=$cFree;min_C_free_bytes=161061273600
  private_start_bytes=$privateStart;private_end_bytes=$privateEnd;runtime_phase_observations=$phases
  execution_boundary='Actual product command functions extracted from pinned AST; actual changed C# private reservation verifier and bounded writer executed under real512MiB child JobObject. Tiny C fixtures simulate terminal success/refusal; whole production launcher and catalog pipeline were not run.'
  coverage_limits='Tests fixed8192-byte pending/terminal documents, tiny preflight and exact131072-byte roots, source1-byte overcapacity, missing/truncated/tampered reserve,20KiB+ reason fallback and sharing-write failure. No actual production input, scale/equality replay, arbitrary concurrent mutation or power-loss durability proof.'
  old_memory_suite_sha256='2e702828e73daca85cba4bdaae895a227a313de17ba285f9cfa289df0bfbea87'
  production_executed=$false;scale_replayed=$false;Python=$false;A_B_runtime_reads=$false;automatic_retry=$false;result_accepted_as_production=$false
}
$out=Join-Path $fixtureRoot 'boundary-validation-v1.json'
if([IO.File]::Exists($out)){throw 'FIXTURE_RECEIPT_EXISTS'}
$receiptBytes=[Text.UTF8Encoding]::new($false).GetBytes(($receipt|ConvertTo-Json -Depth 14))
Account $receiptBytes.LongLength
if($receiptBytes.LongLength -gt ($maxFixtureBytes-$occupancy)){throw 'FIXTURE_RECEIPT_CAP'}
[IO.File]::WriteAllBytes($out,$receiptBytes)
if((Get-FileHash -LiteralPath $out).Hash.ToLowerInvariant() -ne [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($receiptBytes)).ToLowerInvariant()){throw 'FIXTURE_RECEIPT_READBACK'}
[ordered]@{status='PASS_R1_BOUNDARY_ONLY';receipt=$out;bytes=$receiptBytes.LongLength;sha256=(Get-FileHash -LiteralPath $out).Hash.ToLowerInvariant();assertions=$assertions.Count}|ConvertTo-Json -Compress
