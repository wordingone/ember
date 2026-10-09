param([string]$BindingPath,[string]$CommandPath)
$ErrorActionPreference='Stop'
$BindingPath=[IO.Path]::GetFullPath($BindingPath);$CommandPath=[IO.Path]::GetFullPath($CommandPath)
$b=Get-Content -LiteralPath $BindingPath -Raw|ConvertFrom-Json
$cmdText=[IO.File]::ReadAllText($CommandPath);$bindingSha=(Get-FileHash -LiteralPath $BindingPath -Algorithm SHA256).Hash.ToLowerInvariant()
function Sha([string]$p){(Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash.ToLowerInvariant()}
$root=[string]$b.output_root
$rootBytes=[long](Get-ChildItem -LiteralPath $root -File -Recurse|Measure-Object -Property Length -Sum).Sum
$literalCount=[regex]::Matches($cmdText,'(?m)^\$memoryLimitBytes\s*=\s*536870912\s*$').Count
$assignmentCount=[regex]::Matches($cmdText,'(?m)^\$memoryLimitBytes\s*=').Count
$setsCaps=$cmdText -match 'SetCaps\(\$job,\[ulong\]\$memoryLimitBytes\)'
$setsProcess=$cmdText -match 'ProcessMemoryLimit=new UIntPtr\(bytes\)'
$setsJob=$cmdText -match 'JobMemoryLimit=new UIntPtr\(bytes\)'
$hasOverride=($cmdText -match '(?im)^\s*param\s*\(')-or($cmdText -match '\$memoryLimitBytes\s*=\s*\$env:')-or($cmdText -match ('--max-'+'private-bytes'))
$runnerText=[IO.File]::ReadAllText([string]$b.runner_path)
$hiddenChild=($cmdText -match 'UseShellExecute\s*=\s*\$false')-and($cmdText -match 'CreateNoWindow\s*=\s*\$true')-and($cmdText -match 'RedirectStandardOutput\s*=\s*\$true')-and($cmdText -match 'RedirectStandardError\s*=\s*\$true')
$checks=[ordered]@{
  binding_path_matches=([IO.Path]::GetFullPath([string]$b.binding_path) -eq $BindingPath)
  command_path_matches=([IO.Path]::GetFullPath([string]$b.command_path) -eq $CommandPath)
  command_self_binds_binding_sha=$cmdText.Contains($bindingSha)
  command_embeds_bound_runner=$cmdText.Contains([string]$b.runner_path)
  source_hash_matches=(Sha ([string]$b.source_path)) -eq ([string]$b.source_sha256).ToLowerInvariant()
  runner_hash_matches=(Sha ([string]$b.runner_path)) -eq ([string]$b.runner_sha256).ToLowerInvariant()
  process_cap_512_mib=([long]$b.process_memory_limit_bytes -eq 536870912)
  job_cap_512_mib=([long]$b.job_memory_limit_bytes -eq 536870912)
  private_guard_512_mib=([long]$b.max_private_bytes -eq 536870912)
  wall_900_seconds=([long]$b.max_wall_seconds -eq 900)
  below_normal_single_thread=([string]$b.priority -eq 'BelowNormal' -and [int]$b.compute_parallelism -eq 1)
  one_fixed_cap_literal=($literalCount -eq 1 -and $assignmentCount -eq 1)
  job_process_caps_set=($setsCaps -and $setsProcess -and $setsJob)
  no_cap_override_path=(-not $hasOverride)
  child_hidden_and_streams_captured=$hiddenChild
  candidate_root_under_output_cap=($rootBytes -le [long]$b.max_output_bytes)
  no_prior_top_level_production_run=(-not(Test-Path -LiteralPath (Join-Path $root 'run')) -and -not(Test-Path -LiteralPath (Join-Path $root 'run-refusal.json')))
  retired_H37_declaration_removed=([string]$b.tenant_declaration_path -notmatch '2119|H37' -and -not(Test-Path -LiteralPath ([string]$b.tenant_declaration_path)))
  marker_up_has_no_override=([string]$b.marker_policy -match 'No tenant override')
}
$tokens=$null;$errors=$null
[void][Management.Automation.Language.Parser]::ParseFile($CommandPath,[ref]$tokens,[ref]$errors)
$checks.command_ast_valid=(@($errors).Count -eq 0)
$checks.window_style_hidden=($cmdText -match 'WindowStyle\s*=\s*\[Diagnostics.ProcessWindowStyle\]::Hidden')
$flush=$cmdText.IndexOf('$preflightStream.Flush($true)',[StringComparison]::Ordinal)
$launch=$cmdText.IndexOf('$child = [Diagnostics.Process]::Start($psi)',[StringComparison]::Ordinal)
$checks.final_gate_flushed_before_child_start=($flush -ge 0 -and $launch -gt $flush)
$checks.source_bound_through_pass1=([string]$b.retention_policy -match 'THROUGH pass1' -and [string]$b.metadata_order_strategy -match 'hash traversal preselects')
$checks.diagnostic_cap_refusal_covered=([string]$b.retention_diagnostics -match 'triggering sample' -and (Test-Path -LiteralPath (Join-Path $root 'cap-snapshot-green.json')))
$pass=(@($checks.Values|Where-Object{$_ -eq $false}).Count -eq 0)
$receipt=[ordered]@{
 schema='niko.selected_catalog_projection.production_binding_static_validation.v1'
 status=if($pass){'PASS_STATIC_BINDING_ONLY'}else{'FAIL_STATIC_BINDING'}
 observed_utc=[DateTime]::UtcNow.ToString('o')
 binding_path=$BindingPath;binding_sha256=$bindingSha
 command_path=$CommandPath;command_sha256=(Sha $CommandPath)
 source_sha256=(Sha ([string]$b.source_path));runner_sha256=(Sha ([string]$b.runner_path))
 output_root_bytes=$rootBytes;output_root_cap_bytes=[long]$b.max_output_bytes
 process_memory_limit_bytes=[long]$b.process_memory_limit_bytes
 job_memory_limit_bytes=[long]$b.job_memory_limit_bytes
 private_guard_bytes=[long]$b.max_private_bytes
 checks=$checks
 command_executed=$false
}
$receiptPath=Join-Path $root 'retention-binding-validation.json'
$receipt|ConvertTo-Json -Depth 10|Set-Content -LiteralPath $receiptPath -Encoding utf8
Get-FileHash -LiteralPath $receiptPath -Algorithm SHA256|Select-Object Path,Hash|Format-List
$receipt|ConvertTo-Json -Depth 8
if(-not $pass){throw 'STATIC_BINDING_VALIDATION_FAILED'}
