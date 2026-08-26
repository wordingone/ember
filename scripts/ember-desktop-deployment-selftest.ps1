# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$installer = Join-Path $PSScriptRoot "install-ember-desktop.ps1"
$temporary = Join-Path ([IO.Path]::GetTempPath()) ("ember-desktop-selftest-" + [Guid]::NewGuid().ToString("N"))
$install = Join-Path $temporary "install"
$desktop = Join-Path $temporary "desktop"
$menu = Join-Path $temporary "menu"
$fake = Join-Path $temporary "Ember.exe"
$repository = Join-Path $temporary "repository"
$placementLog = Join-Path $temporary "window-placement.log"

function Assert-True([bool]$Condition, [string]$Message) { if (-not $Condition) { throw $Message } }
function Invoke-Deploy([string]$Action) {
    & $installer -Action $Action -InstallRoot $install -RepositoryRoot $repository -DesktopRoot $desktop -StartMenuProgramsRoot $menu
    if (-not $?) { throw "Deployment $Action failed." }
}

function Invoke-DeployExpectFailure([string]$Action) {
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $installer `
            -Action $Action -InstallRoot $install -RepositoryRoot $repository `
            -DesktopRoot $desktop -StartMenuProgramsRoot $menu 2>$null | Out-Null
        $childExit = $LASTEXITCODE
    }
    finally { $ErrorActionPreference = $previousPreference }
    if ($childExit -eq 0) { throw "Deployment $Action unexpectedly succeeded." }
}

function Get-TestCommit {
    $value = (& git -C $repository rev-parse HEAD | Select-Object -First 1).Trim()
    if ($value -notmatch '^[0-9a-f]{40}$') { throw "Could not resolve selftest commit." }
    return $value
}

try {
    New-Item -ItemType Directory -Force -Path $temporary | Out-Null
    Add-Type -TypeDefinition @"
public static class EmberDesktopExitProbe {
    public static int Main() { return 23; }
}
"@ -OutputAssembly $fake -OutputType ConsoleApplication
    New-Item -ItemType Directory -Force -Path (Join-Path $repository "scripts") | Out-Null
    foreach ($name in @("install-ember-desktop.ps1", "launch-installed-ember.ps1", "ember-window-placement.ps1")) {
        Copy-Item -LiteralPath (Join-Path $PSScriptRoot $name) -Destination (Join-Path $repository "scripts\$name")
    }
    $installer = Join-Path $repository "scripts\install-ember-desktop.ps1"
    $env:EMBER_SELFTEST_APPLICATION = $fake
    "param([switch]`$PrepareApplicationOnly)`nWrite-Host 'preparing fixture'`nWrite-Output ''`nWrite-Output `$env:EMBER_SELFTEST_APPLICATION`n" |
        Set-Content -LiteralPath (Join-Path $repository "scripts\launch-ember-cli.ps1") -Encoding UTF8
    "first`n" | Set-Content -LiteralPath (Join-Path $repository "tracked.txt") -Encoding UTF8
    & git -C $repository init --quiet --object-format=sha1
    & git -C $repository config user.name "Ember deployment selftest"
    & git -C $repository config user.email "selftest@invalid.local"
    & git -C $repository add scripts/launch-ember-cli.ps1 tracked.txt
    & git -C $repository commit --quiet -m "selftest first version"
    if ($LASTEXITCODE -ne 0) { throw "Could not create first selftest source commit." }
    $a = Get-TestCommit

    # Upgrade fixture: the pre-layout installer owned this exact root marker. A current
    # install must migrate it instead of leaving two authority markers for the strict
    # source-root resolver to reject.
    New-Item -ItemType Directory -Force -Path $install | Out-Null
    "# Installed Ember application root`n" | Set-Content -LiteralPath (Join-Path $install "GOAL.md") -Encoding UTF8
    Invoke-Deploy "Install"
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $install "GOAL.md"))) "Legacy installed authority marker survived upgrade."
    Assert-True (Test-Path -LiteralPath (Join-Path $install "docs\authority\GOAL.md") -PathType Leaf) "Canonical installed authority marker absent."
    Assert-True (Test-Path (Join-Path $desktop "Ember.lnk")) "Desktop shortcut absent."
    Assert-True (Test-Path (Join-Path $menu "Ember.lnk")) "Start Menu shortcut absent."
    Assert-True (Test-Path (Join-Path $install "versions\$a\version.json")) "Version record absent."
    $installedLauncher = Join-Path $install "launch-installed-ember.ps1"
    $installedPlacement = Join-Path $install "ember-window-placement.ps1"
    Assert-True (Test-Path -LiteralPath $installedLauncher -PathType Leaf) "Installed launcher absent."
    Assert-True (Test-Path -LiteralPath $installedPlacement -PathType Leaf) "Installed window-placement library absent."
    $shell = New-Object -ComObject WScript.Shell
    try {
        $shortcut = $shell.CreateShortcut((Join-Path $desktop "Ember.lnk"))
        Assert-True ($shortcut.TargetPath -like "*powershell.exe") "Shortcut target is not stable PowerShell."
        Assert-True ($shortcut.Arguments -like "*launch-installed-ember.ps1*") "Shortcut arguments do not bind installed launcher."
        Assert-True ($shortcut.IconLocation -like "*versions*$a*Ember.exe,0") "Shortcut icon is not the admitted version."
    }
    finally { [Runtime.InteropServices.Marshal]::FinalReleaseComObject($shell) | Out-Null }

    @"
