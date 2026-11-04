// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// services/session-store.ts -- append-only JSONL persistence of a conversation (#2373).
//
// One file per session: $EMBER_HOME/sessions/<project key>/<session id>.jsonl. Every line is a
// JSON object:
//   {"type":"meta","v":1,"sessionId":...,"cwd":...,"startedAt":...}     first line
//   {"type":"message","ts":...,"message":{...}}                         one engine message
//   {"type":"replace","ts":...,"messages":[...]}                        compaction: the log is now this
// Replaying the lines in order rebuilds exactly the engine's message log. The file is only ever
// appended to, so a crash loses at most the line being written, and a damaged line is skipped
// (and counted) on load instead of failing the session.

import {
  appendFileSync, closeSync, existsSync, mkdirSync, openSync, readdirSync, readFileSync, readSync, statSync,
} from "node:fs";
import { join } from "node:path";
import { getEmberConfigHomeDir } from "../utils/env-detection.ts";
import { projectKey } from "./project-key.ts";

export const SESSION_FILE_VERSION = 1;

export type MessageChange =
  | { type: "append"; messages: unknown[] }
  | { type: "replace"; messages: unknown[] };

export function sessionsDirFor(cwd: string, home: string = getEmberConfigHomeDir()): string {
  return join(home, "sessions", projectKey(cwd));
}

// ---------------------------------------------------------------------------
// Message <-> disk form
// ---------------------------------------------------------------------------
// The engine keeps two derived fields that the model never sees and that would double the file:
// an assistant message's raw `message` response, and a tool-result message's `toolUseResult`
// (the same array as its `content`). They are dropped on write and rebuilt on read.

function asRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

export function encodeMessage(message: unknown): unknown {
  const m = asRecord(message);
  if (m === null) return message;
  const out: Record<string, unknown> = { ...m };
  delete out["message"];
  if (out["toolUseResult"] !== undefined) {
    delete out["toolUseResult"];
    out["toolResultMirror"] = true;
  }
  return out;
}

export function decodeMessage(stored: unknown): unknown {
  const m = asRecord(stored);
  if (m === null) return stored;
  if (m["toolResultMirror"] === true) {
    const { toolResultMirror: _drop, ...rest } = m;
    return { ...rest, toolUseResult: rest["content"] };
  }
  return stored;
}

// ---------------------------------------------------------------------------
// Writer
// ---------------------------------------------------------------------------

export interface SessionWriterOpts {
  dir: string;
  sessionId: string;
  cwd: string;
  now?: () => Date;
  /** Called once with the first write failure; later failures are dropped silently. */
  onError?: (message: string) => void;
}

export class SessionWriter {
  readonly path: string;
  private readonly opts: SessionWriterOpts;
  private failed = false;
  private tailChecked = false;

  constructor(opts: SessionWriterOpts) {
    this.opts = opts;
    this.path = join(opts.dir, `${opts.sessionId}.jsonl`);
  }

  /**
   * A crash can leave the file's last line without its newline. Before the first write to an
   * existing file, start on a fresh line so the new entry is not glued onto the damaged one.
   */
  private freshLinePrefix(): string {
    if (this.tailChecked) return "";
    this.tailChecked = true;
    try {
      const size = statSync(this.path).size;
      if (size === 0) return "";
      const fd = openSync(this.path, "r");
      try {
        const last = Buffer.alloc(1);
        readSync(fd, last, 0, 1, size - 1);
        return last[0] === 0x0a ? "" : "\n";
      } finally {
        closeSync(fd);
      }
    } catch {
      return "";
    }
  }

