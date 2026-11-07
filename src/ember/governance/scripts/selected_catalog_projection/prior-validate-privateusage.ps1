param(
  [Parameter(Mandatory=$true)][string]$SourcePath,
  [Parameter(Mandatory=$true)][string]$ExpectedSha256,
  [Parameter(Mandatory=$true)][string]$ReceiptPath
)
$ErrorActionPreference = 'Stop'
$productionLimit = 536870912L
$pollRows = 64
$checks = [ordered]@{}
$started = [DateTime]::UtcNow.ToString('o')
$sourceHash = ''
$status = 'FAIL'
$failure = ''
$testThreshold = $null
$observedOverCap = $null
$observerFailureReason = ''
$steadyPeak = $null
$sampleCountAt63 = $null
$sampleCountAt64 = $null
$sampleCountAtBoundary = $null

function Write-Receipt {
  param([string]$State, [string]$FailureText)
  $record = [ordered]@{
    schema = 'niko.private_usage_observer.synthetic_validation.v1'
    status = $State
    source_path = [IO.Path]::GetFullPath($SourcePath)
    source_sha256 = $sourceHash
    started_utc = $started
    finished_utc = [DateTime]::UtcNow.ToString('o')
    production_process_and_job_limit_bytes = $productionLimit
    fixed_row_poll_interval = $pollRows
    steady_pass_peak_private_bytes = $steadyPeak
    steady_sample_count_after_63_rows = $sampleCountAt63
    steady_sample_count_after_64_rows = $sampleCountAt64
    steady_sample_count_after_pass_boundary = $sampleCountAtBoundary
    synthetic_guard_threshold_bytes = $testThreshold
    synthetic_overcap_observed_private_bytes = $observedOverCap
    injected_failure_reason_code = $observerFailureReason
    checks = $checks
    failure = $FailureText
  }
  [IO.File]::WriteAllText($ReceiptPath, ($record | ConvertTo-Json -Depth 8), [Text.UTF8Encoding]::new($false))
}

