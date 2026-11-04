// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// services/session-store.test.ts -- #2373: sessions are appended as JSONL and read back intact,
// a damaged line is skipped with a notice, and listings carry the first prompt and time.

import { afterEach, describe, expect, it } from "bun:test";
import { appendFileSync, mkdirSync, mkdtempSync, readFileSync, rmSync, utimesSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { projectKey } from "./project-key.ts";
import {
  decodeMessage,
  describeSkippedLines,
  encodeMessage,
  findSession,
  latestSession,
  listSessions,
  loadSessionFile,
  parseSessionText,
  SessionWriter,
  sessionsDirFor,
} from "./session-store.ts";

const made: string[] = [];
function scratch(): string {
  const d = mkdtempSync(join(tmpdir(), "ember-sess-"));
  made.push(d);
  return d;
}
afterEach(() => {
  for (const d of made.splice(0)) rmSync(d, { recursive: true, force: true });
});

const user = (text: string) => ({ role: "user", content: [{ type: "text", text }], uuid: "u", timestamp: "t" });
const assistant = (text: string) => ({
  role: "assistant",
  content: [{ type: "text", text }],
  uuid: "a",
  timestamp: "t",
  message: { role: "assistant", content: [{ type: "text", text }], stop_reason: "end_turn" },
});
function toolResult(id: string, content: string) {
  const blocks = [{ type: "tool_result", tool_use_id: id, content }];
  return { role: "user", content: blocks, uuid: "r", timestamp: "t", toolUseResult: blocks };
}

function writerFor(home: string, cwd: string, sessionId: string, onError?: (m: string) => void) {
  return new SessionWriter({
    dir: sessionsDirFor(cwd, home),
    sessionId,
    cwd,
    now: () => new Date("2026-11-03T04:00:00Z"),
    ...(onError ? { onError } : {}),
  });
}

describe("projectKey", () => {
  it("is filesystem safe, stable, and distinguishes paths that sanitize alike", () => {
    const a = projectKey("/Users/Me/my project");
    expect(a).toMatch(/^[A-Za-z0-9._-]+$/);
    expect(projectKey("/Users/Me/my project")).toBe(a);
    expect(projectKey("/Users/Me/my-project")).not.toBe(a);
  });
});

describe("message encoding", () => {
  it("drops the engine's derived fields and rebuilds them", () => {
    const stored = encodeMessage(assistant("hi")) as Record<string, unknown>;
    expect(stored["message"]).toBeUndefined();
    const tr = encodeMessage(toolResult("t1", "out")) as Record<string, unknown>;
    expect(tr["toolUseResult"]).toBeUndefined();
    expect(tr["toolResultMirror"]).toBe(true);
    const back = decodeMessage(JSON.parse(JSON.stringify(tr))) as Record<string, unknown>;
    expect(back["toolUseResult"]).toEqual(back["content"]);
    expect(back["toolResultMirror"]).toBeUndefined();
  });
});

describe("SessionWriter + loadSessionFile", () => {
  it("round-trips the messages of a session, appending across writer instances", () => {
    const home = scratch();
    const cwd = "/proj";
    const w = writerFor(home, cwd, "sess-1");
    w.append({ type: "append", messages: [user("remember the word PLUM")] });
    w.append({ type: "append", messages: [assistant("noted"), user("and more")] });
    writerFor(home, cwd, "sess-1").append({ type: "append", messages: [assistant("later")] });

    const loaded = loadSessionFile(w.path)!;
    expect(loaded.sessionId).toBe("sess-1");
    expect(loaded.cwd).toBe(cwd);
    expect(loaded.skippedLines).toEqual([]);
    expect(loaded.messages.length).toBe(4);
    expect((loaded.messages[0] as { content: Array<{ text: string }> }).content[0]!.text).toContain("PLUM");
    expect(loaded.messages[3]).toMatchObject({ role: "assistant" });
    const lines = readFileSync(w.path, "utf-8").trim().split("\n");
    expect(JSON.parse(lines[0]!).type).toBe("meta");
    expect(lines.length).toBe(1 + 4);
  });

  it("a replace entry (compaction) resets the log to the compacted messages", () => {
    const home = scratch();
    const w = writerFor(home, "/proj", "sess-2");
    w.append({ type: "append", messages: [user("a"), assistant("b"), user("c")] });
    w.append({ type: "replace", messages: [user("[compacted conversation summary]\nS"), user("c")] });
    w.append({ type: "append", messages: [assistant("d")] });
    const loaded = loadSessionFile(w.path)!;
    expect(loaded.messages.length).toBe(3);
    expect(JSON.stringify(loaded.messages[0])).toContain("compacted conversation summary");
    expect(JSON.stringify(loaded.messages[2])).toContain('"d"');
  });

  it("skips a corrupt line with a notice instead of failing, and keeps every good line", () => {
    const home = scratch();
    const w = writerFor(home, "/proj", "sess-3");
    w.append({ type: "append", messages: [user("first")] });
    appendFileSync(w.path, "{this is not json\n", "utf-8");
    appendFileSync(w.path, JSON.stringify({ type: "message", message: "not an object" }) + "\n", "utf-8");
    appendFileSync(w.path, JSON.stringify({ type: "mystery" }) + "\n", "utf-8");
    w.append({ type: "append", messages: [assistant("second")] });

    const loaded = loadSessionFile(w.path)!;
    expect(loaded.messages.length).toBe(2);
    expect(loaded.skippedLines).toEqual([3, 4, 5]);
    expect(describeSkippedLines(loaded)).toBe("Skipped 3 unreadable lines in session sess-3 (line 3, 4, 5).");
  });

  it("a crash-truncated last line is skipped, and the next append starts on a fresh line", () => {
    const home = scratch();
    const w = writerFor(home, "/proj", "sess-4");
    w.append({ type: "append", messages: [user("kept")] });
    appendFileSync(w.path, '{"type":"message","ts":"x","message":{"role":"assi', "utf-8"); // no newline
    writerFor(home, "/proj", "sess-4").append({ type: "append", messages: [assistant("after the crash")] });
    const loaded = loadSessionFile(w.path)!;
    expect(loaded.messages.length).toBe(2);
    expect(loaded.skippedLines.length).toBe(1);
    expect(JSON.stringify(loaded.messages[1])).toContain("after the crash");
  });

  it("describeSkippedLines is null when nothing was skipped", () => {
    expect(describeSkippedLines({ sessionId: "abc", skippedLines: [] })).toBeNull();
  });

  it("never throws when the directory cannot be written, and reports it once", () => {
    const home = scratch();
    const blocker = join(home, "blocker");
    writeFileSync(blocker, "a file where a directory is needed");
    const errors: string[] = [];
    const w = new SessionWriter({ dir: join(blocker, "sub"), sessionId: "s", cwd: "/p", onError: (m) => errors.push(m) });
    w.append({ type: "append", messages: [user("x")] });
    w.append({ type: "append", messages: [user("y")] });
    expect(errors.length).toBe(1);
    expect(errors[0]).toContain("not being saved");
  });

  it("an unreadable file loads as null", () => {
    expect(loadSessionFile(join(scratch(), "missing.jsonl"))).toBeNull();
  });

  it("parseSessionText accepts CRLF files", () => {
    const text = [
      JSON.stringify({ type: "meta", v: 1, sessionId: "s9", cwd: "/p", startedAt: "2026-11-03T00:00:00Z" }),
      JSON.stringify({ type: "message", ts: "t", message: user("hi") }),
      "",
    ].join("\r\n");
    const s = parseSessionText(text, "x/s9.jsonl", new Date(0));
    expect(s.messages.length).toBe(1);
    expect(s.skippedLines).toEqual([]);
  });
});

describe("listing sessions", () => {
  function seed(home: string, cwd: string, id: string, prompt: string, mtimeSecs: number, extra = 0): string {
    const w = writerFor(home, cwd, id);
    w.append({ type: "append", messages: [user(prompt), assistant("ok"), ...Array.from({ length: extra }, () => user("more"))] });
    utimesSync(w.path, mtimeSecs, mtimeSecs);
    return w.path;
  }

  it("lists newest first with first prompt, time and message count, scoped to the cwd", () => {
    const home = scratch();
    seed(home, "/proj", "old-session", "fix the login bug", 1_700_000_000);
    seed(home, "/proj", "new-session", "write the report\nin two parts", 1_800_000_000, 2);
    seed(home, "/other", "elsewhere", "unrelated", 1_900_000_000);

    const list = listSessions("/proj", home);
    expect(list.map((s) => s.sessionId)).toEqual(["new-session", "old-session"]);
    expect(list[0]!.firstPrompt).toBe("write the report in two parts");
    expect(list[0]!.messageCount).toBe(4);
    expect(list[1]!.messageCount).toBe(2);
    expect(list[0]!.modified.getTime()).toBe(1_800_000_000_000);
    expect(list[0]!.created.toISOString()).toBe("2026-11-03T04:00:00.000Z");
  });

  it("truncates a long first prompt and skips compaction summaries and tool results", () => {
    const home = scratch();
    const w = writerFor(home, "/proj", "s-long");
    w.append({
      type: "append",
      messages: [user("[compacted conversation summary]\nold"), toolResult("t", "x"), user("y".repeat(200))],
    });
    const s = listSessions("/proj", home)[0]!;
    expect(s.firstPrompt.length).toBe(80);
    expect(s.firstPrompt.endsWith("…")).toBe(true);
    expect(s.firstPrompt.startsWith("yyy")).toBe(true);
  });

  it("ignores empty session files and a missing directory", () => {
    const home = scratch();
    expect(listSessions("/nothing", home)).toEqual([]);
    mkdirSync(sessionsDirFor("/proj", home), { recursive: true });
    writeFileSync(join(sessionsDirFor("/proj", home), "empty.jsonl"), "");
    expect(listSessions("/proj", home)).toEqual([]);
  });

  it("findSession matches an id or a unique prefix; latestSession is the newest", () => {
    const home = scratch();
    seed(home, "/proj", "abcd-1111", "one", 1_700_000_000);
    seed(home, "/proj", "abef-2222", "two", 1_800_000_000);
    expect(findSession("/proj", "abcd", home)?.sessionId).toBe("abcd-1111");
    expect(findSession("/proj", "ab", home)).toBeNull(); // ambiguous
    expect(findSession("/proj", "abef-2222", home)?.sessionId).toBe("abef-2222");
    expect(findSession("/proj", "zzz", home)).toBeNull();
    expect(latestSession("/proj", home)?.sessionId).toBe("abef-2222");
  });
});