  /** Appends a change to the session file. Never throws: a full disk must not end the turn. */
  append(change: MessageChange): void {
    if (this.failed || change.messages.length === 0) return;
    const ts = (this.opts.now?.() ?? new Date()).toISOString();
    try {
      const lines: string[] = [];
      if (!existsSync(this.path)) {
        mkdirSync(this.opts.dir, { recursive: true });
        lines.push(
          JSON.stringify({
            type: "meta",
            v: SESSION_FILE_VERSION,
            sessionId: this.opts.sessionId,
            cwd: this.opts.cwd,
            startedAt: ts,
          }),
        );
      }
      if (change.type === "append") {
        for (const message of change.messages) {
          lines.push(JSON.stringify({ type: "message", ts, message: encodeMessage(message) }));
        }
      } else {
        lines.push(JSON.stringify({ type: "replace", ts, messages: change.messages.map(encodeMessage) }));
      }
      appendFileSync(this.path, this.freshLinePrefix() + lines.join("\n") + "\n", "utf-8");
    } catch (err) {
      this.failed = true;
      this.opts.onError?.(
        `Session history is not being saved (${err instanceof Error ? err.message : String(err)}).`,
      );
    }
  }
}

// ---------------------------------------------------------------------------
// Reader
// ---------------------------------------------------------------------------

export interface LoadedSession {
  sessionId: string;
  path: string;
  cwd: string;
  startedAt: string | null;
  modified: Date;
  messages: unknown[];
  /** 1-based numbers of lines that could not be read and were skipped. */
  skippedLines: number[];
}

/** Text of a user message's first text block, or "" for tool results and non-text content. */
export function userPromptText(message: unknown): string {
  const m = asRecord(message);
  if (m === null || m["role"] !== "user") return "";
  const content = m["content"];
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  for (const block of content) {
    const b = asRecord(block);
    if (b !== null && b["type"] === "text" && typeof b["text"] === "string") return b["text"];
  }
  return "";
}

function sessionIdFromPath(path: string): string {
  const name = path.replace(/\\/g, "/").split("/").pop() ?? path;
  return name.replace(/\.jsonl$/, "");
}

export function parseSessionText(text: string, path: string, modified: Date): LoadedSession {
  const session: LoadedSession = {
    sessionId: sessionIdFromPath(path),
    path,
    cwd: "",
    startedAt: null,
    modified,
    messages: [],
    skippedLines: [],
  };
  const lines = text.split(/\r?\n/);
  for (let i = 0; i < lines.length; i++) {
    const raw = lines[i]!;
    if (raw.trim() === "") continue;
    let entry: Record<string, unknown> | null;
    try {
      entry = asRecord(JSON.parse(raw));
    } catch {
      entry = null;
    }
    const type = entry?.["type"];
    if (entry !== null && type === "meta") {
      if (typeof entry["sessionId"] === "string") session.sessionId = entry["sessionId"];
      if (typeof entry["cwd"] === "string") session.cwd = entry["cwd"];
      if (typeof entry["startedAt"] === "string") session.startedAt = entry["startedAt"];
    } else if (entry !== null && type === "message" && asRecord(entry["message"]) !== null) {
      session.messages.push(decodeMessage(entry["message"]));
    } else if (
      entry !== null && type === "replace" && Array.isArray(entry["messages"]) &&
      (entry["messages"] as unknown[]).every((m) => asRecord(m) !== null)
    ) {
      session.messages = (entry["messages"] as unknown[]).map(decodeMessage);
    } else {
      session.skippedLines.push(i + 1);
    }
  }
  return session;
}

/** Loads one session file; null when it cannot be read at all. */
export function loadSessionFile(path: string): LoadedSession | null {
  try {
    return parseSessionText(readFileSync(path, "utf-8"), path, statSync(path).mtime);
  } catch {
    return null;
  }
}

/** One line telling the user what a load skipped; null when nothing was skipped. */
export function describeSkippedLines(session: Pick<LoadedSession, "sessionId" | "skippedLines">): string | null {
  const n = session.skippedLines.length;
  if (n === 0) return null;
  const shown = session.skippedLines.slice(0, 5).join(", ") + (n > 5 ? ", ..." : "");
  return `Skipped ${n} unreadable line${n === 1 ? "" : "s"} in session ${session.sessionId.slice(0, 8)} (line ${shown}).`;
}

