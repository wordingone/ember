param(
  [Parameter(Mandatory=$true)][string]$BindingPath,
  [Parameter(Mandatory=$true)][string]$BindingSha256,
  [Parameter(Mandatory=$true)][string]$CommandPath,
  [Parameter(Mandatory=$true)][string]$CommandSha256,
  [Parameter(Mandatory=$true)][string]$GateName
)
$ErrorActionPreference = 'Stop'
$binding = $null
$actualBinding = $BindingSha256
$gate = $null
try {
  if ($PSVersionTable.PSVersion.Major -lt 7) { throw 'POWERSHELL7_REQUIRED' }
  foreach ($literal in @($BindingPath,$CommandPath,$GateName)) {
    if ([string]::IsNullOrWhiteSpace($literal) -or $literal -ne $literal.Trim() -or $literal.Contains("`r") -or $literal.Contains("`n")) { throw 'LITERAL_SINGLE_LINE' }
  }
  if ($BindingSha256 -notmatch '^[0-9a-fA-F]{64}$' -or $CommandSha256 -notmatch '^[0-9a-fA-F]{64}$') { throw 'DIGEST_FORMAT' }
  $gate = [Threading.EventWaitHandle]::OpenExisting($GateName)
  if (-not $gate.WaitOne([TimeSpan]::FromSeconds(900))) { throw 'LAUNCH_GATE_TIMEOUT' }
  $BindingPath = [IO.Path]::GetFullPath($BindingPath)
  $CommandPath = [IO.Path]::GetFullPath($CommandPath)
  $binding = Get-Content -LiteralPath $BindingPath -Raw | ConvertFrom-Json
  $actualBinding = (Get-FileHash -LiteralPath $BindingPath -Algorithm SHA256).Hash.ToLowerInvariant()
  $actualCommand = (Get-FileHash -LiteralPath $CommandPath -Algorithm SHA256).Hash.ToLowerInvariant()
  $actualRunner = (Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash.ToLowerInvariant()
  $actualSource = (Get-FileHash -LiteralPath ([string]$binding.source_path) -Algorithm SHA256).Hash.ToLowerInvariant()
  if ($actualBinding -ne $BindingSha256.ToLowerInvariant()) { throw 'BINDING_HASH' }
  if ($actualCommand -ne $CommandSha256.ToLowerInvariant() -or [string]$binding.command_path -ne $CommandPath) { throw 'COMMAND_HASH' }
  if ($actualSource -ne ([string]$binding.source_sha256).ToLowerInvariant()) { throw 'SOURCE_HASH' }
  if ($actualRunner -ne ([string]$binding.runner_sha256).ToLowerInvariant() -or [string]$binding.runner_path -ne $PSCommandPath) { throw 'RUNNER_HASH' }
  $runDir = Join-Path ([string]$binding.output_root) 'run'
  $refusalPath = Join-Path ([string]$binding.output_root) 'run-refusal.json'
  if ((Test-Path -LiteralPath $runDir) -or (Test-Path -LiteralPath $refusalPath)) { throw 'PRIOR_RUN_STATE' }
  Add-Type -Path ([string]$binding.source_path) -ErrorAction Stop
  [NikoSelectedProjection.Runner]::Run($BindingPath, $BindingSha256, $CommandPath, $CommandSha256)
} catch {
  $caughtException = $_.Exception
  $diagnostics = $null
  $aInputBytesRead = $null
  $exceptionChain = @()
  $errorType = [string]$caughtException.GetType().FullName
  $stackTrace = [string]$caughtException.ToString()
  $reason = $errorType
  try {
    $runnerType = $null
    foreach ($assembly in [AppDomain]::CurrentDomain.GetAssemblies()) {
      $candidate = $assembly.GetType('NikoSelectedProjection.Runner', $false)
      if ($null -ne $candidate) { $runnerType = $candidate; break }
    }
    if ($null -ne $runnerType) {
      $flags = [System.Reflection.BindingFlags]::Public -bor [System.Reflection.BindingFlags]::Static
      $bytesField = $runnerType.GetField('LastAInputBytesRead', $flags)
      if ($null -ne $bytesField) { $aInputBytesRead = [long]$bytesField.GetValue($null) }
      $capture = $runnerType.GetMethod('CaptureFailure', $flags)
      if ($null -ne $capture) {
        $bytesForDiagnostics = 0L
        if ($null -ne $aInputBytesRead) { $bytesForDiagnostics = [long]$aInputBytesRead }
        $diagnostics = $capture.Invoke($null, [object[]]@($caughtException, $bytesForDiagnostics))
      }
    }
  } catch { }
  if ($null -ne $diagnostics) {
    $reason = [string]$diagnostics.reason_code
    $errorType = [string]$diagnostics.error_type
    $stackTrace = [string]$diagnostics.stack_trace
    $aInputBytesRead = [long]$diagnostics.a_input_bytes_read
    $exceptionChain = @($diagnostics.exception_chain)
  } else {
    $cursor = $caughtException
    while ($null -ne $cursor) {
      $exceptionChain += [ordered]@{
        type = [string]$cursor.GetType().FullName
        message = [string]$cursor.Message
        hresult = [int]$cursor.HResult
        stack_trace = [string]$cursor.StackTrace
      }
      $cursor = $cursor.InnerException
    }
    if ($exceptionChain.Count -gt 0) { $reason = [string]$exceptionChain[-1].type }
  }
  if ($null -ne $binding -and -not [string]::IsNullOrWhiteSpace([string]$binding.output_root)) {
    $refusalPath = Join-Path ([string]$binding.output_root) 'run-refusal.json'
    $runDir = Join-Path ([string]$binding.output_root) 'run'
    if (-not (Test-Path -LiteralPath $runDir) -and -not (Test-Path -LiteralPath $refusalPath)) {
      $receipt = [ordered]@{
        schema = 'niko.selected_catalog_projection.refusal.v3'
        status = 'REFUSED_NOT_COMPLETE'
        reason_code = $reason
        error_type = $errorType
        exception_chain = $exceptionChain
        stack_trace = $stackTrace
        a_input_bytes_read = $aInputBytesRead
        observed_utc = [DateTime]::UtcNow.ToString('o')
        prediction_sha256 = [string]$binding.prediction_sha256
        source_sha256 = [string]$binding.source_sha256
        runner_sha256 = [string]$binding.runner_sha256
        binding_sha256 = $actualBinding
        command_sha256 = $CommandSha256
        max_private_bytes = [long]$binding.max_private_bytes
        process_memory_limit_bytes = [long]$binding.process_memory_limit_bytes
        job_memory_limit_bytes = [long]$binding.job_memory_limit_bytes
        marker_present_at_refusal = Test-Path -LiteralPath ([string]$binding.marker_path)
        tenant_declaration_path = [string]$binding.tenant_declaration_path
        partial_run_directory_exists = $false
        automatic_retry = $false
        result_accepted = $false
      }
      $bytes = [Text.Encoding]::UTF8.GetBytes(($receipt | ConvertTo-Json -Depth 6))
      $existing = (Get-ChildItem -LiteralPath ([string]$binding.output_root) -File -Recurse | Measure-Object -Property Length -Sum).Sum
      if (($existing + $bytes.Length) -le [long]$binding.max_output_bytes) { [IO.File]::WriteAllBytes($refusalPath, $bytes) }
    }
  }
  [Console]::Error.WriteLine('REFUSED:' + $reason)
  exit 1
} finally {
  if ($null -ne $gate) { $gate.Dispose() }
}
