// tools/powershell-tool.ts — PowerShell command execution tool.
// De-transpiled from bundle (lines 306188–306694). Supports PowerShell 5.1 and 7+.
// bundle=Y

import { spawn } from "child_process";
import { z } from "zod";
import { buildTool, type ToolUseContext } from "../core/tool-interface.ts";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const BASH_TIMEOUT_MS = 120_000;
const MAX_OUTPUT_BYTES = 30 * 1024;
const TRUNCATION_MARKER = "\n... [output truncated] ...";

// ---------------------------------------------------------------------------
// Alias resolution
// ---------------------------------------------------------------------------

const PS_ALIAS_MAP: Record<string, string> = {
  ls: "Get-ChildItem", dir: "Get-ChildItem", gci: "Get-ChildItem",
  cat: "Get-Content", gc: "Get-Content", type: "Get-Content",
  cd: "Set-Location", sl: "Set-Location",
  cp: "Copy-Item", copy: "Copy-Item", ci: "Copy-Item",
  mv: "Move-Item", move: "Move-Item", mi: "Move-Item",
  rm: "Remove-Item", del: "Remove-Item", erase: "Remove-Item",
  ri: "Remove-Item", rd: "Remove-Item", rmdir: "Remove-Item",
  md: "mkdir", mkdir: "New-Item", ni: "New-Item",
  ps: "Get-Process", gps: "Get-Process",
  kill: "Stop-Process", spps: "Stop-Process",
  clc: "Clear-Content",
  echo: "Write-Output", write: "Write-Output",
  cls: "Clear-Host", clear: "Clear-Host",
  select: "Select-Object", sort: "Sort-Object",
  where: "Where-Object", "?": "Where-Object",
  "%": "ForEach-Object", measure: "Measure-Object",
  h: "Get-History", history: "Get-History",
  iex: "Invoke-Expression", iwr: "Invoke-WebRequest",
  irm: "Invoke-RestMethod", icm: "Invoke-Command",
  man: "Get-Help", help: "Get-Help",
  fl: "Format-List", fw: "Format-Wide", ft: "Format-Table", fc: "Format-Custom",
  oc: "Out-Null", oh: "Out-Host",
  foreach: "ForEach-Object", tee: "Tee-Object",
  sc: "Set-Content", ac: "Add-Content",
  si: "Set-Item", gi: "Get-Item",
  gp: "Get-ItemProperty", sp: "Set-ItemProperty",
  gm: "Get-Member", gsv: "Get-Service",
  ssv: "Start-Service", spsv: "Stop-Service",
};

function resolveAlias(cmdlet: string): string {
  return PS_ALIAS_MAP[cmdlet.toLowerCase()] ?? cmdlet;
}

// ---------------------------------------------------------------------------
// Read-only cmdlet sets
// ---------------------------------------------------------------------------

const READ_ONLY_CMDLETS = new Set([
  "Get-ChildItem", "Get-Content", "Get-Item", "Get-ItemProperty",
  "Get-Location", "Get-Process", "Get-Service", "Get-Module", "Get-Command",
  "Get-Help", "Get-Member", "Get-Alias", "Get-PSDrive", "Get-PSProvider",
  "Get-Variable", "Get-EventLog", "Get-WinEvent", "Get-History",
  "Get-Date", "Get-Host", "Get-Culture", "Get-UICulture", "Get-PSCallStack",
  "Get-Error", "Get-ComputerInfo", "Get-Disk", "Get-Partition", "Get-Volume",
  "Get-NetAdapter", "Get-NetIPAddress", "Get-NetRoute", "Get-DnsClientServerAddress",
  "Get-FileHash", "Get-AuthenticodeSignature", "Get-Package", "Get-PackageProvider",
  "Get-PackageSource", "Get-InstalledModule", "Get-AzContext", "Get-AzSubscription",
  "Get-AzResourceGroup",
  "Measure-Object", "Select-Object", "Sort-Object", "Group-Object",
  "Compare-Object", "Where-Object", "ForEach-Object",
  "Format-List", "Format-Table", "Format-Wide", "Format-Custom",
  "Out-Host", "Out-Null", "Out-String", "Out-GridView",
  "Test-Path", "Test-Connection", "Test-NetConnection",
  "Resolve-Path", "Split-Path", "Join-Path", "Convert-Path",
  "Import-Csv", "Import-Clixml",
  "ConvertFrom-Json", "ConvertFrom-Csv", "ConvertFrom-StringData", "ConvertFrom-SecureString",
  "ConvertTo-Json", "ConvertTo-Csv", "ConvertTo-Xml",
  "Select-String", "Tee-Object",
  "Write-Output", "Write-Host", "Write-Verbose", "Write-Debug",
  "Write-Warning", "Write-Information", "Write-Error",
  "Get-Env", "Get-PsProvider", "Clear-Host", "Wait-Process",
  "git", "gh", "docker",
]);

