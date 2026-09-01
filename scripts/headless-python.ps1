# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
$ErrorActionPreference = "Stop"
$boundPython = $env:CODEX_PYTHON
if ([string]::IsNullOrWhiteSpace($boundPython)) {
    [Console]::Error.WriteLine("CODEX_PYTHON_REQUIRED")
    exit 64
}

try {
    $interpreter = (Get-Item -LiteralPath $boundPython -ErrorAction Stop)
} catch {
    [Console]::Error.WriteLine("CODEX_PYTHON_MISSING")
    exit 65
}
if ($interpreter.PSIsContainer) {
    [Console]::Error.WriteLine("CODEX_PYTHON_NOT_FILE")
    exit 66
}

$forwarded = @($args)
if ($forwarded.Count -gt 0 -and $forwarded[0] -eq "--") {
    $forwarded = @($forwarded | Select-Object -Skip 1)
}

& $interpreter.FullName @forwarded
exit $LASTEXITCODE