try {
  $sourceHash = (Get-FileHash -LiteralPath $SourcePath -Algorithm SHA256).Hash.ToLowerInvariant()
  if ($sourceHash -ne $ExpectedSha256.ToLowerInvariant()) { throw 'SOURCE_PIN_MISMATCH' }
  Add-Type -Path $SourcePath -ErrorAction Stop
  $runner = [type]'NikoSelectedProjection.Runner'
  $privateStatic = [Reflection.BindingFlags]::Static -bor [Reflection.BindingFlags]::NonPublic
  $sample = $runner.GetMethod('ObservePrivateUsage', $privateStatic, $null, [type[]]@(), $null)
  $sampleHandle = $runner.GetMethod('ObservePrivateUsage', $privateStatic, $null, [type[]]@([IntPtr]), $null)
  if ($null -eq $sample -or $null -eq $sampleHandle) { throw 'OBSERVER_API_MISSING' }
  $check = $runner.GetMethod('Check', $privateStatic)
  $peakField = $runner.GetField('PeakPrivate', $privateStatic)
  $samplesField = $runner.GetField('PrivateSampleCount', $privateStatic)
  $rowsField = $runner.GetField('PrivateRowsSinceSample', $privateStatic)
  if ($null -eq $check -or $null -eq $peakField -or $null -eq $samplesField -or $null -eq $rowsField) { throw 'OBSERVER_STATE_API_MISSING' }
  $bindingType = $runner.GetNestedType('Binding', [Reflection.BindingFlags]::Public)
  $binding = [Activator]::CreateInstance($bindingType)
  $bindingType.GetField('max_wall_seconds').SetValue($binding, 900L)
  $bindingType.GetField('max_total_bytes_read').SetValue($binding, 2415919104L)
  $bindingType.GetField('max_private_bytes').SetValue($binding, $productionLimit)

  $peakField.SetValue($null, 0L)
  $samplesField.SetValue($null, 0L)
  $rowsField.SetValue($null, 0)
  $watch = [Diagnostics.Stopwatch]::StartNew()
  for ($i = 1; $i -le ($pollRows - 1); $i++) {
    [void]$check.Invoke($null, [object[]]@($binding, $watch, 0L, 'metadata_row', $false))
  }
  $sampleCountAt63 = [long]$samplesField.GetValue($null)
  if ($sampleCountAt63 -ne 0) { throw 'ROW_POLL_EARLY' }
  [void]$check.Invoke($null, [object[]]@($binding, $watch, 0L, 'metadata_row', $false))
  $sampleCountAt64 = [long]$samplesField.GetValue($null)
  $steadyPeak = [long]$peakField.GetValue($null)
  if ($sampleCountAt64 -ne 1 -or $steadyPeak -le 0) { throw 'STEADY_PEAK_NOT_RECORDED' }
  [void]$check.Invoke($null, [object[]]@($binding, $watch, 0L, 'after_pass1', $true))
  $sampleCountAtBoundary = [long]$samplesField.GetValue($null)
  if ($sampleCountAtBoundary -ne ($sampleCountAt64 + 1)) { throw 'PASS_BOUNDARY_NOT_SAMPLED' }
  $checks.steady_pass_peak_recorded = $true
  $checks.fixed_64_row_poll_interval = $true
  $checks.pass_boundary_sampled = $true

  $baseline = [long]$sample.Invoke($null, [object[]]@())
  if ($baseline -ge ($productionLimit - 33554432L)) { throw 'SYNTHETIC_FIXTURE_HEADROOM_INSUFFICIENT' }
  $testThreshold = $baseline + 1048576L
  if ($testThreshold -ge $productionLimit) { throw 'SYNTHETIC_THRESHOLD_NOT_BELOW_PRODUCTION_LIMIT' }
  $bindingType.GetField('max_private_bytes').SetValue($binding, $testThreshold)
  $allocation = [byte[]]::new(16777216)
  for ($i = 0; $i -lt $allocation.Length; $i += 4096) { $allocation[$i] = 1 }
  $peakField.SetValue($null, 0L)
  $samplesField.SetValue($null, 0L)
  $rowsField.SetValue($null, 0)
  $capResult = ''
  try {
    [void]$check.Invoke($null, [object[]]@($binding, $watch, 0L, 'after_pass1', $true))
  } catch {
    $cause = $_.Exception
    while ($null -ne $cause.InnerException) { $cause = $cause.InnerException }
    $capResult = [string]$cause.Message
  }
  $observedOverCap = [long]$peakField.GetValue($null)
  if (-not $capResult.StartsWith('CAP_PRIVATE:', [StringComparison]::Ordinal) -or $observedOverCap -le $testThreshold) {
    throw 'SYNTHETIC_PRIVATE_CAP_NOT_EXERCISED'
  }
  $checks.real_allocation_crossed_synthetic_threshold = $true
  $checks.synthetic_guard_refused_CAP_PRIVATE = $true
  $checks.production_512MiB_limit_unchanged = ($productionLimit -eq 536870912L)

  $failure = $null
  try {
    [void]$sampleHandle.Invoke($null, [object[]]@([IntPtr]::Zero))
  } catch {
    $failure = $_.Exception
    while ($null -ne $failure.InnerException -and $failure -is [System.Management.Automation.MethodInvocationException]) {
      $failure = $failure.InnerException
    }
  }
  if ($null -eq $failure -or $failure.Message -notmatch '^OBSERVER_FAILED\(') { throw 'INJECTED_QUERY_DID_NOT_FAIL_CLOSED' }
  $wrappedFailure = [System.Reflection.TargetInvocationException]::new($failure)
$diagnostics = [NikoSelectedProjection.Runner]::CaptureFailure($wrappedFailure, 0L)
  $observerFailureReason = [string]$diagnostics.reason_code
  if ($observerFailureReason -notmatch '^OBSERVER_FAILED\(') { throw 'OBSERVER_FAILURE_REASON_MISSING' }
  $failureJson = $diagnostics | ConvertTo-Json -Depth 8
  $failureSchema = $failureJson | ConvertFrom-Json
  foreach ($key in @('error_type','reason_code','stack_trace','a_input_bytes_read','exception_chain')) {
    if ($null -eq $failureSchema.PSObject.Properties[$key]) { throw ('OBSERVER_FAILURE_SCHEMA_MISSING:' + $key) }
  }
  if ($failureSchema.exception_chain.Count -lt 2) { throw 'OBSERVER_FAILURE_SCHEMA_CHAIN' }
  $checks.injected_query_failure_refuses_OBSERVER_FAILED = $true
  $checks.failure_schema_has_reason_chain_and_byte_count = $true

  $status = 'PASS'
  Write-Receipt -State $status -FailureText ''
  [Console]::Out.WriteLine('OBSERVER_SYNTHETIC_CHECKS_PASS')
  exit 0
} catch {
  $detail = [string]$_.Exception.Message
  $expectedRed = ($detail -eq 'OBSERVER_API_MISSING' -or $detail -eq 'OBSERVER_FAILURE_REASON_MISSING')
  $status = if ($expectedRed) { 'EXPECTED_RED' } else { 'FAIL' }
  Write-Receipt -State $status -FailureText $detail
  [Console]::Error.WriteLine($detail)
  if ($expectedRed) { exit 1 }
  exit 2
}