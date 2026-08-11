# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
param(
    [ValidateSet("Install", "Repair", "Rollback", "Uninstall")]
    [string]$Action = "Install",
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA "Programs\Ember"),
    [string]$RepositoryRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$DesktopRoot = [Environment]::GetFolderPath("Desktop"),
    [string]$StartMenuProgramsRoot = (Join-Path ([Environment]::GetFolderPath("StartMenu")) "Programs")
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$script:ManifestFields = @("schema_version", "source_commit", "executable_sha256", "executable_relative_path", "installed_at_utc", "previous_source_commit")
$script:VersionFields = @("schema_version", "source_commit", "executable_sha256", "executable_relative_path", "published_at_utc")
$script:OwnerFields = @("schema_version", "product")

function Write-AtomicJson([string]$Path, $Value) {
    $parent = Split-Path -Parent $Path
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    $temporary = Join-Path $parent ("." + [IO.Path]::GetFileName($Path) + "." + [Guid]::NewGuid().ToString("N") + ".tmp")
    try {
        $Value | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $temporary -Encoding UTF8
        Move-Item -LiteralPath $temporary -Destination $Path -Force
    }
    finally { if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Force } }
}

function Assert-ClosedObject($Value, [string[]]$Expected, [string]$Name) {
    $actual = @($Value.PSObject.Properties.Name | Sort-Object)
    $wanted = @($Expected | Sort-Object)
    if (($actual -join '|') -ne ($wanted -join '|')) { throw "$Name has missing or unknown fields." }
}

function Assert-SafeInstallRoot([string]$Root) {
    $full = [IO.Path]::GetFullPath($Root).TrimEnd('\', '/')
    $volume = [IO.Path]::GetPathRoot($full).TrimEnd('\', '/')
    if ([string]::IsNullOrWhiteSpace($full) -or $full.Equals($volume, [StringComparison]::OrdinalIgnoreCase)) {
        throw "The Ember install root cannot be a filesystem root."
    }
}

function Assert-OwnedInstallRoot([string]$Root) {
    $path = Join-Path $Root "install-owner.json"
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "The target is not an owned Ember installation." }
    $owner = Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-ClosedObject $owner $script:OwnerFields "install-owner.json"
    if ($owner.schema_version -ne 1 -or $owner.product -ne "ember") { throw "The Ember installation ownership record is invalid." }
}

function Read-VersionRecord([string]$Root, [string]$Commit) {
    if ($Commit -notmatch '^[0-9a-f]{40}$') { throw "Rollback source commit is invalid." }
    $path = Join-Path $Root "versions\$Commit\version.json"
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Rollback version.json is absent." }
    $record = Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-ClosedObject $record $script:VersionFields "version.json"
    if ($record.schema_version -ne 1 -or $record.source_commit -ne $Commit -or
        $record.executable_sha256 -notmatch '^[0-9a-f]{64}$' -or $record.executable_relative_path -ne "Ember.exe") {
        throw "version.json is invalid."
    }
    $published = [DateTime]::MinValue
    if (-not [DateTime]::TryParse($record.published_at_utc, [ref]$published)) { throw "version.json publication time is invalid." }
    $exe = Join-Path $Root "versions\$Commit\Ember.exe"
    if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) { throw "Rollback executable is absent." }
    $hash = (Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($hash -ne $record.executable_sha256) { throw "Rollback executable hash does not match version.json." }
    return $record
}

function Get-ShortcutSpecification([string]$Root, [string]$IconPath) {
    $powershell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
    [pscustomobject]@{
        TargetPath = $powershell
        Arguments = '-NoLogo -NoProfile -ExecutionPolicy Bypass -File "' + (Join-Path $Root "launch-installed-ember.ps1") + '"'
        WorkingDirectory = $Root
        Description = "Ember local AI laboratory"
        IconLocation = "$IconPath,0"
    }
}

function Write-VerifiedShortcut([string]$Path, $Specification) {
    $parent = Split-Path -Parent $Path
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    $temporary = Join-Path $parent (".Ember." + [Guid]::NewGuid().ToString("N") + ".lnk")
    $shell = New-Object -ComObject WScript.Shell
    try {
        $shortcut = $shell.CreateShortcut($temporary)
        foreach ($field in @("TargetPath", "Arguments", "WorkingDirectory", "Description", "IconLocation")) { $shortcut.$field = $Specification.$field }
        $shortcut.Save()
        $readback = $shell.CreateShortcut($temporary)
        foreach ($field in @("TargetPath", "Arguments", "WorkingDirectory", "Description", "IconLocation")) {
            if ($readback.$field -ne $Specification.$field) { throw "Shortcut readback mismatch for $field." }
        }
        Move-Item -LiteralPath $temporary -Destination $Path -Force
    }
    finally {
        if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Force }
        [Runtime.InteropServices.Marshal]::FinalReleaseComObject($shell) | Out-Null
    }
}

