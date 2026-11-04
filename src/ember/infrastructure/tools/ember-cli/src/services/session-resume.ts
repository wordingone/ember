// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// services/session-resume.ts -- finding and loading a session to continue (#2373):
// the `--continue` / `--resume <id>` launch flags and the data behind the /resume command.

import type { LogOption } from "../types/session-persistence-types.ts";
import {
  describeSkippedLines,
  findSession,
  latestSession,
  listSessions,
  loadSessionFile,
  type SessionSummary,
} from "./session-store.ts";

export type ResumeRequest =
  | { mode: "continue" }
  | { mode: "resume"; id: string }
  /** `--resume` with no id: list the sessions instead of picking one. */
  | { mode: "list" };

/** The resume flag in `argv` (process.argv shape: runtime, script, then arguments), if any. */
export function parseResumeFlags(argv: string[]): ResumeRequest | null {
  const args = argv.slice(2);
  for (let i = 0; i < args.length; i++) {
    const a = args[i]!;
    if (a === "--continue" || a === "-c") return { mode: "continue" };
    if (a.startsWith("--resume=")) {
      const id = a.slice("--resume=".length).trim();
      return id === "" ? { mode: "list" } : { mode: "resume", id };
    }
    if (a === "--resume" || a === "-r") {
      const next = args[i + 1];
      return next !== undefined && !next.startsWith("-") ? { mode: "resume", id: next } : { mode: "list" };
    }
  }
  return null;
}

/** What a REPL needs to start from a recorded session. */
export interface ResumeInit {
  /** The session being continued, or null when none was found (a fresh session starts). */
  sessionId: string | null;
  messages: unknown[];
  /** One-line notices to show above the restored transcript. */
  notices: string[];
}

function pad(n: number): string {
  return String(n).padStart(2, "0");
}

export function formatSessionTime(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** Numbered list of sessions: time, first prompt, size, id prefix. */
export function formatSessionList(sessions: ReadonlyArray<Pick<LogOption, "modified" | "firstPrompt" | "messageCount" | "sessionId">>): string {
  const lines = sessions.map(
    (s, i) =>
      `  ${String(i + 1).padStart(2)}. ${formatSessionTime(s.modified)}  ${s.firstPrompt === "" ? "(no prompt)" : s.firstPrompt}` +
      `  (${s.messageCount} messages)  ${s.sessionId.slice(0, 8)}`,
  );
  return ["Recent sessions in this directory:", ...lines].join("\n");
}

export function summaryToLogOption(s: SessionSummary, cwd: string, index = 0): LogOption {
  return {
    date: s.modified.toISOString(),
    messages: [],
    fullPath: s.path,
    value: index,
    created: s.created,
    modified: s.modified,
    firstPrompt: s.firstPrompt,
    messageCount: s.messageCount,
    fileSize: s.fileSize,
    isSidechain: false,
    isLite: true,
    sessionId: s.sessionId,
    projectPath: cwd,
  };
}

/** Production `getSessions` for the /resume command. */
export function recentSessionLogs(cwd: string, home?: string): LogOption[] {
  return listSessions(cwd, home, 20).map((s, i) => summaryToLogOption(s, cwd, i));
}

/** Production `loadFullLog`: the same entry with its messages read from disk. */
export function loadFullSessionLog(log: LogOption): LogOption {
  const loaded = loadSessionFile(log.fullPath);
  if (loaded === null) return log;
  const notice = describeSkippedLines(loaded);
  return { ...log, isLite: false, messages: loaded.messages, messageCount: loaded.messages.length, ...(notice ? { notice } : {}) };
}

/** Resolves a launch request against the sessions recorded for `cwd`. */
export function resolveResumeInit(req: ResumeRequest, cwd: string, home?: string): ResumeInit {
  if (req.mode === "list") {
    const sessions = recentSessionLogs(cwd, home);
    return {
      sessionId: null,
      messages: [],
      notices: [
        sessions.length === 0
          ? "No earlier sessions in this directory."
          : `${formatSessionList(sessions)}\nStart one with: ember --resume <id>`,
      ],
    };
  }
  const found = req.mode === "continue" ? latestSession(cwd, home) : findSession(cwd, req.id, home);
  if (found === null) {
    return {
      sessionId: null,
      messages: [],
      notices:
        req.mode === "continue"
          ? ["No earlier session in this directory to continue; starting a new one."]
          : [`No session matching "${req.id}" in this directory; starting a new one.`],
    };
  }
  const loaded = loadSessionFile(found.path);
  if (loaded === null || loaded.messages.length === 0) {
    return { sessionId: null, messages: [], notices: [`Session ${found.sessionId.slice(0, 8)} could not be read; starting a new one.`] };
  }
  const skipped = describeSkippedLines(loaded);
  return {
    sessionId: loaded.sessionId,
    messages: loaded.messages,
    notices: [
      `Resumed session ${loaded.sessionId.slice(0, 8)} from ${formatSessionTime(found.modified)} (${loaded.messages.length} messages).`,
      ...(skipped ? [skipped] : []),
    ],
  };
}
