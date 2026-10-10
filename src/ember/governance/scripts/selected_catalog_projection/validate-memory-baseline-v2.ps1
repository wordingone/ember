param([switch]$RedMode,[string]$CandidateSourcePath='',[string]$CandidateRunnerPath='')
$ErrorActionPreference='Stop'
$taskRoot=Split-Path -Parent $PSCommandPath
$syntheticRoot=if($RedMode){Join-Path $taskRoot 'synthetic-preselection-red'}else{Join-Path $taskRoot 'synthetic-memory-successor-validation-v2'}
$baselineSource=Join-Path $taskRoot 'baseline-source-leo74221.cs'
$baselineRunner=Join-Path $taskRoot 'baseline-runner-leo74221.ps1'
$utf8=[Text.UTF8Encoding]::new($false)
$tokenizer='aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
function Sha([string]$p){(Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash.ToLowerInvariant()}
function W([string]$p,[string]$s){[IO.File]::WriteAllText($p,$s,$utf8)}
function WJ([string]$p,$v){W $p (ConvertTo-Json -InputObject $v -Depth 20)}
function A([bool]$ok,[string]$name){if(-not $ok){throw ('ASSERTION_FAILED:'+$name)}}
function Fixture([string]$name,[string]$order,[bool]$duplicate,[string]$FixtureSource,[string]$FixtureRunner,[int]$extraUnselected=0){
  $dir=Join-Path $syntheticRoot $name;[void](New-Item -ItemType Directory -Path $dir -Force)
  $ds=@();$shas=@();for($i=0;$i -lt 8;$i++){$ds+=('dataset:issue1581-bulk-train:synthetic-'+$i);$shas+=('{0:x64}' -f [long]($i+1))}
  $r=[Collections.Generic.List[object]]::new();$e=[Collections.Generic.List[object]]::new()
  foreach($id in $ds){[void]$r.Add([ordered]@{kind='dataset_version';id=$id;state='admitted'})}
  for($i=0;$i -lt 8;$i++){
    $mid='m-selected-'+$i
    [void]$r.Add([ordered]@{kind='membership';id=$mid;exact_sha256=$shas[$i];split='train';admission_state='admitted';tokenizer_sha256=$tokenizer;window_start=[long]($i*10);window_end=[long]($i*10+10)})
    [void]$e.Add([ordered]@{kind='version_membership';from_id=$ds[$i];to_id=$mid})
  }
  [void]$r.Add([ordered]@{kind='membership';id='m-heldout';exact_sha256=$shas[0];split='validation';admission_state='admitted';tokenizer_sha256=$tokenizer;window_start=0;window_end=10})
  [void]$r.Add([ordered]@{kind='membership';id='m-quarantine';exact_sha256=$shas[0];split='train';admission_state='pending';tokenizer_sha256=$tokenizer;window_start=0;window_end=10})
  [void]$r.Add([ordered]@{kind='membership';id='m-adjudicated';exact_sha256=$shas[0];split='validation';admission_state='pending';tokenizer_sha256=$tokenizer;window_start=0;window_end=10})
  for($extra=0;$extra -lt $extraUnselected;$extra++){
    [void]$r.Add([ordered]@{kind='membership';id=('m-extra-unselected-'+$extra);exact_sha256=('{0:x64}' -f [long](10000+$extra));split='train';admission_state='pending';tokenizer_sha256=$tokenizer;window_start=0;window_end=10})
  }
  for($i=0;$i -lt 8;$i++){
    $rs='{0:x64}' -f [long](1000+$i)
    [void]$r.Add([ordered]@{kind='immutable_object';id=('obj-'+$i);sha256=$shas[$i]})
    [void]$r.Add([ordered]@{kind='receipt';sha256=$rs})
    [void]$e.Add([ordered]@{kind='object_receipt';from_id=('object:'+$shas[$i]);to_id=('receipt:'+$rs)})
  }
  [void]$e.Add([ordered]@{kind='evaluation_object';from_id='eval-synthetic';to_id=('object:'+$shas[0])})
  for($i=0;$i -lt 4096;$i++){[void]$r.Add([ordered]@{kind='unselected_padding';item=[long]$i;ordinal=[long]$i})}
  if($duplicate){
    foreach($n in @(9001,9002)){[void]$r.Add([ordered]@{kind='membership';id='m-unreferenced-duplicate';exact_sha256=('{0:x64}' -f [long]$n);split='train';admission_state='pending';tokenizer_sha256=$tokenizer;window_start=0;window_end=10})}
  }
  $doc=[ordered]@{};if($order -eq 'records_before_edges'){$doc.records=$r.ToArray();$doc.edges=$e.ToArray()}else{$doc.edges=$e.ToArray();$doc.records=$r.ToArray()}
  $ep=Join-Path $dir 'export.json';W $ep (ConvertTo-Json -InputObject $doc -Depth 20 -Compress);$eb=[IO.File]::ReadAllBytes($ep)
  $pp=Join-Path $dir 'prediction.json';$pred=[ordered]@{identity=[ordered]@{production_mixture=[ordered]@{catalog_export_path=$ep;catalog_export_sha256=(Sha $ep);dataset_ids=$ds};input_binding=[ordered]@{tokenizer_sha256=$tokenizer};data=[ordered]@{tokenizer_sha256=$tokenizer}}};WJ $pp $pred;$pb=[IO.File]::ReadAllBytes($pp)
  $cp=Join-Path $dir 'synthetic-command.pin';W $cp ('NIKO C-ONLY SYNTHETIC RUNNER PIN V1'+[Environment]::NewLine)
  $bp=Join-Path $dir 'binding.json';$src=$FixtureSource;$run=$FixtureRunner
  $b=[ordered]@{
    schema='synthetic';output_root=$dir;prediction_path=$pp;prediction_bytes=[long]$pb.LongLength;prediction_sha256=(Sha $pp)
    export_path=$ep;owner_reported_export_bytes=[long]$eb.LongLength;max_export_bytes=10485760
    max_total_bytes_read=([long]$eb.LongLength*3+[long]$pb.LongLength+65536);max_metadata_passes=2;max_wall_seconds=900
    max_private_bytes=536870912;max_output_bytes=67108864;min_C_free_bytes=0
    marker_path=(Join-Path $dir 'marker-not-created');tenant_declaration_path=(Join-Path $dir 'tenant-not-created.md')
    tenant_declaration_key='third_tenant_1581_projection';tenant_command_sha_key='third_tenant_1581_command_sha256';max_tenant_declaration_bytes=65536
    priority='BelowNormal';compute_parallelism=1;process_memory_limit_bytes=536870912;job_memory_limit_bytes=536870912
    source_path=$src;source_sha256=(Sha $src);runner_path=$run;runner_sha256=(Sha $run);command_path=$cp
  };WJ $bp $b
  [ordered]@{case_root=$dir;binding_path=$bp;binding_sha256=(Sha $bp);command_path=$cp;command_sha256=(Sha $cp);source_path=$src;runner_path=$run;root_order=$order;duplicate_unselected=$duplicate}
}
. (Join-Path $taskRoot 'fixture-boundary-v2.ps1')
function J([string]$p){Get-Content -LiteralPath $p -Raw|ConvertFrom-Json}
function Complete($x,[string]$n){A ($x.exit_code -eq 0) ($n+'_EXIT');A $x.cleanup_verified ($n+'_CLEANUP');A (Test-Path -LiteralPath $x.run_dir -PathType Container) ($n+'_RUN_DIR');A (-not(Test-Path -LiteralPath $x.refusal_path)) ($n+'_NO_REFUSAL')}
function DuplicateRefusal($x,[string]$n){
  A ($x.exit_code -eq 1) ($n+'_EXIT');A $x.cleanup_verified ($n+'_CLEANUP');A (-not(Test-Path -LiteralPath $x.run_dir)) ($n+'_NO_PARTIAL_RUN');A (Test-Path -LiteralPath $x.refusal_path -PathType Leaf) ($n+'_REFUSAL')
  $z=J $x.refusal_path;A ($z.status -eq 'REFUSED_NOT_COMPLETE') ($n+'_STATUS');A ((ConvertTo-Json $z -Depth 20 -Compress).Contains('MEMBERSHIP_DUPLICATE')) ($n+'_REASON');$z
}
if(Test-Path -LiteralPath $syntheticRoot){throw 'SYNTHETIC_ROOT_ALREADY_EXISTS'}
[void][IO.Directory]::CreateDirectory($syntheticRoot)
$rejectedSource=Join-Path $taskRoot 'rejected-source-e0b957c4.cs'
$rejectedRunner=Join-Path $taskRoot 'rejected-runner-b4263969.ps1'
A ((Sha $baselineSource) -eq 'd37e880d56548821e13a9c27af1cda73a6ff812b0c2d7a0f379e314986858f81') 'FROZEN_BASELINE_SOURCE'
A ((Sha $rejectedSource) -eq 'e0b957c4249b38b582cff073b2dcff9ca7dca1ee0f5dca5c851905352c4cf335') 'FROZEN_REJECTED_SOURCE'
function BoundEvidence($receipt,[long]$expectedIds,[string]$name){
  $sn=@($receipt.diagnostic_snapshots)
  foreach($cp in @('before_hash','after_hash','before_pass1','after_pass1','after_selected_membership_totality','before_pass2','after_pass2')){
    A (@($sn|Where-Object{$_.checkpoint -eq $cp}).Count -eq 1) ($name+'_'+$cp)
  }
  $hashEnd=@($sn|Where-Object{$_.checkpoint -eq 'after_hash'})[0]
  $passStart=@($sn|Where-Object{$_.checkpoint -eq 'before_pass1'})[0]
  A ([long]$hashEnd.selected_membership_id_count -eq 8) ($name+'_HASH_PRESELECTS_EIGHT')
  A ([long]$passStart.selected_membership_id_count -eq 8) ($name+'_BEFORE_PASS1_PRESELECTED')
  A ([long]$passStart.retained_member_object_count -eq 0) ($name+'_BEFORE_PASS1_NO_MEMBERS')
  $observed=@($sn|Where-Object{$_.pass_name -eq 'pass1'})
  A ($observed.Count -ge 4) ($name+'_PASS1_BOUND_OBSERVATIONS')
  foreach($s in $observed){
    A ([long]$s.retained_member_object_count -le 8) ($name+'_SELECTED_ONLY_THROUGH_PASS1_'+$s.checkpoint)
    A ([long]$s.selected_membership_id_count -eq 8) ($name+'_FIXED_SELECTION_THROUGH_PASS1_'+$s.checkpoint)
  }
  $end=@($sn|Where-Object{$_.checkpoint -eq 'after_pass1'})[0]
  A ([long]$end.retained_member_object_count -eq 8) ($name+'_AFTER_PASS1_MEMBERS')
  A ([long]$end.membership_id_set_count -eq $expectedIds) ($name+'_ALL_IDS_PRESERVED')
  foreach($pn in @('hash','pass1','pass2')){
    $rowSamples=@($sn|Where-Object{$_.checkpoint -eq 'every_4096_rows' -and $_.pass_name -eq $pn})
    A ($rowSamples.Count -ge 1) ($name+'_ROW_SNAPSHOTS_'+$pn)
    foreach($s in $rowSamples){A ([long]$s.private_usage_bytes -gt 0) ($name+'_PRIVATE_SAMPLE_'+$pn)}
  }
  $released=@($sn|Where-Object{$_.checkpoint -eq 'after_pass1_release'})[0]
  A ($null -ne $released) ($name+'_RELEASE_OBSERVED')
  foreach($key in @('membership_id_set_count','retained_member_object_count','selected_membership_id_count','selected_dataset_membership_link_count','heldout_hash_index_count','quarantine_hash_index_count','adjudicated_hash_index_count','protected_evaluation_hash_index_count','seen_version_edge_index_count')){A ([long]$released.$key -eq 0) ($name+'_RELEASE_'+$key)}
  A ([long]$receipt.final_validation_index_counts.membership_id_set_count -eq $expectedIds) ($name+'_FROZEN_FINAL_IDS')
  A (@($receipt.runtime_phase_observations).Count -ge 9) ($name+'_RUNTIME_PHASES')
  A ($receipt.membership_retention_strategy -eq 'hash_preselected_ids_only') ($name+'_RETENTION_STRATEGY')
  [ordered]@{selected_ids_after_hash=[long]$hashEnd.selected_membership_id_count;member_objects_before_pass1=[long]$passStart.retained_member_object_count;pass1_member_objects_max_observed=([long]($observed|Measure-Object -Property retained_member_object_count -Maximum).Maximum);member_objects_after_pass1=[long]$end.retained_member_object_count;all_membership_ids_after_pass1=[long]$end.membership_id_set_count;snapshots=$sn}
}
if($RedMode){
  $runs=[Collections.Generic.List[object]]::new()
  $clean=[Collections.Generic.List[object]]::new()
  $duplicates=[Collections.Generic.List[object]]::new()
  foreach($order in @('records_before_edges','edges_before_records')){
    $f=Fixture ('red-rejected-'+$order) $order $false $rejectedSource $rejectedRunner
    $x=RunHidden $f;Complete $x ('REJECTED_'+$order)
    $receipt=J (Join-Path $x.run_dir 'run-receipt.json')
    $sn=@($receipt.diagnostic_snapshots)
    $pre=@($sn|Where-Object{$_.checkpoint -eq 'after_pass1_before_prune'})[0]
    $row=@($sn|Where-Object{$_.checkpoint -eq 'every_4096_rows' -and $_.pass_name -eq 'pass1'})[0]
    A ([long]$pre.retained_member_object_count -eq 11) ($order+'_REPRODUCE_ELEVEN_BEFORE_PRUNE')
    A ([long]$row.retained_member_object_count -eq 11) ($order+'_REPRODUCE_ELEVEN_DURING_PASS1')
    $clean.Add([ordered]@{order=$order;retained_during_pass1=[long]$row.retained_member_object_count;retained_before_prune=[long]$pre.retained_member_object_count;required_maximum=8;selected_only_bound_passes=([long]$row.retained_member_object_count -le 8)})
    $runs.Add($x)
    $f=Fixture ('red-rejected-duplicate-'+$order) $order $true $rejectedSource $rejectedRunner
    $x=RunHidden $f;$z=DuplicateRefusal $x ('REJECTED_DUPLICATE_'+$order)
    $failure=@($z.diagnostic_snapshots|Where-Object{$_.checkpoint -eq 'row_failure' -and $_.pass_name -eq 'pass1'})|Select-Object -Last 1
    A ([long]$failure.retained_member_object_count -eq 12) ($order+'_REPRODUCE_TWELVE_ON_FAILURE')
    A ([long]$failure.membership_id_set_count -eq 12) ($order+'_REPRODUCE_TWELVE_IDS')
    $duplicates.Add([ordered]@{order=$order;failure_snapshot=$failure;required_maximum=8;selected_only_bound_passes=([long]$failure.retained_member_object_count -le 8)})
    $runs.Add($x)
  }
  $red=[ordered]@{schema='niko.selected_catalog_projection.preselection_validation.v1';status='RED_EXPECTED_SELECTED_ONLY_RETENTION_VIOLATION';observed_utc=[DateTime]::UtcNow.ToString('o');rejected_source_sha256=(Sha $rejectedSource);rejected_runner_sha256=(Sha $rejectedRunner);clean_cases=$clean.ToArray();duplicate_cases=$duplicates.ToArray();run_evidence=$runs.ToArray()}
  $rp=Join-Path $syntheticRoot 'preselection-red.json';WJ $rp $red
  Write-Output ('RED_RECEIPT='+$rp);Write-Output ('RED_RECEIPT_SHA256='+(Sha $rp))
  throw 'EXPECTED_RED_PASS1_MEMBER_RETENTION_EXCEEDS_SELECTED'
}
if(-not(Test-Path -LiteralPath $CandidateSourcePath -PathType Leaf)){throw 'CANDIDATE_SOURCE_MISSING'}
if(-not(Test-Path -LiteralPath $CandidateRunnerPath -PathType Leaf)){throw 'CANDIDATE_RUNNER_MISSING'}
$comparisons=[Collections.Generic.List[object]]::new()
$evidence=[Collections.Generic.List[object]]::new()
foreach($extra in @(0,8192)){
  foreach($order in @('records_before_edges','edges_before_records')){
    $name=$order+'-extra'+$extra
    $bf=Fixture ('baseline-'+$name) $order $false $baselineSource $baselineRunner $extra
    $br=RunHidden $bf;Complete $br ('BASELINE_'+$name)
    $cf=Fixture ('candidate-'+$name) $order $false $CandidateSourcePath $CandidateRunnerPath $extra
    $cr=RunHidden $cf;Complete $cr ('CANDIDATE_'+$name)
    A ((Sha $br.fixture.source_path) -eq (Sha $baselineSource)) ($name+'_REAL_FROZEN_BASELINE_SOURCE')
    A ((Sha $cr.fixture.source_path) -eq (Sha $CandidateSourcePath)) ($name+'_REAL_CANDIDATE_SOURCE')
    A ((Sha $br.fixture.source_path) -ne (Sha $cr.fixture.source_path)) ($name+'_DISTINCT_SOURCES')
    $same=[ordered]@{}
    foreach($fn in @('summary.json','selected-memberships.jsonl','selected-objects.jsonl')){
      $bh=Sha (Join-Path $br.run_dir $fn);$ch=Sha (Join-Path $cr.run_dir $fn)
      A ($bh -eq $ch) ($name+'_BYTE_EQUAL_'+$fn)
      $same[$fn]=[ordered]@{baseline_sha256=$bh;candidate_sha256=$ch;identical=($bh -eq $ch)}
    }
    $summary=J (Join-Path $cr.run_dir 'summary.json')
    A ([long]$summary.unique_selected_membership_ids -eq 8) ($name+'_SELECTED_MEMBERSHIPS')
    A ([long]$summary.global_analysis_context_edge_rows -eq 1) ($name+'_GLOBAL_CONTEXT')
    A ([long]$summary.selected_sha_intersections.admitted_non_train -eq 1) ($name+'_HELDOUT_ALL_ROWS')
    A ([long]$summary.selected_sha_intersections.quarantined_train -eq 1) ($name+'_QUARANTINE_ALL_ROWS')
    A ([long]$summary.selected_sha_intersections.adjudicated_non_train -eq 1) ($name+'_ADJUDICATED_ALL_ROWS')
    A ([long]$summary.selected_sha_intersections.protected_evaluation -eq 1) ($name+'_EVALUATION_ALL_ROWS')
    $receipt=J (Join-Path $cr.run_dir 'run-receipt.json')
    $bound=BoundEvidence $receipt (11+$extra) $name
    A ([long]$receipt.metadata_passes -eq 2) ($name+'_TWO_METADATA_PASSES')
    A ([long]$receipt.max_private_bytes -eq 536870912) ($name+'_PRIVATE_CAP')
    A ([long]$receipt.private_bytes_peak_observed -gt 0) ($name+'_MEASURED_PRIVATE_PEAK')
    $comparisons.Add([ordered]@{case=$name;extra_unselected_memberships=$extra;baseline_source_sha256=(Sha $br.fixture.source_path);candidate_source_sha256=(Sha $cr.fixture.source_path);outputs=$same;retention_bound=$bound})
    $evidence.Add([ordered]@{case=$name;baseline=$br;candidate=$cr})
  }
}
$duplicates=[Collections.Generic.List[object]]::new()
foreach($order in @('records_before_edges','edges_before_records')){
  $bf=Fixture ('baseline-duplicate-'+$order) $order $true $baselineSource $baselineRunner
  $br=RunHidden $bf;$bz=DuplicateRefusal $br ('BASELINE_DUPLICATE_'+$order)
  $cf=Fixture ('candidate-duplicate-'+$order) $order $true $CandidateSourcePath $CandidateRunnerPath
  $cr=RunHidden $cf;$cz=DuplicateRefusal $cr ('CANDIDATE_DUPLICATE_'+$order)
  A ($cz.schema -eq 'niko.selected_catalog_projection.refusal.v5') ($order+'_REFUSAL_SCHEMA')
  A ($bz.exception_chain[-1].message -eq $cz.exception_chain[-1].message) ($order+'_EXACT_DUPLICATE_REFUSAL_MESSAGE')
  $failure=@($cz.diagnostic_snapshots|Where-Object{$_.checkpoint -eq 'row_failure' -and $_.pass_name -eq 'pass1'})|Select-Object -Last 1
  A ($null -ne $failure) ($order+'_FAILURE_SNAPSHOT')
  A ([long]$failure.membership_id_set_count -eq 12) ($order+'_ALL_ROW_DUPLICATE_CHECK')
  A ([long]$failure.retained_member_object_count -eq 8) ($order+'_FAILURE_SELECTED_ONLY')
  A ([long]$failure.selected_membership_id_count -eq 8) ($order+'_FAILURE_SELECTION_FIXED')
  & (Join-Path $taskRoot 'validate-refusal-peak.ps1') -RefusalPath $cr.refusal_path -ReceiptPath (Join-Path $syntheticRoot ('peak-'+$order+'.json'))
  $duplicates.Add([ordered]@{order=$order;baseline_inner_message=$bz.exception_chain[-1].message;candidate_inner_message=$cz.exception_chain[-1].message;failure_snapshot=$failure;candidate_exit_code=$cr.exit_code;candidate_cleanup_verified=$cr.cleanup_verified})
  $evidence.Add([ordered]@{case='duplicate-'+$order;baseline=$br;candidate=$cr})
}
$nf=Fixture 'candidate-no-sample-refusal' 'records_before_edges' $false $CandidateSourcePath $CandidateRunnerPath
$nb=J $nf.binding_path;$nb.max_metadata_passes=3;WJ $nf.binding_path $nb;$nf.binding_sha256=Sha $nf.binding_path
$nr=RunHidden $nf
A ($nr.exit_code -eq 1 -and $nr.cleanup_verified) 'NO_SAMPLE_REFUSAL_EXIT_CLEANUP'
A (-not(Test-Path -LiteralPath $nr.run_dir)) 'NO_SAMPLE_REFUSAL_NO_PARTIAL'
$nz=J $nr.refusal_path
A ($nz.exception_chain[-1].message -eq 'BINDING_SCHEMA') 'NO_SAMPLE_REFUSAL_REASON'
A ([long]$nz.a_input_bytes_read -eq 0) 'NO_SAMPLE_NO_DATA_READ'
& (Join-Path $taskRoot 'validate-refusal-peak.ps1') -RefusalPath $nr.refusal_path -ReceiptPath (Join-Path $syntheticRoot 'peak-no-sample.json') -ExpectNoSample
$evidence.Add([ordered]@{case='no-successful-sample';candidate=$nr})
$v=[ordered]@{
 schema='niko.selected_catalog_projection.preselection_validation.v1';status='PASS_HASH_PRESELECTED_MEMBER_RETENTION';observed_utc=[DateTime]::UtcNow.ToString('o')
 baseline_source_sha256=(Sha $baselineSource);baseline_runner_sha256=(Sha $baselineRunner);candidate_source_sha256=(Sha $CandidateSourcePath);candidate_runner_sha256=(Sha $CandidateRunnerPath)
 fixture_contract=[ordered]@{root_orders=@('records_before_edges','edges_before_records');selected_memberships=8;small_all_ids=11;stress_all_ids=8203;padding_records=4096;duplicate_unselected_refuses=$true;source_change_detected='unconditional full Member construction for unselected membership';baseline_and_candidate_bound_separately=$true}
 comparisons=$comparisons.ToArray();duplicate_refusals=$duplicates.ToArray();run_evidence=$evidence.ToArray()
}
$vp=Join-Path $syntheticRoot 'preselection-validation.json';WJ $vp $v
Write-Output ('VALIDATION_RECEIPT='+$vp);Write-Output ('VALIDATION_RECEIPT_SHA256='+(Sha $vp));Write-Output ('VALIDATION_STATUS='+$v.status)