function Install-StableFiles([string]$Root) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot "launch-installed-ember.ps1") -Destination (Join-Path $Root "launch-installed-ember.ps1") -Force
    @(
        '@echo off'
        'powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0launch-installed-ember.ps1"'
        'exit /b %ERRORLEVEL%'
    ) | Set-Content -LiteralPath (Join-Path $Root "Ember.cmd") -Encoding ASCII
    # A compiled deployment is intentionally git-less. These marker bytes let the existing
    # strict runtime resolver bind state to the installation itself instead of a checkout.
    "# Installed Ember application root`n" | Set-Content -LiteralPath (Join-Path $Root "docs/authority/GOAL.md") -Encoding UTF8
    New-Item -ItemType Directory -Force -Path (Join-Path $Root "tools\ember-cli") | Out-Null
}

function Read-Current([string]$Root) {
    $path = Join-Path $Root "current.json"
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { return $null }
    $value = Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-ClosedObject $value $script:ManifestFields "current.json"
    if ($value.schema_version -ne 1 -or $value.source_commit -notmatch '^[0-9a-f]{40}$' -or
        $value.executable_sha256 -notmatch '^[0-9a-f]{64}$' -or
        $value.executable_relative_path -ne "versions/$($value.source_commit)/Ember.exe" -or
        ($value.previous_source_commit -ne "" -and $value.previous_source_commit -notmatch '^[0-9a-f]{40}$')) {
        throw "current.json is invalid."
    }
    $installed = [DateTime]::MinValue
    if (-not [DateTime]::TryParse($value.installed_at_utc, [ref]$installed)) { throw "current.json installation time is invalid." }
    return $value
}

function Repair-Shortcuts([string]$Root, $Manifest, [string]$Desktop, [string]$StartMenu) {
    $exe = Join-Path $Root ($Manifest.executable_relative_path.Replace('/', '\'))
    $spec = Get-ShortcutSpecification $Root $exe
    Write-VerifiedShortcut (Join-Path $Desktop "Ember.lnk") $spec
    Write-VerifiedShortcut (Join-Path $StartMenu "Ember.lnk") $spec
}

function Write-DeploymentReceipt([string]$Root, [string]$Operation, [string]$Verdict, [string]$SourceCommit, [string]$ExecutableHash, [string]$ErrorClass = "") {
    if (-not (Test-Path -LiteralPath $Root -PathType Container)) { return }
    Write-AtomicJson (Join-Path $Root "install-receipt.json") ([ordered]@{
        schema_version = 1; action = $Operation; verdict = $Verdict; source_commit = $SourceCommit
        executable_sha256 = $ExecutableHash; shortcut_kinds = @("desktop", "start_menu")
        error_class = $ErrorClass; recorded_at_utc = [DateTime]::UtcNow.ToString("o")
    })
}

function Remove-OwnedShortcut([string]$Path, [string]$Root) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return }
    $shell = New-Object -ComObject WScript.Shell
    try {
        $shortcut = $shell.CreateShortcut($Path)
        $ownedLauncher = Join-Path $Root "launch-installed-ember.ps1"
        $powershell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
        $expectedArguments = '-NoLogo -NoProfile -ExecutionPolicy Bypass -File "' + $ownedLauncher + '"'
        if ($shortcut.TargetPath -ne $powershell -or $shortcut.Arguments -ne $expectedArguments -or
            $shortcut.WorkingDirectory -ne $Root -or $shortcut.Description -ne "Ember local AI laboratory") {
            throw "Refusing to remove a foreign Ember shortcut."
        }
        Remove-Item -LiteralPath $Path -Force
    }
    finally { [Runtime.InteropServices.Marshal]::FinalReleaseComObject($shell) | Out-Null }
}

if ($env:EMBER_DESKTOP_INSTALL_LIBRARY_ONLY -eq "1") { return }

