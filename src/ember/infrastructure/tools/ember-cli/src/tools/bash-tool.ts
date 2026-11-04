// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// tools/bash-tool.ts — Bash shell command execution tool.
// De-transpiled from bundle (lines 304380–304645). Executes via cmd.exe on Windows.
// bundle=Y

import { spawn, spawnSync } from "child_process";
import { existsSync, unlinkSync, writeFileSync } from "fs";
import { tmpdir } from "os";
import { dirname, join } from "path";
import { z } from "zod";
import { isDestructiveCommand, DESTRUCTIVE_ASK_MESSAGE } from "../core/destructive-command.ts";
import { privateHostAskMessage, privateHostInCommand } from "../core/private-hosts.ts";
import { buildTool, type ToolUseContext } from "../core/tool-interface.ts";
import { createTailReporter } from "../core/tool-progress.ts";
import { assignToSessionJob } from "./process-job.ts";
import { shellStateNote } from "./shell-state-note.ts";

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

// ---------------------------------------------------------------------------
// Shell choice: Git Bash when installed, else cmd.exe
// ---------------------------------------------------------------------------

let _gitBash: string | null | undefined;

/** Git for Windows' bash.exe, or null. A tool named Bash that ran cmd.exe broke every bash habit
 *  of the model: `mkdir -p` made a "-p" folder, `$VAR` stayed literal (blind test S05-S07).
 *  WSL's System32\bash.exe is never used: it runs in another filesystem. */
export function findGitBash(): string | null {
  if (_gitBash !== undefined) return _gitBash;
  _gitBash = null;
  if (process.platform !== "win32") return _gitBash;
  const candidates: string[] = [];
  const fromEnv = process.env["EMBER_GIT_BASH_PATH"];
  if (fromEnv === "") return _gitBash; // explicitly disabled: use cmd.exe
  if (fromEnv) candidates.push(fromEnv);
  for (const root of [process.env["ProgramFiles"], process.env["ProgramFiles(x86)"], process.env["LOCALAPPDATA"] && join(process.env["LOCALAPPDATA"]!, "Programs")]) {
    if (root) candidates.push(join(root, "Git", "bin", "bash.exe"));
  }
  try {
    const where = spawnSync("where.exe", ["git"], { windowsHide: true, encoding: "utf-8" });
    for (const line of String(where.stdout ?? "").split(/\r?\n/)) {
      const git = line.trim();
      if (git) candidates.push(join(dirname(dirname(git)), "bin", "bash.exe"));
    }
  } catch { /* no where.exe */ }
  for (const c of candidates) {
    if (/\\system32\\/i.test(c)) continue;
    if (existsSync(c)) { _gitBash = c; break; }
  }
  return _gitBash;
}

export interface ExecResult {
  stdout: Buffer;
  stderr: string;
  exitCode: number;
  timedOut: boolean;
}

/** Defined before every Git Bash command (#2380 S27). Git Bash rewrites an argument that looks like
 *  a POSIX path into a Windows path ("MSYS path conversion"): `/c` becomes `C:/` and `/b` becomes
 *  `B:/`. So `cmd /c ...` reached cmd.exe without its `/c`, and `start /b ...` (Git's own `start`
 *  is `cmd //c start "$@"`) without its `/b`; cmd.exe then ran as an interactive shell, printed its
 *  banner and prompt, and waited for input until the 120 s timeout. These wrappers call cmd.exe
 *  with path conversion turned off; `//c` (the usual Git Bash workaround) still works. One line,
 *  ended by "; ", so the line numbers in the command's own error messages do not move. Not
 *  exported to child processes: a script the command runs still sees Git's plain tools. */
export const GIT_BASH_PRELUDE =
  `__ember_cmd() { local a=() x; for x in "$@"; do case "$x" in //[A-Za-z]) x="\${x#/}" ;; esac; a+=("$x"); done; ` +
  `MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*' command cmd.exe "\${a[@]}"; }; ` +
  `cmd() { __ember_cmd "$@"; }; cmd.exe() { __ember_cmd "$@"; }; ` +
  `start() { __ember_cmd /d /c start "\${@//&/^&}"; }; `;

/** How the Bash tool starts its shell. stdin is never a pipe: nothing ever writes to it, and an open
 *  pipe let any program that reads input (an interactive cmd.exe, `read`, a REPL) wait on it until
 *  the timeout (#2380 S27). With no stdin such a program sees end of input at once. */