function Get-EmberHostWindowHandle {
    Add-Content -LiteralPath '$($placementLog.Replace("'", "''"))' -Value 'bind'
    return [IntPtr]1
}
function Set-EmberWindowToLeftWorkArea([IntPtr]`$WindowHandle) {
    Add-Content -LiteralPath '$($placementLog.Replace("'", "''"))' -Value 'place'
    return [pscustomobject]@{ X = 0; Y = 0; Width = 1; Height = 1 }
}
"@ | Set-Content -LiteralPath $installedPlacement -Encoding UTF8
    $launchProcess = Start-Process -FilePath "powershell.exe" -ArgumentList @(
        "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", $installedLauncher,
        "-InstallRoot", $install
    ) -Wait -PassThru -WindowStyle Hidden
    Assert-True ($launchProcess.ExitCode -eq 23) "Installed launcher did not preserve the admitted executable exit code."
    Assert-True ((Get-Content -LiteralPath $placementLog) -join "," -eq "bind,place") "Installed launcher did not bind and place its host window before application launch."

    # Idempotent same-version install.
    Invoke-Deploy "Install"
    "second`n" | Set-Content -LiteralPath (Join-Path $repository "tracked.txt") -Encoding UTF8
    & git -C $repository add tracked.txt
    & git -C $repository commit --quiet -m "selftest second version"
    if ($LASTEXITCODE -ne 0) { throw "Could not create second selftest source commit." }
    $b = Get-TestCommit
    $beforeInterrupted = Get-Content (Join-Path $install "current.json") -Raw
    $env:EMBER_SELFTEST_APPLICATION = Join-Path $temporary "missing.exe"
    Invoke-DeployExpectFailure "Install"
    Assert-True ((Get-Content (Join-Path $install "current.json") -Raw) -eq $beforeInterrupted) "Interrupted publication changed current.json."
    $env:EMBER_SELFTEST_APPLICATION = $fake
    Invoke-Deploy "Install"

    Add-Content -LiteralPath (Join-Path $install "versions\$a\Ember.exe") -Value "rollback tamper"
    Invoke-DeployExpectFailure "Rollback"
    Assert-True ((Get-Content (Join-Path $install "current.json") -Raw | ConvertFrom-Json).source_commit -eq $b) "Refused rollback changed current.json."
    Copy-Item -LiteralPath $fake -Destination (Join-Path $install "versions\$a\Ember.exe") -Force
    Invoke-Deploy "Rollback"
    $current = Get-Content (Join-Path $install "current.json") -Raw | ConvertFrom-Json
    Assert-True ($current.source_commit -eq $a) "Rollback did not restore the authenticated version."

    # Installed launcher rejects unknown fields, traversal, and byte tampering before spawn.
    $saved = Get-Content (Join-Path $install "current.json") -Raw
    $bad = $saved | ConvertFrom-Json
    $bad | Add-Member -NotePropertyName foreign -NotePropertyValue 1
    $bad | ConvertTo-Json | Set-Content (Join-Path $install "current.json") -Encoding UTF8
    $env:EMBER_INSTALLED_LAUNCH_LIBRARY_ONLY = "1"
    . $installedLauncher
    $closed = $false
    try { Read-EmberInstalledManifest $install } catch { $closed = $true }
    Assert-True $closed "Unknown manifest field was accepted."
    $missing = $saved | ConvertFrom-Json
    $missing.PSObject.Properties.Remove("installed_at_utc")
    $missing | ConvertTo-Json | Set-Content (Join-Path $install "current.json") -Encoding UTF8
    $closed = $false
    try { Read-EmberInstalledManifest $install } catch { $closed = $true }
    Assert-True $closed "Missing manifest field was accepted."
    $saved | Set-Content (Join-Path $install "current.json") -Encoding UTF8
    $manifest = Read-EmberInstalledManifest $install
    $manifest.executable_relative_path = "../Ember.exe"
    $traversal = $false
    try { Resolve-EmberInstalledExecutable $install $manifest } catch { $traversal = $true }
    Assert-True $traversal "Traversal was accepted."
    Add-Content -LiteralPath (Join-Path $install "versions\$a\Ember.exe") -Value "tamper"
    $tamper = $false
    try { Resolve-EmberInstalledExecutable $install (Read-EmberInstalledManifest $install) } catch { $tamper = $true }
    Assert-True $tamper "Executable tampering was accepted."

    # Restore by rolling forward to b, repair shortcuts, then scoped uninstall.
    $bRecord = Get-Content (Join-Path $install "versions\$b\version.json") -Raw | ConvertFrom-Json
    $next = [ordered]@{ schema_version=1; source_commit=$b; executable_sha256=$bRecord.executable_sha256; executable_relative_path="versions/$b/Ember.exe"; installed_at_utc=[DateTime]::UtcNow.ToString("o"); previous_source_commit="" }
    $next | ConvertTo-Json | Set-Content (Join-Path $install "current.json") -Encoding UTF8
    Invoke-Deploy "Repair"
    $foreign = Join-Path $temporary "foreign.txt"
    "keep" | Set-Content $foreign
    Invoke-Deploy "Uninstall"
    Assert-True (-not (Test-Path $install)) "Install root survived uninstall."
    Assert-True (Test-Path $foreign) "Uninstall removed a foreign file."

    # A root marker not minted by this installer is never silently deleted as migration.
    New-Item -ItemType Directory -Force -Path $install | Out-Null
    $foreignMarker = "foreign authority`n"
    $foreignMarker | Set-Content -LiteralPath (Join-Path $install "GOAL.md") -Encoding UTF8
    $foreignMarkerStored = [IO.File]::ReadAllText((Join-Path $install "GOAL.md"))
    Invoke-DeployExpectFailure "Install"
    Assert-True ([IO.File]::ReadAllText((Join-Path $install "GOAL.md")) -eq $foreignMarkerStored) "Refused migration altered the foreign authority marker."

    # Matching characters in a foreign encoding are not installer-owned historical bytes.
    Remove-Item -LiteralPath $install -Recurse -Force
    New-Item -ItemType Directory -Force -Path $install | Out-Null
    $utf16Marker = Join-Path $install "GOAL.md"
    [IO.File]::WriteAllText($utf16Marker, "# Installed Ember application root`r`n", [Text.Encoding]::Unicode)
    $utf16Stored = [Convert]::ToBase64String([IO.File]::ReadAllBytes($utf16Marker))
    Invoke-DeployExpectFailure "Install"
    Assert-True ([Convert]::ToBase64String([IO.File]::ReadAllBytes($utf16Marker)) -eq $utf16Stored) "Refused migration altered the UTF-16 foreign marker."

    # An installer-owned byte sequence reached through a reparse component is foreign
    # custody and must not be removed through the alias.
    Remove-Item -LiteralPath $install -Recurse -Force
    $reparseTarget = Join-Path $temporary "reparse-install-target"
    New-Item -ItemType Directory -Force -Path $reparseTarget | Out-Null
    "# Installed Ember application root`n" | Set-Content -LiteralPath (Join-Path $reparseTarget "GOAL.md") -Encoding UTF8
    New-Item -ItemType Junction -Path $install -Target $reparseTarget | Out-Null
    Invoke-DeployExpectFailure "Install"
    Assert-True (Test-Path -LiteralPath (Join-Path $reparseTarget "GOAL.md") -PathType Leaf) "Refused reparse migration deleted the target marker."
    [IO.Directory]::Delete($install)

    # A failure after migration preflight must leave the previously launchable legacy
    # marker byte-exact; stable-file publication cannot delete it before later writes.
    New-Item -ItemType Directory -Force -Path $install | Out-Null
    $atomicMarker = Join-Path $install "GOAL.md"
    "# Installed Ember application root`n" | Set-Content -LiteralPath $atomicMarker -Encoding UTF8
    $atomicStored = [Convert]::ToBase64String([IO.File]::ReadAllBytes($atomicMarker))
    "block docs directory" | Set-Content -LiteralPath (Join-Path $install "docs") -Encoding UTF8
    Invoke-DeployExpectFailure "Install"
    Assert-True (Test-Path -LiteralPath $atomicMarker -PathType Leaf) "Failed stable-file publication deleted the legacy authority marker."
    Assert-True ([Convert]::ToBase64String([IO.File]::ReadAllBytes($atomicMarker)) -eq $atomicStored) "Failed stable-file publication altered the legacy authority marker."

    # A canonical marker path occupied by a directory must refuse before the valid
    # legacy marker can be removed or a temp file moved inside the directory.
    Remove-Item -LiteralPath $install -Recurse -Force
    New-Item -ItemType Directory -Force -Path (Join-Path $install "docs\authority\GOAL.md") | Out-Null
    $directoryCaseMarker = Join-Path $install "GOAL.md"
    "# Installed Ember application root`n" | Set-Content -LiteralPath $directoryCaseMarker -Encoding UTF8
    $directoryCaseStored = [Convert]::ToBase64String([IO.File]::ReadAllBytes($directoryCaseMarker))
    Invoke-DeployExpectFailure "Install"
    Assert-True ([Convert]::ToBase64String([IO.File]::ReadAllBytes($directoryCaseMarker)) -eq $directoryCaseStored) "Canonical-directory refusal altered the legacy marker."
    Assert-True (Test-Path -LiteralPath (Join-Path $install "docs\authority\GOAL.md") -PathType Container) "Canonical-directory refusal replaced the occupied destination."

    # The canonical parent itself is custody-bearing; a junction must not redirect the
    # canonical marker write into a foreign directory before legacy deletion.
    Remove-Item -LiteralPath $install -Recurse -Force
    New-Item -ItemType Directory -Force -Path (Join-Path $install "docs") | Out-Null
    $canonicalReparseTarget = Join-Path $temporary "canonical-reparse-target"
    New-Item -ItemType Directory -Force -Path $canonicalReparseTarget | Out-Null
    New-Item -ItemType Junction -Path (Join-Path $install "docs\authority") -Target $canonicalReparseTarget | Out-Null
    $canonicalReparseMarker = Join-Path $install "GOAL.md"
    "# Installed Ember application root`n" | Set-Content -LiteralPath $canonicalReparseMarker -Encoding UTF8
    $canonicalReparseStored = [Convert]::ToBase64String([IO.File]::ReadAllBytes($canonicalReparseMarker))
    Invoke-DeployExpectFailure "Install"
    Assert-True ([Convert]::ToBase64String([IO.File]::ReadAllBytes($canonicalReparseMarker)) -eq $canonicalReparseStored) "Canonical-reparse refusal altered the legacy marker."
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $canonicalReparseTarget "GOAL.md"))) "Canonical-reparse refusal wrote into foreign custody."
    [IO.Directory]::Delete((Join-Path $install "docs\authority"))

    # If the final legacy deletion itself is refused, roll back the newly published
    # canonical marker so the old installed application remains single-authority.
    Remove-Item -LiteralPath $install -Recurse -Force
    New-Item -ItemType Directory -Force -Path $install | Out-Null
    $lockedMarker = Join-Path $install "GOAL.md"
    "# Installed Ember application root`n" | Set-Content -LiteralPath $lockedMarker -Encoding UTF8
    $lockedStored = [Convert]::ToBase64String([IO.File]::ReadAllBytes($lockedMarker))
    $legacyLock = [IO.File]::Open($lockedMarker, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
    try { Invoke-DeployExpectFailure "Install" }
    finally { $legacyLock.Dispose() }
    Assert-True ([Convert]::ToBase64String([IO.File]::ReadAllBytes($lockedMarker)) -eq $lockedStored) "Failed legacy deletion altered the original marker."
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $install "docs\authority\GOAL.md"))) "Failed legacy deletion left a second authority marker."
    Write-Output "EMBER_DESKTOP_DEPLOYMENT_SELFTEST_PASS"
}
finally {
    Remove-Item Env:EMBER_INSTALLED_LAUNCH_LIBRARY_ONLY -ErrorAction SilentlyContinue
    Remove-Item Env:EMBER_SELFTEST_APPLICATION -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Recurse -Force }
}
