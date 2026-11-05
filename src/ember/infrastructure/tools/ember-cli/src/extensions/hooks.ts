// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// extensions/hooks.ts — user-configured hooks on agent events.
//
// Settings (user, project or local settings.json) carry a "hooks" object keyed by event:
//
//   "hooks": {
//     "PreToolUse":       [{ "matcher": "Bash", "hooks": [{ "type": "command", "command": "...", "timeout": 10 }] }],
//     "PostToolUse":      [...],
//     "UserPromptSubmit": [{ "hooks": [{ "type": "command", "command": "..." }] }],
//     "Stop":             [{ "hooks": [{ "type": "command", "command": "..." }] }]
//   }
//
// A flat entry { "matcher": "Bash", "command": "...", "timeout": 10 } is accepted too.
// `matcher` is a regex matched against the whole tool name ("" or "*" matches every tool);
// it applies to PreToolUse and PostToolUse only. `timeout` is in seconds (default 60).
//
// The hook command receives the event as JSON on stdin and runs with the project directory
// as cwd. Exit code 0: success (stdout is context for UserPromptSubmit). Exit code 2: BLOCK;
// stderr is the reason shown to the model (PreToolUse), the user (UserPromptSubmit), or fed
// back as the next instruction (Stop). Any other exit code is a non-blocking error that is
// reported and ignored. A hook that exceeds its timeout is killed and ignored. A hook may
// also print JSON: {"decision":"block","reason":"..."} or
// {"hookSpecificOutput":{"permissionDecision":"deny","permissionDecisionReason":"..."}}.

import { spawn } from "node:child_process";

export type HookEvent = "PreToolUse" | "PostToolUse" | "UserPromptSubmit" | "Stop";

export const HOOK_EVENTS: readonly HookEvent[] = ["PreToolUse", "PostToolUse", "UserPromptSubmit", "Stop"];

export const DEFAULT_HOOK_TIMEOUT_S = 60;
const MAX_CAPTURE_CHARS = 20_000;

export interface HookCommand {
  command: string;
  /** seconds */
  timeout?: number;
}

export interface HookMatcherEntry {
  /** Regex over the tool name; absent, "" or "*" matches everything. */
  matcher?: string;
  hooks: HookCommand[];
}

export type HooksConfig = Partial<Record<HookEvent, HookMatcherEntry[]>>;

export interface HookRunResult {
  command: string;
  exitCode: number | null;
  stdout: string;
  stderr: string;
  timedOut: boolean;
  /** Set when the hook asked to block (exit 2 or a block decision in JSON stdout). */
  blocked: boolean;
  reason?: string;
}

// ---------------------------------------------------------------------------
// Config parsing
// ---------------------------------------------------------------------------

/** Normalises the raw `hooks` value from settings; bad entries are dropped with a warning. */
export function parseHooksConfig(raw: unknown, warn: (m: string) => void = () => {}): HooksConfig {
  const out: HooksConfig = {};
  if (raw === undefined || raw === null) return out;
  if (typeof raw !== "object" || Array.isArray(raw)) {
    warn('settings "hooks" must be an object keyed by event name; ignored');
    return out;
  }
  for (const [event, entries] of Object.entries(raw as Record<string, unknown>)) {
    if (!(HOOK_EVENTS as readonly string[]).includes(event)) {
      warn(`unknown hook event "${event}" ignored (known: ${HOOK_EVENTS.join(", ")})`);
      continue;
    }
    if (!Array.isArray(entries)) {
      warn(`hooks.${event} must be an array; ignored`);
      continue;
    }
    const list: HookMatcherEntry[] = [];
    for (const e of entries as unknown[]) {
      if (!e || typeof e !== "object") continue;
      const entry = e as Record<string, unknown>;
      const matcher = typeof entry["matcher"] === "string" ? (entry["matcher"] as string) : undefined;
      const hooks: HookCommand[] = [];
      const addCommand = (h: Record<string, unknown>): void => {
        const type = h["type"];
        if (typeof h["command"] !== "string" || h["command"].trim() === "" || (type !== undefined && type !== "command")) {
          warn(`hooks.${event}: only {"type":"command","command":"..."} hooks are supported; entry ignored`);
          return;
        }
        const t = typeof h["timeout"] === "number" && h["timeout"] > 0 ? (h["timeout"] as number) : undefined;
        hooks.push({ command: h["command"] as string, ...(t !== undefined ? { timeout: t } : {}) });
      };
      if (Array.isArray(entry["hooks"])) {
        for (const h of entry["hooks"] as unknown[]) if (h && typeof h === "object") addCommand(h as Record<string, unknown>);
      } else if (typeof entry["command"] === "string") {
        addCommand(entry);
      }
      if (hooks.length > 0) list.push({ ...(matcher !== undefined ? { matcher } : {}), hooks });
    }
    if (list.length > 0) out[event as HookEvent] = list;
  }
  return out;
}

