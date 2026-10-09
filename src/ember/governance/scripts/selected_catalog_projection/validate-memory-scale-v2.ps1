param([string]$CandidateSourcePath,[string]$CandidateRunnerPath)
$ErrorActionPreference='Stop'
$root=Join-Path $PSScriptRoot 'synthetic-memory-scale-v2'
if(Test-Path -LiteralPath $root){throw 'SCALE_ROOT_EXISTS'}
$free=[long]([IO.DriveInfo]::new('C:\')).AvailableFreeSpace
if($free -lt 161061273600){throw 'SCALE_C_FLOOR'}
$watch=[Diagnostics.Stopwatch]::StartNew();$started=[DateTime]::UtcNow.ToString('o')
[void][IO.Directory]::CreateDirectory($root)
$case=Join-Path $root 'projection';[void][IO.Directory]::CreateDirectory($case)
$utf8=[Text.UTF8Encoding]::new($false)
function Sha($p){(Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash.ToLowerInvariant()}
function WJ($p,$v){[IO.File]::WriteAllText($p,(ConvertTo-Json -InputObject $v -Depth 30),$utf8)}
function Assert([bool]$ok,[string]$name){if(-not $ok){throw ('SCALE_ASSERT:'+ $name)}}
Add-Type -Path (Join-Path $PSScriptRoot 'scale-generator.cs')
. (Join-Path $PSScriptRoot 'fixture-boundary-v2.ps1')
$terminal=$null;$coverage=$null;$status='REFUSED_NOT_COMPLETE';$errorText='';$inputBytes=0L
try{
  $export=Join-Path $root 'export.json';$coverage=[MemoryScaleGenerator]::Generate($export);$inputBytes=[long]$coverage.export_bytes
  $prediction=Join-Path $root 'prediction.json';$ds=@();for($i=0;$i -lt 8;$i++){$ds+=('dataset:issue1581-bulk-train:scale-'+$i)}
  $tok='a'*64
  WJ $prediction ([ordered]@{identity=[ordered]@{production_mixture=[ordered]@{catalog_export_path=$export;catalog_export_sha256=(Sha $export);dataset_ids=$ds};input_binding=[ordered]@{tokenizer_sha256=$tok};data=[ordered]@{tokenizer_sha256=$tok}}})
  $cp=Join-Path $case 'command.pin';[IO.File]::WriteAllText($cp,'NIKO C-ONLY SCALE PIN V1'+"`n",$utf8)
  $bp=Join-Path $case 'binding.json'
  $binding=[ordered]@{schema='synthetic';output_root=$case;prediction_path=$prediction;prediction_bytes=[long](Get-Item -LiteralPath $prediction).Length;prediction_sha256=(Sha $prediction);export_path=$export;owner_reported_export_bytes=$inputBytes;max_export_bytes=805306368;max_total_bytes_read=2415919104;max_metadata_passes=2;max_wall_seconds=900;max_private_bytes=536870912;max_output_bytes=134217728;min_C_free_bytes=161061273600;marker_path=(Join-Path $root 'marker-never-created');tenant_declaration_path=(Join-Path $root 'tenant-never-created');tenant_declaration_key='disabled';tenant_command_sha_key='disabled';max_tenant_declaration_bytes=65536;priority='BelowNormal';compute_parallelism=1;process_memory_limit_bytes=536870912;job_memory_limit_bytes=536870912;source_path=$CandidateSourcePath;source_sha256=(Sha $CandidateSourcePath);runner_path=$CandidateRunnerPath;runner_sha256=(Sha $CandidateRunnerPath);command_path=$cp}
  $preparedBytes=0L;foreach($file in [IO.Directory]::EnumerateFiles($root,'*',[IO.SearchOption]::AllDirectories)){$preparedBytes+=[IO.FileInfo]::new($file).Length}
  # Preserve 64 KiB for the binding and terminal receipt, so the projection cannot exceed the cumulative-write budget.
  $binding.max_output_bytes=[long][Math]::Min(134217728,268435456-$preparedBytes-65536)
  if($binding.max_output_bytes -le 0){throw 'SCALE_NO_OUTPUT_BUDGET'}
  WJ $bp $binding
  $f=[ordered]@{case_root=$case;binding_path=$bp;binding_sha256=(Sha $bp);command_path=$cp;command_sha256=(Sha $cp);source_path=$CandidateSourcePath;runner_path=$CandidateRunnerPath}
  $terminal=RunHidden $f
  Assert ($terminal.exit_code -eq 0 -and $terminal.cleanup_verified -and -not $terminal.timed_out) 'ACTUAL_EXIT_CLEANUP'
  $run=Join-Path $case 'run';Assert ([IO.Directory]::Exists($run) -and -not [IO.Directory]::Exists((Join-Path $case 'staging-unaccepted'))) 'ATOMIC_PROMOTION'
  $summary=Get-Content -LiteralPath (Join-Path $run 'summary.json') -Raw|ConvertFrom-Json
  $receipt=Get-Content -LiteralPath (Join-Path $run 'run-receipt.json') -Raw|ConvertFrom-Json
  Assert ($summary.unique_selected_membership_ids -eq 130578 -and $summary.selected_membership_edge_rows -eq 130578 -and $summary.unique_selected_sha256s -eq 130103) 'MINIMUM_SCALE_COUNTS'
  Assert ($receipt.final_validation_index_counts.membership_id_set_count -eq 293852) 'ALL_ROW_DUPLICATE_INDEX'
  Assert ($summary.unresolved_receipt_edges -eq 0 -and $summary.missing_selected_objects -eq 0 -and $summary.duplicate_object_rows -eq 0) 'OBJECT_RECEIPT_CHECKS'
  $live=@($receipt.diagnostic_snapshots|Where-Object{$_.checkpoint -eq 'after_pass1_release'})[0]
  foreach($key in @('membership_id_set_count','retained_member_object_count','selected_membership_id_count','selected_dataset_membership_link_count','heldout_hash_index_count','quarantine_hash_index_count','adjudicated_hash_index_count','protected_evaluation_hash_index_count','seen_version_edge_index_count')){Assert ([long]$live.$key -eq 0) ('RELEASE_'+$key)}
  Assert ($receipt.private_bytes_peak_observed -gt 0 -and $receipt.private_bytes_peak_observed -le 536870912) 'PRIVATE_CAP'
  $phases=Get-Content -LiteralPath (Join-Path $run 'phase-observations.json') -Raw|ConvertFrom-Json
  Assert (@($phases).Count -ge 10) 'ALL_PHASES'
  foreach($phase in $phases){Assert ($phase.job_peak_process_memory_bytes -le 536870912 -and $phase.job_peak_memory_bytes -le 536870912 -and $phase.process_memory_limit_bytes -eq 536870912 -and $phase.job_memory_limit_bytes -eq 536870912) 'JOB_CAP_COUNTERS'}
  $status='PASS_SCALE_FINAL_SERIALIZATION'
}catch{$errorText=$_.Exception.ToString();throw}
finally{
  $occupancy=0L;foreach($file in [IO.Directory]::EnumerateFiles($root,'*',[IO.SearchOption]::AllDirectories)){$occupancy+=[IO.FileInfo]::new($file).Length}
  # Files are exclusive-create and never copied or overwritten here. Promotion is a same-volume rename.
  $receiptPath=Join-Path $root 'scale-validation.json'
  $record=[ordered]@{schema='niko.selected_catalog_projection.memory_scale_validation.v1';status=$status;start_utc=$started;end_utc=[DateTime]::UtcNow.ToString('o');elapsed_seconds=$watch.Elapsed.TotalSeconds;c_free_before_bytes=$free;max_written_bytes=268435456;occupancy_before_validation_receipt_bytes=$occupancy;cumulative_written_before_validation_receipt_bytes=$occupancy;input_export_bytes=$inputBytes;coverage=$coverage;child_terminal=$terminal;error=$errorText;automatic_retry=$false;production_payload_copied=$false;A_B_runtime_reads=$false;accepted_production_result=$false}
  $json=ConvertTo-Json -InputObject $record -Depth 30
  if($occupancy+$utf8.GetByteCount($json) -gt 268435456 -or $watch.Elapsed.TotalSeconds -gt 900){$record.status='REFUSED_NOT_COMPLETE';$record.error+=' SCALE_TOTAL_WRITE_OR_WALL_CAP';$json=ConvertTo-Json -InputObject $record -Depth 30}
  [IO.File]::WriteAllText($receiptPath,$json,$utf8)
  Write-Output ('SCALE_RECEIPT='+$receiptPath);Write-Output ('SCALE_RECEIPT_SHA256='+(Sha $receiptPath));Write-Output ('SCALE_STATUS='+$record.status)
  if($record.status -ne 'PASS_SCALE_FINAL_SERIALIZATION'){[Console]::Error.WriteLine($record.error);throw 'SCALE_VALIDATION_REFUSED'}
}
