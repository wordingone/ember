param([Parameter(Mandatory=$true)][string]$RefusalPath,[Parameter(Mandatory=$true)][string]$ReceiptPath,[switch]$ExpectNoSample)
$ErrorActionPreference='Stop'
if(Test-Path -LiteralPath $ReceiptPath){throw 'PEAK_CHECK_RECEIPT_EXISTS'}
$j=Get-Content -LiteralPath $RefusalPath -Raw|ConvertFrom-Json
$names=@($j.PSObject.Properties.Name)
$peakPresent=$names -contains 'private_bytes_peak_observed'
$countPresent=$names -contains 'private_usage_sample_count'
$sampleCount=if($countPresent){[long]$j.private_usage_sample_count}else{$null}
$peak=if($peakPresent){$j.private_bytes_peak_observed}else{$null}
$checks=[ordered]@{peak_field_present=$peakPresent;sample_count_field_present=$countPresent;refusal_not_accepted=($j.result_accepted -eq $false);original_exception_retained=(@($j.exception_chain).Count -gt 0)}
if($ExpectNoSample){
 $checks.zero_samples=($countPresent -and $sampleCount -eq 0)
 $checks.peak_explicitly_unknown=($peakPresent -and $null -eq $peak)
}else{
 $checks.successful_sample_recorded=($countPresent -and $sampleCount -gt 0)
 $checks.measured_peak_positive=($peakPresent -and $null -ne $peak -and [long]$peak -gt 0)
 $sn=@($j.diagnostic_snapshots)
 $lower=if($sn.Count){[long]($sn|Measure-Object -Property private_usage_bytes -Maximum).Maximum}else{0L}
 $checks.peak_covers_reported_samples=($peakPresent -and $null -ne $peak -and [long]$peak -ge $lower)
}
$pass=@($checks.Values|Where-Object{$_ -ne $true}).Count -eq 0
$r=[ordered]@{schema='niko.refusal_peak_validation.v1';status=if($pass){'PASS_REFUSAL_PEAK_CONTRACT'}else{'RED_REFUSAL_PEAK_CONTRACT'};observed_utc=[DateTime]::UtcNow.ToString('o');refusal_path=$RefusalPath;refusal_sha256=(Get-FileHash -LiteralPath $RefusalPath -Algorithm SHA256).Hash.ToLowerInvariant();expect_no_sample=[bool]$ExpectNoSample;checks=$checks}
[IO.File]::WriteAllText($ReceiptPath,(ConvertTo-Json $r -Depth 8),[Text.UTF8Encoding]::new($false))
Write-Output ('PEAK_VALIDATION='+$r.status)
if(-not $pass){throw 'ASSERTION_FAILED:REFUSAL_MUST_CARRY_MEASURED_OR_EXPLICITLY_UNKNOWN_PEAK'}