/** True when `matcher` selects `toolName`. An invalid regex matches nothing. */
export function matcherMatches(matcher: string | undefined, toolName: string): boolean {
  if (matcher === undefined || matcher === "" || matcher === "*") return true;
  try {
    return new RegExp(`^(?:${matcher})$`).test(toolName);
  } catch {
    return false;
  }
}

// ---------------------------------------------------------------------------
// Running one command
// ---------------------------------------------------------------------------

function clip(s: string): string {
  return s.length > MAX_CAPTURE_CHARS ? s.slice(0, MAX_CAPTURE_CHARS) + "\n[output truncated]" : s;
}

function jsonBlock(stdout: string): { blocked: boolean; reason?: string } {
  const trimmed = stdout.trim();
  if (!trimmed.startsWith("{")) return { blocked: false };
  try {
    const j = JSON.parse(trimmed) as Record<string, unknown>;
    if (j["decision"] === "block") {
      return { blocked: true, reason: typeof j["reason"] === "string" ? (j["reason"] as string) : undefined };
    }
    const sp = j["hookSpecificOutput"] as Record<string, unknown> | undefined;
    if (sp && sp["permissionDecision"] === "deny") {
      return {
        blocked: true,
        reason: typeof sp["permissionDecisionReason"] === "string" ? (sp["permissionDecisionReason"] as string) : undefined,
      };
    }
  } catch {
    // not JSON: plain output
  }
  return { blocked: false };
}

/** Stops the hook process this runner spawned (by its pid) together with its children. */
function killTree(pid: number | undefined): void {
  if (pid === undefined) return;
  try {
    if (process.platform === "win32") {
      spawn("taskkill", ["/pid", String(pid), "/T", "/F"], { stdio: "ignore", windowsHide: true }).on("error", () => {});
    } else {
      process.kill(pid, "SIGKILL");
    }
  } catch {
    // already gone
  }
}

export function runHookCommand(
  hook: HookCommand,
  payload: Record<string, unknown>,
  cwd: string,
): Promise<HookRunResult> {
  return new Promise<HookRunResult>((resolve) => {
    const timeoutMs = Math.round((hook.timeout ?? DEFAULT_HOOK_TIMEOUT_S) * 1000);
    let stdout = "";
    let stderr = "";
    let timedOut = false;
    let settled = false;
    const finish = (exitCode: number | null): void => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      const out = clip(stdout);
      const err = clip(stderr);
      let blocked = exitCode === 2;
      let reason = blocked ? err.trim() || out.trim() || undefined : undefined;
      if (!blocked && exitCode === 0) {
        const j = jsonBlock(out);
        if (j.blocked) {
          blocked = true;
          reason = j.reason ?? undefined;
        }
      }
      resolve({ command: hook.command, exitCode, stdout: out, stderr: err, timedOut, blocked, reason });
    };

    // The hook is a user-written shell command line, so it runs through the platform shell.
    const child = spawn(hook.command, {
      cwd,
      shell: true,
      stdio: ["pipe", "pipe", "pipe"],
      windowsHide: true,
      env: { ...process.env, EMBER_PROJECT_DIR: cwd },
    });
    const timer = setTimeout(() => {
      timedOut = true;
      stderr += `\nhook timed out after ${timeoutMs / 1000}s`;
      killTree(child.pid);
      // A shell wrapper's grandchildren may keep the pipes open; settle now.
      finish(null);
    }, timeoutMs);
    child.stdout!.setEncoding("utf8");
    child.stderr!.setEncoding("utf8");
    child.stdout!.on("data", (d: string) => { if (stdout.length < MAX_CAPTURE_CHARS * 2) stdout += d; });
    child.stderr!.on("data", (d: string) => { if (stderr.length < MAX_CAPTURE_CHARS * 2) stderr += d; });
    child.on("error", (e) => { stderr += `\n${e.message}`; finish(null); });
    child.on("close", (code) => finish(code));
    child.stdin!.on("error", () => {});
    try {
      child.stdin!.end(JSON.stringify(payload));
    } catch {
      // hook exited before reading stdin
    }
  });
}