const GIT_READ_ONLY_SUBS = new Set([
  "log", "diff", "status", "show", "branch", "remote", "stash",
  "cat-file", "ls-files", "ls-tree", "rev-parse", "rev-list",
  "describe", "shortlog", "blame", "tag", "notes", "reflog",
  "for-each-ref", "check-ignore", "diff-tree", "diff-index", "diff-files",
]);

const GH_READ_ONLY_SUBS = new Set([
  "pr", "issue", "repo", "gist", "release", "run", "workflow",
  "auth", "api", "search", "secret", "variable", "extension", "label",
]);

const DOCKER_READ_ONLY_SUBS = new Set([
  "ps", "images", "inspect", "logs", "stats", "top",
  "port", "diff", "history", "system", "info", "version",
]);

// Blocked type literals for constrained-language-mode safety
const BLOCKED_TYPES = new Set([
  "adsi", "adsisearcher", "adsidirectoryentry", "wmiobject",
  "ciminstance", "cimsession", "cimclass", "comobject", "__comobject",
  "directoryentry", "directorysearcher", "reflection.assembly",
  "system.reflection.assembly", "codedom.compiler", "microsoft.csharp",
  "marshal", "system.runtime.interopservices.marshal",
  "diagnostics.process", "system.diagnostics.process",
  "net.webrequest", "net.webclient", "system.net.webrequest", "system.net.webclient",
]);

// ---------------------------------------------------------------------------
// Read-only detection
// ---------------------------------------------------------------------------

function isSingleCmdletReadOnly(segment: string): boolean {
  const tokens = segment.trim().split(/\s+/);
  const firstToken = tokens[0] ?? "";
  const resolved = resolveAlias(firstToken);
  if (READ_ONLY_CMDLETS.has(resolved)) {
    if (resolved.toLowerCase() === "git") {
      const sub = tokens[1]?.toLowerCase();
      return sub != null && GIT_READ_ONLY_SUBS.has(sub);
    }
    if (resolved.toLowerCase() === "gh") {
      const sub = tokens[1]?.toLowerCase();
      return sub != null && GH_READ_ONLY_SUBS.has(sub);
    }
    if (resolved.toLowerCase() === "docker") {
      const sub = tokens[1]?.toLowerCase();
      return sub != null && DOCKER_READ_ONLY_SUBS.has(sub);
    }
    return true;
  }
  return false;
}

function isReadOnlyCommand(cmd: string): boolean {
  const segments = cmd.split("|").map((s) => s.trim()).filter((s) => s.length > 0);
  return segments.every(isSingleCmdletReadOnly);
}

// ---------------------------------------------------------------------------
// AST security check
// ---------------------------------------------------------------------------

interface AstCheckResult {
  safe: boolean;
  reason?: string;
}