// ---------------------------------------------------------------------------
// Listing
// ---------------------------------------------------------------------------

export interface SessionSummary {
  sessionId: string;
  path: string;
  firstPrompt: string;
  created: Date;
  modified: Date;
  messageCount: number;
  fileSize: number;
}

const FIRST_PROMPT_MAX = 80;

function summarize(path: string): SessionSummary | null {
  let text: string;
  let st: ReturnType<typeof statSync>;
  try {
    st = statSync(path);
    text = readFileSync(path, "utf-8");
  } catch {
    return null;
  }
  let sessionId = sessionIdFromPath(path);
  let created: Date = st.birthtime.getTime() > 0 ? st.birthtime : st.mtime;
  let firstPrompt = "";
  let messageCount = 0;
  for (const raw of text.split("\n")) {
    if (raw === "") continue;
    if (raw.startsWith('{"type":"message"')) {
      messageCount++;
      if (firstPrompt === "") {
        try {
          const prompt = userPromptText((JSON.parse(raw) as { message?: unknown }).message).trim();
          if (prompt !== "" && !prompt.startsWith("[compacted conversation summary]")) firstPrompt = prompt;
        } catch {
          // a damaged line is reported when the session is loaded; here it just has no prompt
        }
      }
    } else if (raw.startsWith('{"type":"meta"')) {
      try {
        const meta = JSON.parse(raw) as { sessionId?: unknown; startedAt?: unknown };
        if (typeof meta.sessionId === "string") sessionId = meta.sessionId;
        if (typeof meta.startedAt === "string" && !Number.isNaN(Date.parse(meta.startedAt))) {
          created = new Date(meta.startedAt);
        }
      } catch {
        // ignore a damaged meta line
      }
    }
  }
  if (messageCount === 0) return null; // nothing to resume
  const oneLine = firstPrompt.replace(/\s+/g, " ");
  return {
    sessionId,
    path,
    firstPrompt: oneLine.length > FIRST_PROMPT_MAX ? oneLine.slice(0, FIRST_PROMPT_MAX - 1) + "…" : oneLine,
    created,
    modified: st.mtime,
    messageCount,
    fileSize: st.size,
  };
}

/** Sessions recorded for `cwd`, most recently modified first. */
export function listSessions(cwd: string, home?: string, limit = 50): SessionSummary[] {
  const dir = sessionsDirFor(cwd, home);
  let names: string[];
  try {
    names = readdirSync(dir).filter((n) => n.endsWith(".jsonl"));
  } catch {
    return [];
  }
  const dated: Array<{ path: string; mtime: number }> = [];
  for (const name of names) {
    const path = join(dir, name);
    try {
      dated.push({ path, mtime: statSync(path).mtimeMs });
    } catch {
      // vanished between readdir and stat
    }
  }
  dated.sort((a, b) => b.mtime - a.mtime);
  const out: SessionSummary[] = [];
  for (const { path } of dated) {
    const s = summarize(path);
    if (s !== null) out.push(s);
    if (out.length >= limit) break;
  }
  return out;
}

/** The session whose id equals or starts with `idOrPrefix`; null when none or ambiguous. */
export function findSession(cwd: string, idOrPrefix: string, home?: string): SessionSummary | null {
  const wanted = idOrPrefix.trim();
  if (wanted === "") return null;
  const all = listSessions(cwd, home, 500);
  const exact = all.find((s) => s.sessionId === wanted);
  if (exact) return exact;
  const prefixed = all.filter((s) => s.sessionId.startsWith(wanted));
  return prefixed.length === 1 ? prefixed[0]! : null;
}

export function latestSession(cwd: string, home?: string): SessionSummary | null {
  return listSessions(cwd, home, 1)[0] ?? null;
}
