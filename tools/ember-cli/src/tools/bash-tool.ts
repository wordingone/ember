// tools/bash-tool.ts — Bash shell command execution tool.
// De-transpiled from bundle (lines 304380–304645). Executes via cmd.exe on Windows.
// bundle=Y

import { spawn } from "child_process";
import { z } from "zod";
import { buildTool, type ToolUseContext } from "../core/tool-interface.ts";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const BASH_TIMEOUT_MS = 120_000;
const BACKGROUND_THRESHOLD_MS = 15_000;
const MAX_OUTPUT_BYTES = 30 * 1024;
const TRUNCATION_MARKER = "\n... [output truncated] ...";

// ---------------------------------------------------------------------------
// Read-only command detection
// ---------------------------------------------------------------------------

const READ_ONLY_COMMANDS = new Set([
  "grep", "rg", "find", "cat", "head", "tail", "wc", "stat", "file",
  "jq", "awk", "cut", "sort", "uniq", "tr", "ls", "tree", "du", "pwd",
  "which", "type", "env", "printenv", "date", "whoami", "id", "uname",
  "hostname", "ps", "top", "diff", "cmp", "md5sum", "sha256sum", "xxd",
  "od", "strings", "ldd", "nm", "objdump", "readelf", "file", "test", "[",
]);