export function shellInvocation(command: string, gitBash: string | null): {
  file: string;
  args: string[];
  stdio: ["ignore", "pipe", "pipe"];
  verbatim: boolean;
  batch: { path: string; body: string } | null;
} {
  const stdio: ["ignore", "pipe", "pipe"] = ["ignore", "pipe", "pipe"];
  if (gitBash) return { file: gitBash, args: ["-c", GIT_BASH_PRELUDE + command], stdio, verbatim: false, batch: null };
  // Verbatim: Node's default argv quoting turned every `"` into `\"`, which cmd.exe does not
  // understand (blind test S03-S05). `/s /c "<cmd>"` makes cmd strip exactly the outer quotes.
  // A multi-line command runs as a temporary batch file: `cmd /c` runs only the first line (S08).
  if (/[\r\n]/.test(command.trim())) {
    const path = join(tmpdir(), `ember-bash-${process.pid}-${Date.now()}-${Math.random().toString(36).slice(2)}.cmd`);
    const body = "@echo off\r\n" + command.replace(/\r?\n/g, "\r\n") + "\r\n";
    return { file: "cmd.exe", args: ["/d", "/s", "/c", `"call "${path}""`], stdio, verbatim: true, batch: { path, body } };
  }
  return { file: "cmd.exe", args: ["/d", "/s", "/c", `"${command}"`], stdio, verbatim: true, batch: null };
}

async function executeCommand(
  command: string,
  timeout: number,
  abortSignal: AbortSignal,
  cwd: string,
  toolUseId?: string,
): Promise<ExecResult> {
  return executeCommandWithShell(command, timeout, abortSignal, cwd, findGitBash(), toolUseId);
}

