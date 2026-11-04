# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
#Requires -Version 5.1
<#
.SYNOPSIS
  One-command setup for ember-cli in open-weights mode (Windows).

.DESCRIPTION
  Checks the prerequisites, installs Bun if it is missing (after telling you and asking),
  installs the ember-cli dependencies, then runs `ember pull`: it picks a model that fits
  this GPU, fetches the official llama.cpp runtime if there is none, downloads the model,
  proves it loads and calibrates it.  Every step is skipped when it is already done, so
  running this again is safe and ends with "nothing to do".

  Guide: docs\ember-cli\INSTALL.md

.PARAMETER EmberHome
  Where ember keeps its configuration, models.json, the fetched llama.cpp runtime and
  (by default) the models.  Default: the EMBER_HOME environment variable, else ~\.ember.
  A non-default value is only valid for this run: set EMBER_HOME yourself to keep it.

.PARAMETER ModelsDir
  Where the model files go (15-20 GB).  Default: <EmberHome>\models.

.PARAMETER Model
  Pull this model instead of the one ember would pick, e.g. unsloth/Qwen3.8-27B-GGUF:UD-Q4_K_XL.
  Also the way to reuse a GGUF you already have: point -ModelsDir at the folder that holds it.

.PARAMETER DryRun
  Do everything except the model download: the last step runs `ember pull --dry-run`, which
  prints the model, quant and context it would pick and changes nothing.

.PARAMETER SkipModel
  Install Bun and the dependencies only; do not run `ember pull`.

.PARAMETER Repull
  Run `ember pull` even though a working model is already selected.

.PARAMETER AllowNoGpu
  Continue without an NVIDIA GPU.  ember then plans for the smallest model on the CPU, and
  you must provide a CPU llama-server yourself (set EMBER_LLAMA_SERVER).

.PARAMETER Yes
  Do not ask before installing Bun (for unattended runs).

.PARAMETER PullArgs
  Extra arguments passed to `ember pull`, e.g. -PullArgs '--no-calibrate'.

.EXAMPLE
  .\Ember-Open-Setup.cmd
.EXAMPLE
  .\Ember-Open-Setup.cmd -DryRun
.EXAMPLE
  .\Ember-Open-Setup.cmd -ModelsDir D:\llm-models -Yes
#>
[CmdletBinding()]
param(
  [string]$EmberHome,
  [string]$ModelsDir,
  [string]$Model,
  [switch]$DryRun,
  [switch]$SkipModel,
  [switch]$Repull,
  [switch]$AllowNoGpu,
  [switch]$Yes,
  [string[]]$PullArgs
)

$ErrorActionPreference = 'Stop'
$MinBun = [version]'1.2.0'
$Done = New-Object System.Collections.Generic.List[string]
$Kept = New-Object System.Collections.Generic.List[string]

function Say([string]$m) { Write-Host $m }
function Step([string]$m) { Write-Host ''; Write-Host "== $m" -ForegroundColor Cyan }
function Ok([string]$m) { Write-Host "  [ok]   $m" -ForegroundColor Green }
function Warn([string]$m) { Write-Host "  [warn] $m" -ForegroundColor Yellow }
function Stop-Setup([string]$what, [string]$fix, [int]$code) {
  Write-Host ''
  Write-Host "  [FAIL] $what" -ForegroundColor Red
  if ($fix) { Write-Host "         Fix: $fix" }
  Write-Host ''
  Write-Host 'Nothing is left half-done: fix the item above and run this command again; finished steps are skipped.'
  exit $code
}

function Confirm-Action([string]$question) {
  if ($Yes) { return $true }
  $interactive = [Environment]::UserInteractive -and -not [Console]::IsInputRedirected
  if (-not $interactive) { return $false }
  $a = Read-Host "$question [y/N]"
  return ($a -match '^(y|yes)$')
}

function Find-Bun {
  # Prefer a real executable or .cmd shim over a bun.ps1 shim (a .ps1 needs a permissive execution policy).
  $c = Get-Command bun -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
  if (-not $c) { $c = Get-Command bun -ErrorAction SilentlyContinue | Select-Object -First 1 }
  if ($c) { return $c.Source }
  $p = Join-Path $env:USERPROFILE '.bun\bin\bun.exe'
  if (Test-Path -LiteralPath $p) { return $p }
  return $null
}

