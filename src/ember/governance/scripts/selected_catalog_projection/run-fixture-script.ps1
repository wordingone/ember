# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
param([string]$ScriptPath,[string]$ArgumentsJson,[string]$GateName)
$ErrorActionPreference='Stop'
$gate=[Threading.EventWaitHandle]::OpenExisting($GateName)
try{
  if(-not $gate.WaitOne([TimeSpan]::FromSeconds(900))){throw 'FIXTURE_GATE_TIMEOUT'}
  $params=ConvertFrom-Json -InputObject $ArgumentsJson -AsHashtable
  & $ScriptPath @params
  if($null -ne $LASTEXITCODE -and $LASTEXITCODE -ne 0){exit $LASTEXITCODE}
}finally{$gate.Dispose()}