/** {@link executeCommand} with the shell given: tests pass a real bash on any platform. */
export async function executeCommandWithShell(
  command: string,
  timeout: number,
  abortSignal: AbortSignal,
  cwd: string,
  gitBash: string | null,
  toolUseId?: string,
): Promise<ExecResult> {
  return new Promise((resolveRaw) => {
    const stdoutChunks: Buffer[] = [];
    const stderrChunks: string[] = [];
    let finished = false;

    const invocation = shellInvocation(command, gitBash);
    let batchPath: string | null = null;
    if (invocation.batch) {
      batchPath = invocation.batch.path;
      writeFileSync(batchPath, invocation.batch.body);
    }
    const cmdArgs = invocation.args;
    const cleanupBatch = () => {
      if (batchPath) { try { unlinkSync(batchPath); } catch { /* already gone */ } batchPath = null; }
    };
    const proc = spawn(invocation.file, cmdArgs, {
      env: process.env,
      cwd,
      shell: false,
      stdio: invocation.stdio,
      windowsVerbatimArguments: invocation.verbatim,
      // Own hidden console: a child sharing ember's console could change its title, code page and
      // window size (blind test: after a PowerShell call the caret and borders drew as "?").
      windowsHide: true,
    });
    // Anything this command leaves running ends with ember, not with the window (blind test S27/S28).
    assignToSessionJob(proc.pid);
    // The screen shows the last line of output while the command runs (blind test S24).
    const liveTail = createTailReporter(toolUseId);
    const resolve = (result: ExecResult): void => { liveTail.stop(); resolveRaw(result); };
    // Killing cmd.exe alone leaves its children running (a timed-out ping kept going): end the
    // whole tree this tool started, by its PID.
    const killTree = () => {
      if (proc.pid !== undefined && process.platform === "win32") {
        try { spawnSync("taskkill", ["/pid", String(proc.pid), "/T", "/F"], { windowsHide: true }); } catch { /* best effort */ }
      }
      try { proc.kill(); } catch { /* already exited */ }
    };
    proc.on("exit", cleanupBatch);

    const timer = setTimeout(() => {
      if (!finished) {
        killTree();
        cleanupBatch();
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
        killTree();
        cleanupBatch();
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

    proc.stdout?.on("data", (chunk: Buffer) => { stdoutChunks.push(chunk); liveTail.push(chunk); });
    proc.stderr?.on("data", (chunk: Buffer) => { stderrChunks.push(chunk.toString("utf-8")); liveTail.push(chunk); });

    // A command that starts a background process (`start /b`, `cmd &`) exits while the child still
    // holds the output pipes, so "close" never comes until the timeout (blind test S27). Once the
    // shell itself has exited, give stragglers a moment, then return what arrived.
    proc.on("exit", (code: number | null) => {
      setTimeout(() => {
        if (finished) return;
        finished = true;
        clearTimeout(timer);
        abortSignal.removeEventListener("abort", abort);
        try { proc.stdout?.destroy(); proc.stderr?.destroy(); } catch { /* already closed */ }
        resolve({
          stdout: Buffer.concat(stdoutChunks),
          stderr: stderrChunks.join("") + "\n[the command started a background process that is still running; its later output is not captured]",
          exitCode: code ?? 0,
          timedOut: false,
        });
      }, 1500);
    });

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

/** Over the cap, keep the start and the end: the end of a log is usually what matters. */
function keepHeadAndTail(text: string): string {
  if (text.length <= MAX_OUTPUT_BYTES) return text;
  const half = Math.floor(MAX_OUTPUT_BYTES / 2);
  const dropped = text.length - 2 * half;
  return text.slice(0, half) + `
... [${dropped} characters of output omitted] ...
` + text.slice(-half);
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

/** S12: a call whose only effect was a lost `cd` / variable says so in its result. */
function withStateNote(interpretation: string, command: string, result: ExecResult, ctx: ToolUseContext): string {
  if (result.timedOut || result.exitCode !== 0) return interpretation;
  const note = shellStateNote(command, findGitBash() ? "bash" : "cmd", ctx.cwd ?? process.cwd());
  return note ? `${interpretation}; ${note}` : interpretation;
}

async function runBash(
  input: { command: string; timeout?: number },
  ctx: ToolUseContext,
): Promise<BashOutput> {
  const { command } = input;
  const timeout = input.timeout ?? BASH_TIMEOUT_MS;
  const disableBackground = process.env["EMBER_DISABLE_BACKGROUND_TASKS"] === "1";

  if (!disableBackground) {
    const bgTaskId: string | undefined = undefined;
    const startTime = Date.now();
    const result = await executeCommand(command, timeout, ctx.abortController.signal, ctx.cwd ?? process.cwd(), ctx.toolUseId);
    const elapsed = Date.now() - startTime;
    const stdoutBuf = result.stdout;
    const isImage = detectImageOutput(stdoutBuf);
    let stdout = isImage ? "[binary image output]" : stdoutBuf.toString("utf-8");
    stdout = keepHeadAndTail(stdout);
    const stderr = keepHeadAndTail(result.stderr);
    const interpretation = withStateNote(result.timedOut
      ? `Command timed out after ${Math.round(timeout / 1000)}s and was stopped (it may be waiting for input, or need a larger timeout)`
      : interpretExitCode(command, result.exitCode), command, result, ctx);
    void elapsed; void BACKGROUND_THRESHOLD_MS;
    return {
      stdout: stdout || undefined,
      stderr: stderr || undefined,
      returnCodeInterpretation: interpretation,
      noOutputExpected: stdout.length === 0 && stderr.length === 0,
      ...(bgTaskId ? { backgroundTaskId: bgTaskId } : {}),
      ...(isImage ? { isImage: true } : {}),
    };
  } else {
    const result = await executeCommand(command, timeout, ctx.abortController.signal, ctx.cwd ?? process.cwd(), ctx.toolUseId);
    const stdoutBuf = result.stdout;
    const isImage = detectImageOutput(stdoutBuf);
    let stdout = isImage ? "[binary image output]" : stdoutBuf.toString("utf-8");
    stdout = keepHeadAndTail(stdout);
    const stderr = keepHeadAndTail(result.stderr);
    return {
      stdout: stdout || undefined,
      stderr: stderr || undefined,
      returnCodeInterpretation: withStateNote(result.timedOut
        ? `Command timed out after ${Math.round(timeout / 1000)}s and was stopped (it may be waiting for input, or need a larger timeout)`
        : interpretExitCode(command, result.exitCode), command, result, ctx),
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

    prompt: (_opts?) => (findGitBash() || process.platform !== "win32" ? `## Bash tool
Runs a command with bash (Git Bash on Windows): use bash syntax (ls, cat, mkdir -p, $VAR, pipes).
Windows paths work with forward slashes (for example D:/work/notes.txt). Windows programs (python, node, git) are on PATH.
- Every call starts fresh in the project directory: cd and variables do NOT carry over to the next call.
  Chain dependent steps in one call (cd sub && make).` : `## Bash tool
Runs a command with cmd.exe on Windows (bash is not installed): use cmd syntax (dir, type, set, &&, ^ escapes).
- Every call starts fresh in the project directory: cd and set do NOT carry over to the next call.
  Chain dependent steps in one call (cd sub && build) or put them on separate lines (run as a batch file).`) + `
- Read-only commands are auto-allowed; commands that change things may ask for permission.
- Timeout default: 120 seconds (pass timeout in ms for longer jobs). There is no input: a command
  that reads input gets end of input at once. At the timeout the whole process tree is ended.
- Output over 30 KB keeps its beginning and end.`,

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
      if (isDestructiveCommand(command)) {
        return { behavior: "ask" as const, updatedInput: input, message: DESTRUCTIVE_ASK_MESSAGE };
      }
      // WebFetch refuses private/loopback addresses; a shell command that reaches one must not be a way round (W28).
      const privateHost = privateHostInCommand(command);
      if (privateHost) {
        return { behavior: "ask" as const, updatedInput: input, message: privateHostAskMessage(privateHost) };
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
      content: shellResultText(content),
    }),

    toAutoClassifierInput: (input?: BashInput) => input?.command ?? "",
  }),
  { searchHint: "execute shell commands" } as const,
);

/** Plain text for a shell result: stdout, then stderr, then the exit line. A JSON blob with \r\n
 *  escapes was shown to the user whenever stdout was empty or the output was large (blind test). */
export function shellResultText(out: { stdout?: string; stderr?: string; returnCodeInterpretation?: string }): string {
  const parts: string[] = [];
  const stdout = (out.stdout ?? "").replace(/\r\n/g, "\n").replace(/\n+$/, "");
  if (stdout.length > 0) parts.push(stdout);
  const stderr = (out.stderr ?? "").replace(/\r\n/g, "\n").trim();
  if (stderr.length > 0) parts.push(`stderr: ${stderr}`);
  if (out.returnCodeInterpretation) parts.push(`(${out.returnCodeInterpretation})`);
  return parts.length > 0 ? parts.join("\n") : "(no output)";
}