try {
  Say 'ember-cli open-weights setup'
  if ($DryRun) { Say '(dry run: the model step only plans, nothing is downloaded)' }

  # ---- locate the checkout -------------------------------------------------
  $RepoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..\..\..\..\..'))
  $CliSrc = Join-Path $RepoRoot 'src\ember\infrastructure\tools\ember-cli\src'
  $Main = Join-Path $CliSrc 'entrypoints\main.ts'
  $Launcher = Join-Path $RepoRoot 'Ember-Open.cmd'
  if (-not ((Test-Path -LiteralPath $Main) -and (Test-Path -LiteralPath $Launcher))) {
    Stop-Setup "This does not look like a full ember checkout (missing $Main or $Launcher)." 'Clone the whole repository (git clone <repo-url>) and run Ember-Open-Setup.cmd from its root folder.' 1
  }

  if ($EmberHome) { $env:EMBER_HOME = [System.IO.Path]::GetFullPath($EmberHome) }
  $EmberHomeDir = $env:EMBER_HOME
  if (-not $EmberHomeDir) { $EmberHomeDir = Join-Path $env:USERPROFILE '.ember' }
  $env:EMBER_SOURCE_ROOT = $RepoRoot
  $ModelsJson = Join-Path $EmberHomeDir 'models.json'

  # ---- 1. prerequisites ----------------------------------------------------
  Step '1/5  Prerequisites'

  $isWin = ($env:OS -eq 'Windows_NT')
  if (-not $isWin) {
    Stop-Setup 'This setup script is for Windows 10/11.' 'On Linux/macOS follow the manual steps in docs/ember-cli/INSTALL.md (they are not tested yet).' 1
  }
  if ([Environment]::OSVersion.Version.Major -lt 10) {
    Stop-Setup "Windows $([Environment]::OSVersion.Version) is too old; ember-cli needs Windows 10 or 11." 'Update Windows.' 1
  }
  Ok "Windows $([Environment]::OSVersion.Version)"

  $git = Get-Command git -ErrorAction SilentlyContinue
  if ($git) { Ok "git: $($git.Source)" } else { Warn 'git was not found on PATH. ember-cli still starts, but the agent cannot use git until you install Git for Windows (https://git-scm.com).' }

  $smi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
  $gpuOk = $false
  if (-not $smi) {
    if ($AllowNoGpu) {
      Warn 'No nvidia-smi: continuing without a GPU (-AllowNoGpu). Set EMBER_LLAMA_SERVER to a CPU llama-server; only the smallest model is considered.'
    } else {
      Stop-Setup 'No NVIDIA driver found (nvidia-smi is not on PATH).' 'Install the current NVIDIA driver (https://www.nvidia.com/Download/index.aspx) and run this again. Without a GPU, add -AllowNoGpu and provide a CPU build of llama-server through EMBER_LLAMA_SERVER.' 2
    }
  } else {
    $gpuLine = & $smi.Source --query-gpu=name,memory.total,driver_version,memory.free --format=csv,noheader,nounits
    if ($LASTEXITCODE -ne 0 -or -not $gpuLine) {
      Stop-Setup 'nvidia-smi is installed but cannot talk to the GPU driver.' 'Reboot, or reinstall the NVIDIA driver, then run this again.' 2
    }
    $first = ($gpuLine | Select-Object -First 1).ToString().Split(',') | ForEach-Object { $_.Trim() }
    $gpuName = $first[0]
    $vramMiB = [int]$first[1]
    $driver = $first[2]
    $vramFreeMiB = [int]$first[3]
    $header = (& $smi.Source) -join "`n"
    $cuda = 0
    if ($header -match 'CUDA(?: UMD)? Version:\s*(\d+)\.(\d+)') { $cuda = [int]$Matches[1] }
    elseif ($driver -match '^(\d+)\.') { if ([int]$Matches[1] -ge 580) { $cuda = 13 } elseif ([int]$Matches[1] -ge 525) { $cuda = 12 } }
    if ($cuda -lt 12) {
      Stop-Setup "NVIDIA driver $driver supports CUDA $cuda; the llama.cpp builds ember fetches need CUDA 12 or newer (driver 525 or newer)." 'Update the NVIDIA driver and run this again.' 2
    }
    $gpuOk = $true
    Ok ("GPU: $gpuName, {0:N1} GiB VRAM, driver $driver (CUDA $cuda)" -f ($vramMiB / 1024))
    if ($vramMiB -lt 6000) { Warn 'Under 6 GiB of VRAM: only the 4B model fits, with a short context.' }
    if ($vramMiB -ge 6000 -and $vramFreeMiB -lt 6000) {
      Warn (('Only {0:N1} GiB of the VRAM is free right now: another program is using the GPU (see nvidia-smi). ember pull sizes the model to the FREE memory, so close that program first, or no model may fit.') -f ($vramFreeMiB / 1024))
    }
  }

  $target = $ModelsDir
  if (-not $target) { $target = Join-Path $EmberHomeDir 'models' }
  try {
    $root = [System.IO.Path]::GetPathRoot([System.IO.Path]::GetFullPath($target))
    $drive = New-Object System.IO.DriveInfo($root)
    $freeGiB = $drive.AvailableFreeSpace / 1GB
    if ($freeGiB -lt 30) {
      Warn ("Only {0:N0} GiB free on {1}; the 27B model needs about 30 GiB (ember pull checks the exact size of the model it picks). Use -ModelsDir to choose another drive." -f $freeGiB, $root)
    } else {
      Ok ("Disk: {0:N0} GiB free on {1} (models go to $target)" -f $freeGiB, $root)
    }
  } catch {
    Warn "Could not measure free disk space for $target; ember pull checks it again before downloading."
  }

  # ---- 2. Bun ----------------------------------------------------------------
  Step '2/5  Bun (the JavaScript runtime ember-cli runs on)'
  $Bun = Find-Bun
  if (-not $Bun) {
    Say '  Bun is not installed.'
    Say '  This script can install it with the official installer: powershell -c "irm bun.sh/install.ps1 | iex"'
    Say '  (installs into %USERPROFILE%\.bun, user scope, no administrator rights; it adds that folder to your user PATH).'
    if (-not (Confirm-Action '  Install Bun now?')) {
      Stop-Setup 'Bun is required and was not installed.' 'Run this again with -Yes to let it install Bun, or install Bun from https://bun.sh yourself and run this again.' 3
    }
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    & powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -Command 'irm bun.sh/install.ps1 | iex' | Out-Host
    if ($LASTEXITCODE -ne 0) {
      Stop-Setup "The Bun installer failed (exit code $LASTEXITCODE)." 'Check the internet connection and any proxy or antivirus block on bun.sh, or install Bun from https://bun.sh yourself, then run this again.' 3
    }
    $env:Path = (Join-Path $env:USERPROFILE '.bun\bin') + ';' + $env:Path
    $Bun = Find-Bun
    if (-not $Bun) {
      Stop-Setup 'The Bun installer finished but bun.exe is not where it should be (%USERPROFILE%\.bun\bin).' 'Open a new terminal and run this again; if it persists, install Bun manually from https://bun.sh.' 3
    }
    $Done.Add('installed Bun')
  }
  $bunVersionText = ((& $Bun --version) | Select-Object -First 1).ToString().Trim()
  $bunVersion = $null
  try { $bunVersion = [version]($bunVersionText -replace '[^0-9.].*$', '') } catch { $bunVersion = $null }
  if (-not $bunVersion -or $bunVersion -lt $MinBun) {
    Stop-Setup "Bun $bunVersionText is older than the $MinBun that ember-cli's lockfile needs." 'Run: bun upgrade   (or reinstall from https://bun.sh), then run this again.' 3
  }
  Ok "Bun $bunVersionText ($Bun)"
  if (-not $Done.Contains('installed Bun')) { $Kept.Add("Bun $bunVersionText") }

  # ---- 3. dependencies -------------------------------------------------------
  Step '3/5  ember-cli dependencies'
  $hadModules = Test-Path -LiteralPath (Join-Path $CliSrc 'node_modules')
  Push-Location $CliSrc
  try {
    & $Bun install --production --frozen-lockfile | Out-Host
    $rc = $LASTEXITCODE
  } finally {
    Pop-Location
  }
  if ($rc -ne 0) {
    Stop-Setup "bun install failed (exit code $rc)." 'Check the internet connection (registry.npmjs.org) and that the checkout is not read-only, then run this again. If the lockfile is reported as out of date, run git status: the checkout has local changes to src/ember/infrastructure/tools/ember-cli/src/package.json or bun.lock.' 4
  }
  $version = & $Bun run $Main --version
  if ($LASTEXITCODE -ne 0) {
    Stop-Setup 'ember-cli does not start after the install (bun run main.ts --version failed).' 'Run: bun run src\ember\infrastructure\tools\ember-cli\src\entrypoints\main.ts --version  and read the error. Delete src\ember\infrastructure\tools\ember-cli\src\node_modules and run this again for a clean install.' 4
  }
  Ok ("ember-cli starts: " + (($version | Select-Object -First 1).ToString().Trim()))
  if ($hadModules) { $Kept.Add('ember-cli dependencies (re-checked, no changes needed)') } else { $Done.Add('installed ember-cli dependencies') }

  # ---- 4. model ----------------------------------------------------------------
  Step '4/5  Model and llama.cpp runtime'
  $ready = $false
  $current = $null
  if (Test-Path -LiteralPath $ModelsJson) {
    try { $current = Get-Content -Raw -LiteralPath $ModelsJson | ConvertFrom-Json } catch { $current = $null }
  }
  if ($current -and $current.seat -eq 'open-weights' -and $current.model -and $current.binary -and
      (Test-Path -LiteralPath $current.model) -and (Test-Path -LiteralPath $current.binary)) {
    $ready = $true
  }
  if ($SkipModel) {
    Warn 'Skipping the model step (-SkipModel). Run: Ember-Open pull   when you are ready.'
  } elseif ($ready -and -not $Repull) {
    $ctxText = ''
    if ($current.nCtx) { $ctxText = ", context $($current.nCtx)" }
    Ok "A model is already selected: $($current.modelName)$ctxText ($ModelsJson). Not downloading again."
    Say '         To pick a different model: -Repull.  To re-measure the speed/context settings: Ember-Open pull --calibrate'
    $Kept.Add("model $($current.modelName)")
  } else {
    $pull = @('pull')
    if ($DryRun) { $pull += '--dry-run' }
    if ($ModelsDir) { $pull += @('--models-dir', $ModelsDir) }
    if ($Model) { $pull += $Model }
    if ($PullArgs) { $pull += $PullArgs }
    Say ("  Running: ember " + ($pull -join ' '))
    if (-not $DryRun) { Say '  A model download is 15-20 GB for the larger models; it resumes if interrupted. Calibration then loads the model on the GPU for several minutes.' }
    & $Bun run $Main @pull | Out-Host
    $prc = $LASTEXITCODE
    if ($prc -ne 0) {
      $smokeLog = Join-Path $(if ($ModelsDir) { $ModelsDir } else { Join-Path $EmberHomeDir 'models' }) 'pull-smoke.log'
      switch ($prc) {
        2 { Stop-Setup 'ember pull could not get a llama.cpp runtime (see the lines above).' 'Check the internet connection to github.com, or point EMBER_LLAMA_SERVER at your own llama-server.exe, then run this again.' 5 }
        3 { Stop-Setup 'No model fits or loads on this machine right now.' "Close other programs that use the GPU (browsers with video, games, another model server; check nvidia-smi for free VRAM) and run this again, or choose a smaller model: Ember-Open pull Qwen/Qwen3-8B-GGUF:Q4_K_M . If a model was started, its load log is $smokeLog." 5 }
        default { Stop-Setup "ember pull failed (exit code $prc)." "Read the lines above. The load log, if any, is $smokeLog. Run this again to resume." 5 }
      }
    }
    if ($DryRun) { $Done.Add('planned the model download (ember pull --dry-run): nothing downloaded') } else { $Done.Add('selected and calibrated a model (ember pull)') }
  }

  # ---- 5. summary ----------------------------------------------------------------
  Step '5/5  Summary'
  if ($Done.Count -gt 0) { foreach ($d in $Done) { Ok "did: $d" } }
  if ($Kept.Count -gt 0) { foreach ($k in $Kept) { Ok "already in place: $k" } }
  if ($Done.Count -eq 0 -and -not $DryRun -and -not $SkipModel) { Say '  Nothing to do: everything was already set up.' }
  Say ''
  Say "ember home:  $EmberHomeDir"
  if ($EmberHome) {
    Say "             (set for this run only; to keep it run: setx EMBER_HOME `"$EmberHomeDir`"  and open a new terminal)"
  }
  Say ''
  if ($DryRun -or $SkipModel) {
    Say 'Next: run this again without -DryRun / -SkipModel to download and calibrate the model.'
  } else {
    Say 'Start ember from the folder you want to work in:'
    Say "  $Launcher"
    Say 'One headless task:'
    Say "  $Launcher -p `"your task`""
    Say 'Check each feature (web search, web fetch, computer use): docs\ember-cli\INSTALL.md, section "Check that each feature works".'
  }
  exit 0
} catch {
  Write-Host ''
  Write-Host "  [FAIL] Unexpected problem: $($_.Exception.Message)" -ForegroundColor Red
  Write-Host '         Fix: run this again; if it repeats, see "Troubleshooting" in docs\ember-cli\INSTALL.md and report this line.'
  exit 1
}