const DANGEROUS_PATTERNS: RegExp[] = [
  /\$\(/,
  /`[^`]+`/,
  /\$\{.*\}/,
];

const CD_GIT_PIPELINE_RE = /\bcd\b.*\|.*\bgit\b/;

function extractBaseCommand(cmd: string): string {
  const trimmed = cmd.trim();
  const noEnv = trimmed.replace(/^(?:[A-Za-z_][A-Za-z0-9_]*=\S+\s+)*/, "");
  return noEnv.split(/\s+/)[0]?.toLowerCase() ?? "";
}

function isSingleSegmentReadOnly(segment: string): boolean {
  const base = extractBaseCommand(segment);
  if (READ_ONLY_COMMANDS.has(base)) return true;
  if (base === "git") {
    const sub = segment.trim().split(/\s+/)[1]?.toLowerCase();
    const GIT_RO = new Set([
      "log", "diff", "status", "show", "branch", "remote", "stash",
      "cat-file", "ls-files", "ls-tree", "rev-parse", "rev-list",
      "describe", "shortlog", "blame", "tag", "notes", "reflog",
      "for-each-ref", "check-ignore", "diff-tree", "diff-index", "diff-files",
    ]);
    if (sub && GIT_RO.has(sub)) return true;
    return false;
  }
  return false;
}

function isReadOnlyCommand(cmd: string): boolean {
  const segments = cmd.split("|").map((s) => s.trim()).filter((s) => s.length > 0);
  return segments.every(isSingleSegmentReadOnly);
}

function detectDangerousPatterns(cmd: string): boolean {
  return DANGEROUS_PATTERNS.some((re) => re.test(cmd));
}

function detectCdGitPipeline(cmd: string): boolean {
  return CD_GIT_PIPELINE_RE.test(cmd);
}

// ---------------------------------------------------------------------------
// Exit code interpretation
// ---------------------------------------------------------------------------

function interpretExitCode(cmd: string, exitCode: number): string {
  const base = extractBaseCommand(cmd);
  if ((base === "grep" || base === "rg") && exitCode === 1) {
    return "No matches found (exit 1 is normal for grep/rg with no matches)";
  }
  if (base === "diff" && exitCode === 1) {
    return "Files differ (exit 1 means differences found, not an error)";
  }
  if (base === "find" && exitCode === 1) {
    return "Partial success (some directories were inaccessible)";
  }
  if ((base === "test" || base === "[") && exitCode === 1) {
    return "Condition is false (exit 1 is not an error for test)";
  }
  if (exitCode === 0) return "Command succeeded";
  return `Command exited with code ${exitCode}`;
}

// ---------------------------------------------------------------------------
// Image output detection
// ---------------------------------------------------------------------------

function detectImageOutput(buf: Buffer): boolean {
  if (buf.length < 4) return false;
  // PNG magic bytes
  if (buf[0] === 137 && buf[1] === 80 && buf[2] === 78 && buf[3] === 71) return true;
  // JPEG magic bytes
  if (buf[0] === 255 && buf[1] === 216 && buf[2] === 255) return true;
  return false;
}

// ---------------------------------------------------------------------------
// Process execution
// ---------------------------------------------------------------------------

interface ExecResult {
  stdout: Buffer;
  stderr: string;
  exitCode: number;
  timedOut: boolean;
}

async function executeCommand(
  command: string,
  timeout: number,
  abortSignal: AbortSignal,
): Promise<ExecResult> {
  return new Promise((resolve) => {
    const stdoutChunks: Buffer[] = [];
    const stderrChunks: string[] = [];
    let finished = false;

    const proc = spawn("cmd.exe", ["/c", command], {
      env: process.env,
      cwd: process.cwd(),
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

export interface BashOutput {
  stdout?: string;
  stderr?: string;
  returnCodeInterpretation: string;
  noOutputExpected: boolean;
  backgroundTaskId?: string;
  isImage?: boolean;
}

// ---------------------------------------------------------------------------
// Execution wrapper
// ---------------------------------------------------------------------------

async function runBash(
  input: { command: string; timeout?: number },
  ctx: ToolUseContext,
): Promise<BashOutput> {
  const { command } = input;
  const timeout = input.timeout ?? BASH_TIMEOUT_MS;
  const disableBackground = process.env["EMBER_DISABLE_BACKGROUND_TASKS"] === "1";

  if (!disableBackground) {
    let bgTaskId: string | undefined;
    const startTime = Date.now();
    const result = await executeCommand(command, timeout, ctx.abortController.signal);
    const elapsed = Date.now() - startTime;
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
    const interpretation = interpretExitCode(command, result.exitCode);
    if (elapsed > BACKGROUND_THRESHOLD_MS && !result.timedOut) {
      bgTaskId = "bg-" + Math.random().toString(36).slice(2);
    }
    return {
      stdout: stdout || undefined,
      stderr: stderr || undefined,
      returnCodeInterpretation: interpretation,
      noOutputExpected: stdout.length === 0 && stderr.length === 0,
      ...(bgTaskId ? { backgroundTaskId: bgTaskId } : {}),
      ...(isImage ? { isImage: true } : {}),
    };
  } else {
    const result = await executeCommand(command, timeout, ctx.abortController.signal);
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
    return {
      stdout: stdout || undefined,
      stderr: stderr || undefined,
      returnCodeInterpretation: interpretExitCode(command, result.exitCode),
      noOutputExpected: stdout.length === 0 && stderr.length === 0,
      ...(isImage ? { isImage: true } : {}),
    };
  }
}

// ---------------------------------------------------------------------------
// Schema and input type
// ---------------------------------------------------------------------------

const BashInputSchema = z.object({
  command: z.string(),
  timeout: z.number().optional(),
  description: z.string().optional(),
});

export type BashInput = z.infer<typeof BashInputSchema>;

// ---------------------------------------------------------------------------
// Tool definition
// ---------------------------------------------------------------------------

export const bashTool = Object.assign(
  buildTool<BashInput, BashOutput>({
    name: "Bash",

    inputSchema: BashInputSchema,

    isReadOnly: (input?: BashInput) => isReadOnlyCommand(input?.command ?? ""),
    isDestructive: () => false,
    isConcurrencySafe: () => false,

    description: (_input?: BashInput, _opts?) =>
      "Execute shell commands. Returns stdout, stderr, and exit code interpretation.",

    prompt: (_opts?) => `## Bash tool
Execute shell commands in a bash session.
- Commands like ls, grep, cat, find are auto-allowed (read-only).
- Write operations (rm, mv, cp, etc.) require permission.
- Timeout default: 120 seconds.
- Long-running commands (>15s) may be automatically backgrounded.
- CWD resets to project root if changed outside it.`,

    checkPermissions: async (input: BashInput, ctx: ToolUseContext) => {
      const { command } = input;
      const state = ctx.getAppState() as Record<string, unknown>;
      const bashDenyPatterns = (state["bashDenyPatterns"] as string[] | undefined) ?? [];
      for (const pattern of bashDenyPatterns) {
        if (command.includes(pattern)) {
          return {
            behavior: "deny" as const,
            updatedInput: input,
            message: `Command denied by rule: ${pattern}`,
          };
        }
      }
      if (detectDangerousPatterns(command)) {
        return {
          behavior: "ask" as const,
          updatedInput: input,
          message: "Command contains potentially dangerous patterns (command substitution)",
        };
      }
      if (detectCdGitPipeline(command)) {
        return {
          behavior: "ask" as const,
          updatedInput: input,
          message: "Piped cd+git pattern is potentially unsafe",
        };
      }
      return { behavior: "allow" as const, updatedInput: input };
    },

    call: async (args: BashInput, ctx: ToolUseContext) => {
      const data = await runBash(args, ctx);
      return { data };
    },

    mapToolResultToToolResultBlockParam: (content: BashOutput, toolUseId: string) => ({
      type: "tool_result" as const,
      tool_use_id: toolUseId,
      content: JSON.stringify(content),
    }),

    toAutoClassifierInput: (input?: BashInput) => input?.command ?? "",
  }),
  { searchHint: "execute shell commands" } as const,
);