function checkAstSecurity(cmd: string): AstCheckResult {
  const lower = cmd.toLowerCase();

  if (/\biex\b/.test(lower) || /\binvoke-expression\b/.test(lower))
    return { safe: false, reason: "Invoke-Expression (iex) is a dangerous dynamic execution method" };
  if (/(-encodedcommand|-enc\b|-e\s+[A-Za-z0-9+/=]{10,})/.test(lower))
    return { safe: false, reason: "Encoded command flag detected (-EncodedCommand/-e)" };
  if (/\bpowershell\b.*-command|-command\b/.test(lower))
    return { safe: false, reason: "Nested PowerShell invocation detected" };
  if (/\badd-type\b/.test(lower))
    return { safe: false, reason: "Add-Type .NET compilation detected" };
  if (/\bnew-object\b.*-comobject/i.test(cmd) || /\[comobject\]/.test(lower))
    return { safe: false, reason: "COM object creation detected" };
  if (/\bstart-process\b.*-verb\s+runas/i.test(cmd))
    return { safe: false, reason: "Start-Process -Verb RunAs elevation detected" };
  if (/\$\(/.test(cmd))
    return { safe: false, reason: "Subexpression $() detected — potentially dynamic execution" };
  if (/@[A-Za-z_][A-Za-z0-9_]*/.test(cmd))
    return { safe: false, reason: "Splatting (@variable) detected" };
  if (/--\s*%/.test(cmd))
    return { safe: false, reason: "Stop-parsing token (--%) detected" };
  if (/\binstall-module\b|\bimport-module\b/.test(lower))
    return { safe: false, reason: "Module loading/installation detected" };
  if (/\bregister-scheduledtask\b|\bnew-scheduledtask\b/.test(lower))
    return { safe: false, reason: "Scheduled task registration detected" };
  if (/\binvoke-wmimethod\b|\binvoke-cimmethod\b/.test(lower))
    return { safe: false, reason: "WMI/CIM method invocation detected" };
  if (/\biwr\b.*\|.*\biex\b|\binvoke-webrequest\b.*\|.*\binvoke-expression\b/.test(lower))
    return { safe: false, reason: "Download cradle pattern detected (Invoke-WebRequest | Invoke-Expression)" };
  if (/\bcertutil\b.*-urlcache/.test(lower) || /\bcertutil\b.*-verifyctl/.test(lower))
    return { safe: false, reason: "certutil download cradle detected" };
  if (/\bbitsadmin\b.*\/transfer/.test(lower))
    return { safe: false, reason: "bitsadmin download cradle detected" };
  if (/^using\s+(namespace|module|assembly)\s/im.test(cmd))
    return { safe: false, reason: "using statement detected" };
  if (/#requires\s/.test(cmd))
    return { safe: false, reason: "#requires statement detected" };
  if (/\bstart-job\b.*-filepath/i.test(cmd))
    return { safe: false, reason: "Start-Job -FilePath dangerous invocation detected" };
  if (/"[^"]*\$\([^"]*\)"/.test(cmd))
    return { safe: false, reason: "Expandable string with embedded expression detected" };

  // Type literal check
  const typeLiteralRe = /\[([A-Za-z0-9_.]+)\]/g;
  let match: RegExpExecArray | null;
  while ((match = typeLiteralRe.exec(cmd)) !== null) {
    const typeName = (match[1] ?? "").toLowerCase();
    if (BLOCKED_TYPES.has(typeName)) {
      return { safe: false, reason: `Blocked type literal [${match[1]}] — forbidden in constrained language mode` };
    }
  }

  if (/\$[A-Za-z_][A-Za-z0-9_]*\s*\(/.test(cmd))
    return { safe: false, reason: "Dynamic command name detected (variable as cmdlet)" };
  if (/\)\.[A-Za-z]+\s*\(/.test(cmd))
    return { safe: false, reason: "Method invocation on object detected" };
  if (/\$env:[A-Za-z_][A-Za-z0-9_]*\s*=/.test(cmd))
    return { safe: false, reason: "Environment variable scope write detected" };
  if (/\bset-alias\b|\bnew-alias\b|\bremove-alias\b/.test(lower))
    return { safe: false, reason: "Alias manipulation detected" };

  return { safe: true };
}

function containsUncPath(cmd: string): boolean {
  return /\\\\[A-Za-z0-9_.-]+\\|\/\/[A-Za-z0-9_.-]+\//.test(cmd);
}

// ---------------------------------------------------------------------------
// Exit code interpretation
// ---------------------------------------------------------------------------

function interpretPowerShellExitCode(cmd: string, exitCode: number): string {
  const lower = cmd.trim().toLowerCase();
  const base = lower.split(/\s+/)[0] ?? "";

  if ((base === "grep" || base === "rg" || base === "findstr") && exitCode === 1)
    return "No matches found (exit 1 is normal for grep/rg/findstr with no matches)";

  if (base === "robocopy") {
    if (exitCode === 0) return "robocopy success: no files copied (no changes)";
    if (exitCode === 1) return "robocopy success: files copied successfully";
    if (exitCode === 2) return "robocopy success: extra files or directories were detected";
    if (exitCode === 3) return "robocopy success: some files copied, extra files present";
    if (exitCode === 4) return "robocopy partial success: some files not copied (mismatched, different attributes)";
    if (exitCode === 5) return "robocopy partial success: some files copied; some files mismatched";
    if (exitCode === 6) return "robocopy partial success: extra files and mismatched files";
    if (exitCode === 7) return "robocopy partial success: files copied, extras, mismatched";
    return `robocopy error: exit code ${exitCode} (8+ indicates a fatal error)`;
  }

  if (exitCode === 0) return "Command succeeded";
  return `Command exited with code ${exitCode}`;
}

// ---------------------------------------------------------------------------
// PowerShell edition detection (cached)
// ---------------------------------------------------------------------------

let _cachedEdition: "7+" | "5.1" | "unknown" | null = null;

function runPsEditionCheck(exe: string): Promise<boolean> {
  return new Promise((resolve) => {
    const proc = spawn(exe, ["-NoProfile", "-NonInteractive", "-Command", "$PSVersionTable.PSVersion.Major"], {
      timeout: 5000,
    });
    let output = "";
    proc.stdout?.on("data", (d: Buffer) => { output += d.toString(); });
    proc.on("close", (code: number | null) => {
      resolve(code === 0 && output.trim().length > 0);
    });
    proc.on("error", () => resolve(false));
  });
}

async function detectPowerShellEdition(): Promise<"7+" | "5.1" | "unknown"> {
  if (_cachedEdition !== null) return _cachedEdition;
  try {
    const pwsh = await runPsEditionCheck("pwsh");
    if (pwsh) { _cachedEdition = "7+"; return "7+"; }
  } catch {}
  try {
    const ps5 = await runPsEditionCheck("powershell");
    if (ps5) { _cachedEdition = "5.1"; return "5.1"; }
  } catch {}
  _cachedEdition = "unknown";
  return "unknown";
}

async function getPsExecutable(): Promise<string> {
  const edition = await detectPowerShellEdition();
  if (edition === "7+") return "pwsh";
  return "powershell";
}

// ---------------------------------------------------------------------------
// Image output detection
// ---------------------------------------------------------------------------

function detectImageOutput(buf: Buffer): boolean {
  if (buf.length < 4) return false;
  if (buf[0] === 137 && buf[1] === 80 && buf[2] === 78 && buf[3] === 71) return true; // PNG
  if (buf[0] === 255 && buf[1] === 216 && buf[2] === 255) return true; // JPEG
  return false;
}

// ---------------------------------------------------------------------------
// Process execution
// ---------------------------------------------------------------------------

interface PsExecResult {
  stdout: Buffer;
  stderr: string;
  exitCode: number;
  timedOut: boolean;
}

async function executePs(
  command: string,
  timeout: number,
  abortSignal: AbortSignal,
  psExe: string,
  cwd: string,
): Promise<PsExecResult> {
  return new Promise((resolve) => {
    const stdoutChunks: Buffer[] = [];
    const stderrChunks: string[] = [];
    let finished = false;

    const proc = spawn(psExe, ["-NoProfile", "-NonInteractive", "-Command", command], {
      env: process.env,
      cwd,
      shell: false,
    });

    const timer = setTimeout(() => {
      if (!finished) {
        proc.kill();
        finished = true;
        resolve({
          stdout: Buffer.concat(stdoutChunks),
          stderr: stderrChunks.join(""),
          exitCode: -1,
          timedOut: true,
        });
      }
    }, timeout);

    const abort = () => {
      if (!finished) {
        proc.kill();
        finished = true;
        clearTimeout(timer);
        resolve({
          stdout: Buffer.concat(stdoutChunks),
          stderr: stderrChunks.join(""),
          exitCode: -1,
          timedOut: false,
        });
      }
    };

    abortSignal.addEventListener("abort", abort, { once: true });

    proc.stdout?.on("data", (chunk: Buffer) => stdoutChunks.push(chunk));
    proc.stderr?.on("data", (chunk: Buffer) => stderrChunks.push(chunk.toString("utf-8")));

    proc.on("close", (code: number | null) => {
      if (!finished) {
        finished = true;
        clearTimeout(timer);
        abortSignal.removeEventListener("abort", abort);
        resolve({
          stdout: Buffer.concat(stdoutChunks),
          stderr: stderrChunks.join(""),
          exitCode: code ?? 0,
          timedOut: false,
        });
      }
    });

    proc.on("error", (err: Error) => {
      if (!finished) {
        finished = true;
        clearTimeout(timer);
        abortSignal.removeEventListener("abort", abort);
        resolve({
          stdout: Buffer.alloc(0),
          stderr: String(err),
          exitCode: 1,
          timedOut: false,
        });
      }
    });
  });
}

// ---------------------------------------------------------------------------
// Public output type
// ---------------------------------------------------------------------------

export interface PowerShellOutput {
  stdout?: string;
  stderr?: string;
  returnCodeInterpretation: string;
  interrupted: boolean;
  noOutputExpected: boolean;
  isImage?: boolean;
}

// ---------------------------------------------------------------------------
// Execution wrapper
// ---------------------------------------------------------------------------

async function runPowerShell(
  input: { command: string; timeout?: number },
  ctx: ToolUseContext,
): Promise<PowerShellOutput> {
  const { command } = input;
  const timeout = input.timeout ?? BASH_TIMEOUT_MS;
  const psExe = await getPsExecutable();
  const result = await executePs(command, timeout, ctx.abortController.signal, psExe, ctx.cwd ?? process.cwd());

  const stdoutBuf = result.stdout;
  const isImage = detectImageOutput(stdoutBuf);
  let stdout = isImage ? "[binary image output]" : stdoutBuf.toString("utf-8");
  if (stdout.length > MAX_OUTPUT_BYTES) {
    stdout = stdout.slice(0, MAX_OUTPUT_BYTES) + TRUNCATION_MARKER;
  }
  let stderr = result.stderr;
  if (stderr.length > MAX_OUTPUT_BYTES) {
    stderr = stderr.slice(0, MAX_OUTPUT_BYTES) + TRUNCATION_MARKER;
  }
  const interpretation = interpretPowerShellExitCode(command, result.exitCode);
  return {
    stdout: stdout || undefined,
    stderr: stderr || undefined,
    returnCodeInterpretation: interpretation,
    interrupted: result.timedOut,
    noOutputExpected: stdout.length === 0 && stderr.length === 0,
    ...(isImage ? { isImage: true } : {}),
  };
}

// ---------------------------------------------------------------------------
// Schema and input type
// ---------------------------------------------------------------------------

const PowerShellInputSchema = z.object({
  command: z.string(),
  timeout: z.number().optional(),
  description: z.string().optional(),
});

export type PowerShellInput = z.infer<typeof PowerShellInputSchema>;

// ---------------------------------------------------------------------------
// Tool definition
// ---------------------------------------------------------------------------

export const powerShellTool = Object.assign(
  buildTool<PowerShellInput, PowerShellOutput>({
    name: "PowerShell",

    inputSchema: PowerShellInputSchema,

    isReadOnly: (input?: PowerShellInput) => isReadOnlyCommand(input?.command ?? ""),
    isDestructive: () => false,
    isConcurrencySafe: () => false,

    description: (_input?: PowerShellInput, _opts?) =>
      "Execute PowerShell commands. Returns stdout, stderr, and exit code interpretation.",

    prompt: (_opts?) => `## PowerShell tool
Execute PowerShell commands (edition detected at runtime).
- Read-only cmdlets (Get-ChildItem, Select-String, etc.) are auto-allowed.
- Set-Content, Add-Content, Remove-Item are allowed in acceptEdits mode.
- Dangerous patterns (Invoke-Expression, encoded commands, etc.) trigger a permission prompt.
- Timeout default: 120 seconds.
- Long-running commands (>15s) may be automatically backgrounded.
- UNC paths (\\\\server\\share) are blocked.
- Windows PowerShell 5.1: pipeline chain operators (&&/||) are NOT available; default encoding is UTF-16 LE.
- PowerShell 7+: pipeline chain operators are available.`,

    checkPermissions: async (input: PowerShellInput, ctx: ToolUseContext) => {
      const { command } = input;
      const state = ctx.getAppState() as Record<string, unknown>;
      const denyPatterns = (state["bashDenyPatterns"] as string[] | undefined) ?? [];
      const denyPaths = (state["denyPaths"] as string[] | undefined) ?? [];
      for (const pattern of [...denyPatterns, ...denyPaths]) {
        if (command.includes(pattern)) {
          return {
            behavior: "deny" as const,
            updatedInput: input,
            message: `Command denied by rule: ${pattern}`,
          };
        }
      }
      if (containsUncPath(command)) {
        return {
          behavior: "deny" as const,
          updatedInput: input,
          message: "UNC paths are blocked (NTLM credential leak risk)",
        };
      }
      const astResult = checkAstSecurity(command);
      if (!astResult.safe) {
        return {
          behavior: "ask" as const,
          updatedInput: input,
          message: `Security check flagged: ${astResult.reason}`,
        };
      }
      return { behavior: "allow" as const, updatedInput: input };
    },

    call: async (args: PowerShellInput, ctx: ToolUseContext) => {
      const data = await runPowerShell(args, ctx);
      return { data };
    },

    mapToolResultToToolResultBlockParam: (content: PowerShellOutput, toolUseId: string) => ({
      type: "tool_result" as const,
      tool_use_id: toolUseId,
      content: JSON.stringify(content),
    }),

    toAutoClassifierInput: (input?: PowerShellInput) => input?.command ?? "",
  }),
  { searchHint: "execute PowerShell commands" } as const,
);