$root = [IO.Path]::GetFullPath($InstallRoot)
try {
    Assert-SafeInstallRoot $root
    if ($Action -eq "Uninstall") {
        Assert-OwnedInstallRoot $root
        Remove-OwnedShortcut (Join-Path $DesktopRoot "Ember.lnk") $root
        Remove-OwnedShortcut (Join-Path $StartMenuProgramsRoot "Ember.lnk") $root
        if (Test-Path -LiteralPath $root) { Remove-Item -LiteralPath $root -Recurse -Force }
        Write-Output "Ember uninstalled."
        exit 0
    }

    New-Item -ItemType Directory -Force -Path $root | Out-Null
    $ownerPath = Join-Path $root "install-owner.json"
    if (Test-Path -LiteralPath $ownerPath -PathType Leaf) {
        Assert-OwnedInstallRoot $root
    }
    else {
        Write-AtomicJson $ownerPath ([ordered]@{ schema_version = 1; product = "ember" })
    }
    if ($Action -eq "Repair") {
        $current = Read-Current $root
        if ($null -eq $current) { throw "Repair requires an installed current.json." }
        $record = Read-VersionRecord $root $current.source_commit
        if ($record.executable_sha256 -ne $current.executable_sha256 -or
            $current.executable_relative_path -ne "versions/$($record.source_commit)/Ember.exe") {
            throw "current.json does not match the authenticated version record."
        }
        Install-StableFiles $root
        Repair-Shortcuts $root $current $DesktopRoot $StartMenuProgramsRoot
        Write-DeploymentReceipt $root $Action "PASS" $current.source_commit $current.executable_sha256
        Write-Output "Ember repaired."
        exit 0
    }

    if ($Action -eq "Rollback") {
        $current = Read-Current $root
        if ($null -eq $current -or [string]::IsNullOrWhiteSpace($current.previous_source_commit)) { throw "No authenticated previous Ember version is available." }
        $record = Read-VersionRecord $root $current.previous_source_commit
        $replacement = [ordered]@{
            schema_version = 1; source_commit = $record.source_commit; executable_sha256 = $record.executable_sha256
            executable_relative_path = "versions/$($record.source_commit)/Ember.exe"; installed_at_utc = [DateTime]::UtcNow.ToString("o")
            previous_source_commit = $current.source_commit
        }
        Install-StableFiles $root
        Repair-Shortcuts $root $replacement $DesktopRoot $StartMenuProgramsRoot
        Write-AtomicJson (Join-Path $root "current.json") $replacement
        Write-DeploymentReceipt $root $Action "PASS" $replacement.source_commit $replacement.executable_sha256
        Write-Output "Ember rolled back to $($replacement.source_commit)."
        exit 0
    }

    $status = & git -C $RepositoryRoot status --porcelain --untracked-files=no
    if ($LASTEXITCODE -ne 0 -or -not [string]::IsNullOrWhiteSpace(($status -join "`n"))) { throw "Installation requires a clean tracked source checkout." }
    $commit = (& git -C $RepositoryRoot rev-parse HEAD | Select-Object -First 1).Trim()
    $lines = @(& (Join-Path $RepositoryRoot "scripts\launch-ember-cli.ps1") -PrepareApplicationOnly)
    $built = @($lines | Where-Object {
        $_ -is [string] -and -not [string]::IsNullOrWhiteSpace($_) -and
        (Test-Path -LiteralPath $_ -PathType Leaf)
    } | Select-Object -Last 1)[0]
    if ($commit -notmatch '^[0-9a-f]{40}$') { throw "Installation requires an exact lowercase source commit." }
    if (-not (Test-Path -LiteralPath $built -PathType Leaf)) { throw "The canonical build did not return an executable." }
    $hash = (Get-FileHash -LiteralPath $built -Algorithm SHA256).Hash.ToLowerInvariant()
    $versionRoot = Join-Path $root "versions\$commit"
    $existing = Join-Path $versionRoot "Ember.exe"
    if (Test-Path -LiteralPath $existing -PathType Leaf) {
        if ((Get-FileHash -LiteralPath $existing -Algorithm SHA256).Hash.ToLowerInvariant() -ne $hash) { throw "Immutable Ember version bytes differ for the same source commit." }
        [void](Read-VersionRecord $root $commit)
    }
    else {
        $stage = Join-Path $root (".publish-" + [Guid]::NewGuid().ToString("N"))
        New-Item -ItemType Directory -Force -Path $stage | Out-Null
        try {
            Copy-Item -LiteralPath $built -Destination (Join-Path $stage "Ember.exe")
            Write-AtomicJson (Join-Path $stage "version.json") ([ordered]@{
                schema_version = 1; source_commit = $commit; executable_sha256 = $hash
                executable_relative_path = "Ember.exe"; published_at_utc = [DateTime]::UtcNow.ToString("o")
            })
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $versionRoot) | Out-Null
            Move-Item -LiteralPath $stage -Destination $versionRoot
        }
        finally { if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force } }
    }
    $prior = Read-Current $root
    $previous = if ($null -eq $prior -or $prior.source_commit -eq $commit) { "" } else { $prior.source_commit }
    $manifest = [ordered]@{
        schema_version = 1; source_commit = $commit; executable_sha256 = $hash
        executable_relative_path = "versions/$commit/Ember.exe"; installed_at_utc = [DateTime]::UtcNow.ToString("o")
        previous_source_commit = $previous
    }
    Install-StableFiles $root
    Repair-Shortcuts $root $manifest $DesktopRoot $StartMenuProgramsRoot
    Write-AtomicJson (Join-Path $root "current.json") $manifest
    Write-DeploymentReceipt $root $Action "PASS" $commit $hash
    Write-Output "Ember installed at source $commit."
}
catch {
    try { Write-DeploymentReceipt $root $Action "REFUSED" "" "" $_.Exception.GetType().Name } catch {}
    [Console]::Error.WriteLine("Ember deployment refused: " + $_.Exception.Message)
    exit 1
}