// ---------------------------------------------------------------------------
// Runner
// ---------------------------------------------------------------------------

export interface HookOutcome {
  blocked: boolean;
  /** Joined reasons of the blocking hooks. */
  reason?: string;
  /** stdout of successful hooks (context for UserPromptSubmit). */
  output: string;
  results: HookRunResult[];
  /** Non-blocking problems worth showing the user (timeouts, other non-zero exits). */
  warnings: string[];
}

export interface HookRunnerOptions {
  cwd: string;
  sessionId?: string;
  /** Test seam: replaces process spawning. */
  run?: typeof runHookCommand;
}

export class HookRunner {
  constructor(private config: HooksConfig, private readonly opts: HookRunnerOptions) {}

  setConfig(config: HooksConfig): void {
    this.config = config;
  }

  hasHooks(event: HookEvent): boolean {
    return (this.config[event]?.length ?? 0) > 0;
  }

  /** Hook commands for `event` that apply to `toolName`, de-duplicated by command line. */
  select(event: HookEvent, toolName?: string): HookCommand[] {
    const seen = new Set<string>();
    const out: HookCommand[] = [];
    for (const entry of this.config[event] ?? []) {
      if ((event === "PreToolUse" || event === "PostToolUse") && !matcherMatches(entry.matcher, toolName ?? "")) continue;
      for (const h of entry.hooks) {
        if (seen.has(h.command)) continue;
        seen.add(h.command);
        out.push(h);
      }
    }
    return out;
  }

  async run(event: HookEvent, fields: Record<string, unknown> = {}, toolName?: string): Promise<HookOutcome> {
    const hooks = this.select(event, toolName);
    const outcome: HookOutcome = { blocked: false, output: "", results: [], warnings: [] };
    if (hooks.length === 0) return outcome;
    const payload = {
      session_id: this.opts.sessionId ?? "",
      cwd: this.opts.cwd,
      hook_event_name: event,
      ...(toolName !== undefined ? { tool_name: toolName } : {}),
      ...fields,
    };
    const exec = this.opts.run ?? runHookCommand;
    const results = await Promise.all(hooks.map((h) => exec(h, payload, this.opts.cwd)));
    const reasons: string[] = [];
    const outputs: string[] = [];
    for (const r of results) {
      outcome.results.push(r);
      if (r.blocked) {
        outcome.blocked = true;
        reasons.push(r.reason ?? `blocked by hook: ${r.command}`);
      } else if (r.timedOut) {
        outcome.warnings.push(`${event} hook timed out and was ignored: ${r.command}`);
      } else if (r.exitCode !== 0) {
        const detail = r.stderr.trim().split("\n")[0] ?? "";
        outcome.warnings.push(`${event} hook exited with code ${r.exitCode}${detail ? `: ${detail}` : ""} (ignored): ${r.command}`);
      } else if (r.stdout.trim() !== "") {
        outputs.push(r.stdout.trim());
      }
    }
    if (outcome.blocked) outcome.reason = reasons.join("\n");
    outcome.output = outputs.join("\n");
    return outcome;
  }
}

// ---------------------------------------------------------------------------
// Session-wide runner (the QueryEngine and the REPL both read this)
// ---------------------------------------------------------------------------

let activeRunner: HookRunner | null = null;
let warningSink: ((message: string) => void) | null = null;

export function setActiveHookRunner(runner: HookRunner | null): void {
  activeRunner = runner;
}

export function getActiveHookRunner(): HookRunner | null {
  return activeRunner;
}

/** The REPL registers where hook warnings (timeouts, failing hooks) are shown. */
export function setHookWarningSink(sink: ((message: string) => void) | null): void {
  warningSink = sink;
}

export function reportHookWarnings(outcome: HookOutcome): void {
  if (!warningSink) return;
  for (const w of outcome.warnings) {
    try { warningSink(w); } catch { /* sink errors are ignored */ }
  }
}

/** Reason text the model sees when a PreToolUse hook blocks a call. */
export function preToolUseBlockMessage(toolName: string, outcome: HookOutcome): string {
  return `PreToolUse hook blocked ${toolName}: ${outcome.reason ?? "no reason given"}`;
}
