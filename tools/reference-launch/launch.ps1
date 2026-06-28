param(
    [Parameter(ValueFromRemainingArguments=$true)]
    [string[]]$Args
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$entry = Join-Path $repo "scripts\ember_gate_launch_entry.py"
if (-not (Test-Path -LiteralPath $entry)) {
    throw "EMBER_GATE_LAUNCH_ENTRY_MISSING: $entry"
}
python $entry --repo $repo @Args
