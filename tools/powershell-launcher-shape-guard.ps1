# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('worktree', 'staged')]
    [string]$Scope,

    [Parameter(Mandatory = $true, ValueFromRemainingArguments = $true)]
    [string[]]$Paths
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$utf8Strict = [System.Text.UTF8Encoding]::new($false, $true)
$maximumBytes = 4MB

# PowerShell aliases are process-global and user-mutable. Only these literal spellings are
# interpreted, and every spelling here is pinned to the process-creation primitive it means.
# Unknown or dynamically constructed command targets are refused instead of resolved from the
# ambient alias table.
$processAliases = @{
    'saps' = 'Start-Process'
    'start' = 'Start-Process'
    'iex' = 'Invoke-Expression'
}

$processCommands = @(
    'Start-Process', 'Start-Job', 'Invoke-Expression'
)

$nativeCommandNames = @(
    'python', 'python2', 'python3', 'py', 'node', 'bun', 'cargo', 'rustc',
    'dotnet', 'cmd', 'powershell', 'pwsh', 'bash', 'wsl', 'torchrun', 'ember',
    'ember-lab'
)

function Get-TrackedText {
    param([Parameter(Mandatory = $true)][string]$Path)

    if ($Scope -eq 'worktree') {
        $item = Get-Item -LiteralPath $Path -ErrorAction Stop
        if ($item.Length -gt $maximumBytes) {
            throw "PowerShell source exceeds $maximumBytes bytes"
        }
        return [System.IO.File]::ReadAllText($item.FullName, $utf8Strict)
    }

    $sizeText = (& git cat-file -s ":$Path" 2>&1 | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or $sizeText -notmatch '^\d+$') {
        throw "cannot read staged PowerShell blob size"
    }
    if ([uint64]$sizeText -gt [uint64]$maximumBytes) {
        throw "staged PowerShell source exceeds $maximumBytes bytes"
    }
    $text = (& git show --no-textconv ":$Path" 2>&1 | Out-String)
    if ($LASTEXITCODE -ne 0) {
        throw "cannot read staged PowerShell blob"
    }
    if ($text.Contains([char]0xFFFD)) {
        throw "staged PowerShell source is not valid UTF-8"
    }
    return $text
}

