param([string]$BindingPath)
$ErrorActionPreference = 'Stop'

$taskRoot = Split-Path -Parent $PSCommandPath
$baseRoot = Split-Path -Parent $taskRoot
$binding = Get-Content -LiteralPath $bindingPath -Raw | ConvertFrom-Json
$markerPath = [string]$binding.marker_path
$markerParent = Split-Path -Parent $markerPath
if (-not (Test-Path -LiteralPath $markerParent)) { throw 'GPU_MARKER_PARENT_UNAVAILABLE_STOP_A_READ' }
if (Test-Path -LiteralPath $markerPath) { throw 'GPU_WINDOW_MARKER_PRESENT_STOP_A_READ' }

$sourcePath = [string]$binding.source_path
$runnerPath = [string]$binding.runner_path
$sourceHash = (Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash.ToLowerInvariant()
$runnerHash = (Get-FileHash -LiteralPath $runnerPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($sourceHash -ne ([string]$binding.source_sha256).ToLowerInvariant()) { throw 'SOURCE_PIN_MISMATCH' }
if ($runnerHash -ne ([string]$binding.runner_sha256).ToLowerInvariant()) { throw 'RUNNER_PIN_MISMATCH' }

$predictionPath = [string]$binding.prediction_path
$predictionBytes = [IO.File]::ReadAllBytes($predictionPath)
$predictionHash = [Convert]::ToHexString([System.Security.Cryptography.SHA256]::HashData($predictionBytes)).ToLowerInvariant()
if ($predictionBytes.Length -ne [long]$binding.prediction_bytes) { throw 'BOUND_PREDICTION_SIZE_MISMATCH' }
if ($predictionHash -ne ([string]$binding.prediction_sha256).ToLowerInvariant()) { throw 'BOUND_PREDICTION_HASH_MISMATCH' }
$predictionText = [Text.UTF8Encoding]::new($false,$true).GetString($predictionBytes)
$predictionJson = ConvertFrom-Json -InputObject $predictionText -AsHashtable

$fixtureRoot = Join-Path $taskRoot ('validation-prediction-schema-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ') + '-' + [Guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($fixtureRoot) | Out-Null
$missingPath = Join-Path $fixtureRoot 'prediction-missing-input-tokenizer.json'
$mismatchPath = Join-Path $fixtureRoot 'prediction-tokenizer-digest-mismatch.json'
$negativeJson = ConvertTo-Json -InputObject $predictionJson -Depth 100 -Compress
$missingObject = ConvertFrom-Json -InputObject $negativeJson -AsHashtable
if (-not $missingObject.identity.input_binding.ContainsKey('tokenizer_sha256')) { throw 'NEGATIVE_FIXTURE_TARGET_MISSING_IN_SOURCE' }
[void]$missingObject.identity.input_binding.Remove('tokenizer_sha256')
$missingText = ConvertTo-Json -InputObject $missingObject -Depth 100 -Compress
[IO.File]::WriteAllText($missingPath,$missingText,[Text.UTF8Encoding]::new($false))
$missingBytes = [IO.File]::ReadAllBytes($missingPath)
$missingHash = [Convert]::ToHexString([System.Security.Cryptography.SHA256]::HashData($missingBytes)).ToLowerInvariant()

$mismatchObject = ConvertFrom-Json -InputObject $negativeJson -AsHashtable
$expectedBindingTokenizer = [string]$mismatchObject.identity.input_binding.tokenizer_sha256
$mismatchedDigest = '0' * 64
if ($mismatchedDigest -eq $expectedBindingTokenizer) { $mismatchedDigest = 'f' * 64 }
$mismatchObject.identity.data.tokenizer_sha256 = $mismatchedDigest
$mismatchText = ConvertTo-Json -InputObject $mismatchObject -Depth 100 -Compress
[IO.File]::WriteAllText($mismatchPath,$mismatchText,[Text.UTF8Encoding]::new($false))
$mismatchBytes = [IO.File]::ReadAllBytes($mismatchPath)
$mismatchHash = [Convert]::ToHexString([System.Security.Cryptography.SHA256]::HashData($mismatchBytes)).ToLowerInvariant()

Add-Type -Path $sourcePath -ErrorAction Stop
$runnerType = [AppDomain]::CurrentDomain.GetAssemblies() | ForEach-Object { $_.GetType('NikoSelectedProjection.Runner',$false) } | Where-Object { $null -ne $_ } | Select-Object -First 1
if ($null -eq $runnerType) { throw 'RUNNER_TYPE_NOT_LOADED' }
$bindingType = $runnerType.GetNestedType('Binding',[System.Reflection.BindingFlags]::Public)
$readFlags = [System.Reflection.BindingFlags]::Static -bor [System.Reflection.BindingFlags]::NonPublic
$readMethod = $runnerType.GetMethod('ReadPrediction',$readFlags)
if ($null -eq $bindingType -or $null -eq $readMethod) { throw 'READ_PREDICTION_REFLECTION_NOT_FOUND' }
$lastBytesField = $runnerType.GetField('LastAInputBytesRead',[System.Reflection.BindingFlags]::Public -bor [System.Reflection.BindingFlags]::Static)

function Invoke-ReadPrediction([string]$path,[long]$length,[string]$sha,[string]$marker,[string]$exportPath) {
  $object = [Activator]::CreateInstance($bindingType)
  $bindingType.GetField('prediction_path').SetValue($object,$path)
  $bindingType.GetField('prediction_bytes').SetValue($object,$length)
  $bindingType.GetField('prediction_sha256').SetValue($object,$sha)
  $bindingType.GetField('export_path').SetValue($object,$exportPath)
  $bindingType.GetField('marker_path').SetValue($object,$marker)
  $bindingType.GetField('tenant_declaration_path').SetValue($object,(Join-Path $fixtureRoot 'no-tenant.md'))
  $bindingType.GetField('tenant_declaration_key').SetValue($object,'third_tenant_1581_projection')
  $bindingType.GetField('tenant_command_sha_key').SetValue($object,'third_tenant_1581_command_sha256')
  $bindingType.GetField('max_tenant_declaration_bytes').SetValue($object,[long]65536)
  $bindingType.GetField('max_wall_seconds').SetValue($object,[long]60)
  $bindingType.GetField('max_total_bytes_read').SetValue($object,[long]1048576)
  $bindingType.GetField('max_private_bytes').SetValue($object,[long]536870912)
  $stopwatch = [Diagnostics.Stopwatch]::StartNew()
  $arguments = [object[]]@($object,$stopwatch,[long]0)
  $lastBytesField.SetValue($null,[long]0)
  try {
    $value = $readMethod.Invoke($null,$arguments)
    $type = $value.GetType()
    [ordered]@{
      passed = $true
      exception_type = $null
      exception_message = $null
      input_bytes_read = [long]$lastBytesField.GetValue($null)
      export_path = [string]$type.GetField('ExportPath').GetValue($value)
      export_sha256 = [string]$type.GetField('ExportSha').GetValue($value)
      tokenizer_sha256 = [string]$type.GetField('Tokenizer').GetValue($value)
      dataset_id_count = [int]$type.GetField('Ids').GetValue($value).Count
    }
  } catch {
    $cause = $_.Exception
    while ($null -ne $cause.InnerException) { $cause = $cause.InnerException }
    [ordered]@{
      passed = $false
      exception_type = [string]$cause.GetType().FullName
      exception_message = [string]$cause.Message
      input_bytes_read = [long]$lastBytesField.GetValue($null)
      export_path = $null
      export_sha256 = $null
      tokenizer_sha256 = $null
      dataset_id_count = $null
    }
  }
}

$realMixture = $predictionJson.identity.production_mixture
$expectedTokenizer = [string]$predictionJson.identity.input_binding.tokenizer_sha256
$expectedDataTokenizer = [string]$predictionJson.identity.data.tokenizer_sha256
$realResult = Invoke-ReadPrediction $predictionPath ([long]$predictionBytes.Length) $predictionHash (Join-Path $fixtureRoot 'no-marker') ([string]$binding.export_path)
$missingResult = Invoke-ReadPrediction $missingPath ([long]$missingBytes.Length) $missingHash (Join-Path $fixtureRoot 'no-marker') ([string]$binding.export_path)
$mismatchResult = Invoke-ReadPrediction $mismatchPath ([long]$mismatchBytes.Length) $mismatchHash (Join-Path $fixtureRoot 'no-marker') ([string]$binding.export_path)
$expectedMissingMessage = 'PREDICTION_KEY_MISSING:identity.input_binding.tokenizer_sha256'
$expectedMismatchMessage = 'PREDICTION_TOKENIZER_MISMATCH:identity.input_binding.tokenizer_sha256!=identity.data.tokenizer_sha256'
$assertions = [ordered]@{
  real_bound_prediction_read_succeeds = [bool]$realResult.passed
  real_prediction_export_path_matches_binding = (([string]$realResult.export_path).Replace('/','\').TrimEnd('\') -eq ([string]$binding.export_path).Replace('/','\').TrimEnd('\'))
  real_prediction_export_sha_is_valid = ([string]$realResult.export_sha256 -match '^[0-9a-fA-F]{64}$')
  real_prediction_tokenizer_matches_input_binding = ($realResult.tokenizer_sha256 -eq $expectedTokenizer)
  real_prediction_data_tokenizer_matches = ($expectedTokenizer -eq $expectedDataTokenizer)
  real_prediction_has_eight_dataset_ids = ([int]$realResult.dataset_id_count -eq 8)
  real_prediction_read_exact_bytes = ([long]$realResult.input_bytes_read -eq [long]$predictionBytes.Length)
  missing_input_binding_tokenizer_refuses = (-not [bool]$missingResult.passed)
  missing_error_names_exact_key_path = ($missingResult.exception_message -eq $expectedMissingMessage)
  missing_fixture_input_bytes_read_exact = ([long]$missingResult.input_bytes_read -eq [long]$missingBytes.Length)
  mismatched_tokenizer_refuses = (-not [bool]$mismatchResult.passed)
  mismatch_error_names_both_paths = ($mismatchResult.exception_message -eq $expectedMismatchMessage)
  mismatch_fixture_input_bytes_read_exact = ([long]$mismatchResult.input_bytes_read -eq [long]$mismatchBytes.Length)
  export_content_not_opened = $true
}
$result = [ordered]@{
  schema = 'niko.selected_catalog_projection.prediction_schema_validation.v2'
  observed_utc = [DateTime]::UtcNow.ToString('o')
  fixture_root = $fixtureRoot
  source_path = $sourcePath
  source_sha256 = $sourceHash
  runner_path = $runnerPath
  runner_sha256 = $runnerHash
  real_prediction_path = $predictionPath
  real_prediction_bytes = $predictionBytes.Length
  real_prediction_sha256 = $predictionHash
  real_prediction_key_audit_path = Join-Path $baseRoot 'prediction-key-audit-leo74156-20261009T0639Z.json'
  real_prediction_result = $realResult
  missing_key_path = 'identity.input_binding.tokenizer_sha256'
  missing_fixture_path = $missingPath
  missing_fixture_bytes = $missingBytes.Length
  missing_fixture_sha256 = $missingHash
  missing_result = $missingResult
  mismatch_paths = @('identity.input_binding.tokenizer_sha256','identity.data.tokenizer_sha256')
  mismatch_fixture_path = $mismatchPath
  mismatch_fixture_bytes = $mismatchBytes.Length
  mismatch_fixture_sha256 = $mismatchHash
  mismatch_fixture_data_tokenizer_sha256 = $mismatchedDigest
  mismatch_result = $mismatchResult
  export_content_opened = $false
  assertions = $assertions
  passed = (@($assertions.Values | Where-Object { -not $_ }).Count -eq 0)
}
$resultPath = Join-Path $fixtureRoot 'prediction-schema-validation.json'
[IO.File]::WriteAllText($resultPath,($result | ConvertTo-Json -Depth 12),[Text.UTF8Encoding]::new($false))
if (-not $result.passed) { Write-Output ($result | ConvertTo-Json -Depth 12); exit 1 }
Write-Output ($result | ConvertTo-Json -Depth 12)
