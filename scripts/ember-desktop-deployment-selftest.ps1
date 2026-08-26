# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$temporary = Join-Path ([IO.Path]::GetTempPath()) ("ember-desktop-selftest-" + [Guid]::NewGuid().ToString("N"))
$install = Join-Path $temporary "install"
$desktop = Join-Path $temporary "desktop"
$menu = Join-Path $temporary "menu"
$repository = Join-Path $temporary "repository"
$fakeApplication = Join-Path $temporary "Ember.exe"
$fakeRuntime = Join-Path $temporary "ember-lab.exe"
function Assert-True([bool]$Condition, [string]$Message) { if (-not $Condition) { throw $Message } }
function Invoke-Deploy([string]$Action) {
    & $script:Installer -Action $Action -InstallRoot $install -RepositoryRoot $repository -DesktopRoot $desktop -StartMenuProgramsRoot $menu
    if (-not $?) { throw "Deployment $Action failed." }
}
function Invoke-DeployExpectFailure([string]$Action) {
    $prior = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $script:Installer -Action $Action -InstallRoot $install -RepositoryRoot $repository -DesktopRoot $desktop -StartMenuProgramsRoot $menu 2>$null | Out-Null
        $code = $LASTEXITCODE
    } finally { $ErrorActionPreference = $prior }
    if ($code -eq 0) { throw "Deployment $Action unexpectedly succeeded." }
}
function Get-TestCommit {
    $value = (& git -C $repository rev-parse HEAD | Select-Object -First 1).Trim()
    if ($value -notmatch '^[0-9a-f]{40}$') { throw "Could not resolve selftest commit." }
    return $value
}
try {
    New-Item -ItemType Directory -Force -Path (Join-Path $repository "scripts") | Out-Null
    Add-Type -TypeDefinition 'namespace FixtureApp { public static class Program { public static int Main() { return 0; } } }' -OutputAssembly $fakeApplication -OutputType ConsoleApplication
    Add-Type -TypeDefinition 'namespace FixtureLab { public static class Program { public static int Main() { return 23; } } }' -OutputAssembly $fakeRuntime -OutputType ConsoleApplication
    foreach ($name in @("install-ember-desktop.ps1", "ember-window-placement.ps1")) {
        Copy-Item -LiteralPath (Join-Path $PSScriptRoot $name) -Destination (Join-Path $repository "scripts\$name")
    }
    $script:Installer = Join-Path $repository "scripts\install-ember-desktop.ps1"
    $env:EMBER_SELFTEST_APPLICATION = $fakeApplication
    $env:EMBER_SELFTEST_RUNTIME = $fakeRuntime
    @'
Write-Output ("EMBER_APPLICATION=" + $env:EMBER_SELFTEST_APPLICATION)
Write-Output ("EMBER_LAB=" + $env:EMBER_SELFTEST_RUNTIME)
'@ | Set-Content -LiteralPath (Join-Path $repository "scripts\prepare-ember-cockpit.ps1") -Encoding UTF8
    "first" | Set-Content -LiteralPath (Join-Path $repository "tracked.txt") -Encoding UTF8
    & git -C $repository init --quiet --object-format=sha1
    & git -C $repository config user.name "Ember deployment selftest"
    & git -C $repository config user.email "selftest@invalid.local"
    & git -C $repository add scripts tracked.txt
    & git -C $repository commit --quiet -m "selftest first version"
    if ($LASTEXITCODE -ne 0) { throw "Could not create first selftest source commit." }
    $a = Get-TestCommit
    New-Item -ItemType Directory -Force -Path $install | Out-Null
    "# Installed Ember application root" | Set-Content -LiteralPath (Join-Path $install "GOAL.md") -Encoding UTF8
    Invoke-Deploy "Install"
    $current = Get-Content (Join-Path $install "current.json") -Raw | ConvertFrom-Json
    Assert-True ($current.schema_version -eq 2) "Current deployment schema is not v2."
    Assert-True ($current.source_commit -eq $a) "Installed source identity is wrong."
    Assert-True (Test-Path (Join-Path $install "versions\$a\Ember.exe")) "Versioned cockpit absent."
    Assert-True (Test-Path (Join-Path $install "versions\$a\ember-lab.exe")) "Versioned governed runtime absent."
    Assert-True (-not (Test-Path (Join-Path $install "launch-installed-ember.ps1"))) "Legacy installed launcher survived."
    $shell = New-Object -ComObject WScript.Shell
    try {
        $shortcut = $shell.CreateShortcut((Join-Path $desktop "Ember.lnk"))
        Assert-True ($shortcut.TargetPath -eq (Join-Path $install "versions\$a\ember-lab.exe")) "Shortcut does not target governed runtime."
        Assert-True ($shortcut.Arguments -like "cockpit *--source-commit $a*") "Shortcut does not bind the Cockpit dispatch command."
        Assert-True ($shortcut.IconLocation -like "*versions*$a*Ember.exe,0") "Shortcut icon is not the admitted application."
    } finally { [Runtime.InteropServices.Marshal]::FinalReleaseComObject($shell) | Out-Null }
    Invoke-Deploy "Install"
    "second" | Set-Content -LiteralPath (Join-Path $repository "tracked.txt") -Encoding UTF8
    & git -C $repository add tracked.txt
    & git -C $repository commit --quiet -m "selftest second version"
    $b = Get-TestCommit
    $env:EMBER_SELFTEST_APPLICATION = Join-Path $temporary "missing.exe"
    $before = Get-Content (Join-Path $install "current.json") -Raw
    Invoke-DeployExpectFailure "Install"
    Assert-True ((Get-Content (Join-Path $install "current.json") -Raw) -eq $before) "Refused install changed current.json."
    $env:EMBER_SELFTEST_APPLICATION = $fakeApplication
    Invoke-Deploy "Install"
    Assert-True ((Get-Content (Join-Path $install "current.json") -Raw | ConvertFrom-Json).source_commit -eq $b) "Upgrade did not publish b."
    Add-Content -LiteralPath (Join-Path $install "versions\$a\ember-lab.exe") -Value "tamper"
    Invoke-DeployExpectFailure "Rollback"
    Copy-Item -LiteralPath $fakeRuntime -Destination (Join-Path $install "versions\$a\ember-lab.exe") -Force
    Invoke-Deploy "Rollback"
    Assert-True ((Get-Content (Join-Path $install "current.json") -Raw | ConvertFrom-Json).source_commit -eq $a) "Rollback did not restore a."
    Invoke-Deploy "Repair"
    $foreign = Join-Path $temporary "foreign.txt"
    "keep" | Set-Content $foreign
    Invoke-Deploy "Uninstall"
    Assert-True (-not (Test-Path $install)) "Install root survived uninstall."
    Assert-True (Test-Path $foreign) "Uninstall removed foreign data."
    Write-Output "EMBER_DESKTOP_DEPLOYMENT_SELFTEST_PASS"
}
finally {
    Remove-Item Env:EMBER_SELFTEST_APPLICATION -ErrorAction SilentlyContinue
    Remove-Item Env:EMBER_SELFTEST_RUNTIME -ErrorAction SilentlyContinue
    if (Test-Path $temporary) { Remove-Item -LiteralPath $temporary -Recurse -Force }
}