function Test-NativeCommandName {
    param([Parameter(Mandatory = $true)][string]$Name)

    $leaf = [System.IO.Path]::GetFileName($Name).ToLowerInvariant()
    $stem = [System.IO.Path]::GetFileNameWithoutExtension($leaf)
    if ($leaf -match '\.(exe|com|bat|cmd)$') { return $true }
    if ($Name.Contains('/') -or $Name.Contains('\')) { return $true }
    if ($nativeCommandNames -contains $stem) { return $true }
    if ($stem -match '^python\d+(\.\d+)?$') { return $true }
    return $false
}

function Resolve-ScriptRootExpression {
    param(
        [Parameter(Mandatory = $true)]
        [System.Management.Automation.Language.Ast]$Node,
        [Parameter(Mandatory = $true)]
        [string]$SourcePath
    )

    $sourceFullPath = [System.IO.Path]::GetFullPath($SourcePath)
    if ($Node -is [System.Management.Automation.Language.VariableExpressionAst]) {
        if ($Node.VariablePath.UserPath -ieq 'PSScriptRoot') {
            return [System.IO.Path]::GetDirectoryName($sourceFullPath)
        }
        if ($Node.VariablePath.UserPath -ieq 'PSCommandPath') {
            return $sourceFullPath
        }
        return $null
    }
    if ($Node -is [System.Management.Automation.Language.ParenExpressionAst]) {
        $elements = @($Node.Pipeline.PipelineElements)
        if ($elements.Count -ne 1) { return $null }
        return Resolve-ScriptRootExpression -Node $elements[0] -SourcePath $SourcePath
    }
    if ($Node -is [System.Management.Automation.Language.CommandAst]) {
        $name = $Node.GetCommandName()
        $elements = @($Node.CommandElements)
        if ($name -ieq 'Join-Path' -and $elements.Count -eq 3) {
            $base = Resolve-ScriptRootExpression -Node $elements[1] -SourcePath $SourcePath
            $child = $elements[2]
            if (
                $null -eq $base -or
                $child -isnot [System.Management.Automation.Language.StringConstantExpressionAst] -or
                [string]::IsNullOrEmpty($child.Value) -or
                [System.IO.Path]::IsPathRooted($child.Value)
            ) {
                return $null
            }
            return [System.IO.Path]::GetFullPath((Join-Path $base $child.Value))
        }
        if ($name -ieq 'Split-Path' -and $elements.Count -eq 2) {
            $value = Resolve-ScriptRootExpression -Node $elements[1] -SourcePath $SourcePath
            if ($null -eq $value) { return $null }
            return [System.IO.Path]::GetDirectoryName($value)
        }
    }
    return $null
}

function Get-TrackedRepoRelativePath {
    param([Parameter(Mandatory = $true)][string]$Target)

    $repoRoot = [System.IO.Path]::GetFullPath((Get-Location).Path).TrimEnd('\', '/')
    $targetFullPath = [System.IO.Path]::GetFullPath($Target)
    $prefix = "$repoRoot$([System.IO.Path]::DirectorySeparatorChar)"
    if (-not $targetFullPath.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        return $null
    }
    $relative = $targetFullPath.Substring($prefix.Length).Replace('\', '/')
    if ([string]::IsNullOrWhiteSpace($relative)) { return $null }
    if ($Scope -eq 'worktree') {
        if (-not (Test-Path -LiteralPath $targetFullPath -PathType Leaf)) { return $null }
    } else {
        & git cat-file -e ":$relative" 2>$null
        if ($LASTEXITCODE -ne 0) { return $null }
    }
    return $relative
}

function New-LauncherFinding {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Detail
    )
    return [pscustomobject]@{ Path = $Path; Detail = $Detail }
}

function Resolve-PriorStaticStringAssignment {
    param(
        [Parameter(Mandatory = $true)]
        [System.Management.Automation.Language.Ast]$Ast,
        [Parameter(Mandatory = $true)]
        [System.Management.Automation.Language.VariableExpressionAst]$Variable,
        [Parameter(Mandatory = $true)]
        [int]$BeforeOffset
    )

    $variableName = $Variable.VariablePath.UserPath
    $assignments = @($Ast.FindAll({
        param($node)
        if ($node -isnot [System.Management.Automation.Language.AssignmentStatementAst]) {
            return $false
        }
        if ($node.Extent.EndOffset -gt $BeforeOffset) { return $false }
        if ($node.Left -isnot [System.Management.Automation.Language.VariableExpressionAst]) {
            return $false
        }
        return $node.Left.VariablePath.UserPath -ieq $variableName
    }, $true))
    if ($assignments.Count -ne 1) { return $null }

    $right = $assignments[0].Right
    if (
        $right -is [System.Management.Automation.Language.CommandExpressionAst] -and
        $right.Expression -is [System.Management.Automation.Language.StringConstantExpressionAst]
    ) {
        return $right.Expression.Value
    }
    return $null
}

function Get-LauncherFinding {
    param(
        [Parameter(Mandatory = $true)]
        [System.Management.Automation.Language.Ast]$Ast,
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $namedLauncher = [System.IO.Path]::GetFileName($Path) -match '(?i)launch|launcher'
    $trainingChild = '(?i)run_vertical_slice|certified_train|run_pretraining|torchrun|train\.py|pretrain\.py'

    $commands = $Ast.FindAll({
        param($node)
        $node -is [System.Management.Automation.Language.CommandAst]
    }, $true)
    foreach ($command in $commands) {
        $name = $command.GetCommandName()
        if ([string]::IsNullOrWhiteSpace($name)) {
            if ($command.InvocationOperator -eq [System.Management.Automation.Language.TokenKind]::Ampersand) {
                $resolvedTarget = Resolve-ScriptRootExpression `
                    -Node $command.CommandElements[0] -SourcePath $Path
                if ($null -ne $resolvedTarget) {
                    $relativeTarget = Get-TrackedRepoRelativePath -Target $resolvedTarget
                    if ($null -ne $relativeTarget) {
                        return New-LauncherFinding -Path $relativeTarget -Detail (
                            "script-rooted target invoked by $Path at line " +
                            $command.Extent.StartLineNumber
                        )
                    }
                }
                return New-LauncherFinding -Path $Path -Detail (
                    "dynamic command target at line $($command.Extent.StartLineNumber)"
                )
            }
            # Dot-sourcing imports definitions into the current process; it is
            # not a child-process launch and therefore is not this rule's shape.
            continue
        }
        $resolved = if ($processAliases.ContainsKey($name.ToLowerInvariant())) {
            $processAliases[$name.ToLowerInvariant()]
        } else {
            $name
        }
        if ($processCommands -contains $resolved) {
            $variableArguments = @($command.FindAll({
                param($node)
                $node -is [System.Management.Automation.Language.VariableExpressionAst]
            }, $true))
            foreach ($variable in $variableArguments) {
                $staticValue = Resolve-PriorStaticStringAssignment `
                    -Ast $Ast -Variable $variable -BeforeOffset $command.Extent.StartOffset
                if ($null -eq $staticValue) {
                    return New-LauncherFinding -Path $Path -Detail (
                        "opaque process-command variable $($variable.Extent.Text) at line " +
                        $command.Extent.StartLineNumber
                    )
                }
                if ($staticValue -match $trainingChild) {
                    return New-LauncherFinding -Path $Path -Detail (
                        "$resolved target $($variable.Extent.Text) resolves to a training child " +
                        "at line $($command.Extent.StartLineNumber)"
                    )
                }
            }
        }
        if (($processCommands -contains $resolved) -and ($namedLauncher -or $command.Extent.Text -match $trainingChild)) {
            return New-LauncherFinding -Path $Path -Detail "$resolved at line $($command.Extent.StartLineNumber)"
        }
        if ((Test-NativeCommandName -Name $resolved) -and ($namedLauncher -or $command.Extent.Text -match $trainingChild)) {
            return New-LauncherFinding -Path $Path -Detail "direct native command '$name' at line $($command.Extent.StartLineNumber)"
        }
        if (
            $command.InvocationOperator -eq [System.Management.Automation.Language.TokenKind]::Ampersand -and
            ($namedLauncher -or $command.Extent.Text -match $trainingChild)
        ) {
            return New-LauncherFinding -Path $Path -Detail "call-operator command '$name' at line $($command.Extent.StartLineNumber)"
        }
    }

    $memberCalls = $Ast.FindAll({
        param($node)
        $node -is [System.Management.Automation.Language.InvokeMemberExpressionAst]
    }, $true)
    foreach ($call in $memberCalls) {
        $memberName = $call.Member.Extent.Text.Trim('"', "'")
        if ($memberName -ieq 'Start' -and ($namedLauncher -or $call.Extent.Text -match $trainingChild)) {
            return New-LauncherFinding -Path $Path -Detail "member Start invocation at line $($call.Extent.StartLineNumber)"
        }
        if (
            $call.Static -and $memberName -match '^(Start|Run|Execute|CreateProcess)$' -and
            ($namedLauncher -or $call.Extent.Text -match $trainingChild)
        ) {
            return New-LauncherFinding -Path $Path -Detail "static process-capable member '$memberName' at line $($call.Extent.StartLineNumber)"
        }
    }

    $aliasMutations = $Ast.FindAll({
        param($node)
        if ($node -isnot [System.Management.Automation.Language.CommandAst]) { return $false }
        $name = $node.GetCommandName()
        return $name -in @('Set-Alias', 'New-Alias', 'Import-Alias')
    }, $true)
    if ($aliasMutations.Count -gt 0 -and ($namedLauncher -or $Ast.Extent.Text -match $trainingChild)) {
        return New-LauncherFinding -Path $Path -Detail "ambient alias mutation at line $($aliasMutations[0].Extent.StartLineNumber)"
    }

    return $null
}

$failed = $false
foreach ($path in $Paths) {
    try {
        $text = Get-TrackedText -Path $path
        $tokens = $null
        $parseErrors = $null
        $ast = [System.Management.Automation.Language.Parser]::ParseInput(
            $text,
            $path,
            [ref]$tokens,
            [ref]$parseErrors
        )
        if ($parseErrors.Count -ne 0) {
            throw "PowerShell parse error at line $($parseErrors[0].Extent.StartLineNumber): $($parseErrors[0].Message)"
        }
        $finding = Get-LauncherFinding -Ast $ast -Path $path
        if ($null -ne $finding) {
            [Console]::Out.WriteLine("$($finding.Path)`t$($finding.Detail)")
            $failed = $true
        }
    } catch {
        [Console]::Out.WriteLine("$path`tREFUSED: $($_.Exception.Message)")
        $failed = $true
    }
}

if ($failed) { exit 1 }
exit 0
