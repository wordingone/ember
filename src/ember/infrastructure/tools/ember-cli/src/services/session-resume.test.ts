// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// services/session-resume.test.ts -- #2373: the launch flags and the data behind /resume.

import { afterEach, describe, expect, it } from "bun:test";
import { appendFileSync, mkdtempSync, rmSync, utimesSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  formatSessionList,
  formatSessionTime,
  loadFullSessionLog,
  parseResumeFlags,
  recentSessionLogs,
  resolveResumeInit,
} from "./session-resume.ts";
import { SessionWriter, sessionsDirFor } from "./session-store.ts";

const made: string[] = [];
function scratch(): string {
  const d = mkdtempSync(join(tmpdir(), "ember-resume-"));
  made.push(d);
  return d;
}
afterEach(() => {
  for (const d of made.splice(0)) rmSync(d, { recursive: true, force: true });
});

const user = (text: string) => ({ role: "user", content: [{ type: "text", text }], uuid: "u", timestamp: "t" });
const assistant = (text: string) => ({ role: "assistant", content: [{ type: "text", text }], uuid: "a", timestamp: "t" });

function seed(home: string, cwd: string, id: string, prompt: string, mtimeSecs: number): string {
  const w = new SessionWriter({ dir: sessionsDirFor(cwd, home), sessionId: id, cwd });
  w.append({ type: "append", messages: [user(prompt), assistant(`answer to ${prompt}`)] });
  utimesSync(w.path, mtimeSecs, mtimeSecs);
  return w.path;
}

const argv = (...rest: string[]) => ["bun", "ember", ...rest];

describe("parseResumeFlags", () => {
  it("reads --continue / -c", () => {
    expect(parseResumeFlags(argv("--continue"))).toEqual({ mode: "continue" });
    expect(parseResumeFlags(argv("-c"))).toEqual({ mode: "continue" });
  });

  it("reads --resume <id>, -r <id> and --resume=<id>", () => {
    expect(parseResumeFlags(argv("--resume", "abc123"))).toEqual({ mode: "resume", id: "abc123" });
    expect(parseResumeFlags(argv("-r", "abc123"))).toEqual({ mode: "resume", id: "abc123" });
    expect(parseResumeFlags(argv("--resume=abc123"))).toEqual({ mode: "resume", id: "abc123" });
  });

  it("--resume with no id (or a following flag) lists the sessions", () => {
    expect(parseResumeFlags(argv("--resume"))).toEqual({ mode: "list" });
    expect(parseResumeFlags(argv("--resume", "--other"))).toEqual({ mode: "list" });
    expect(parseResumeFlags(argv("--resume="))).toEqual({ mode: "list" });
  });

  it("is null without the flags, and never reads the runtime or script slots", () => {
    expect(parseResumeFlags(argv())).toBeNull();
    expect(parseResumeFlags(argv("--model", "x"))).toBeNull();
    expect(parseResumeFlags(["--continue", "--resume"])).toBeNull(); // the first two slots are runtime and script
  });
});

describe("resolveResumeInit", () => {
  it("--continue restores the newest session of the directory", () => {
    const home = scratch();
    seed(home, "/proj", "old-one", "first task", 1_700_000_000);
    seed(home, "/proj", "new-one", "second task", 1_800_000_000);
    seed(home, "/elsewhere", "other-dir", "unrelated", 1_900_000_000);

    const init = resolveResumeInit({ mode: "continue" }, "/proj", home);
    expect(init.sessionId).toBe("new-one");
    expect(init.messages.length).toBe(2);
    expect(JSON.stringify(init.messages[0])).toContain("second task");
    expect(init.notices.length).toBe(1);
    expect(init.notices[0]).toContain("Resumed session new-one");
    expect(init.notices[0]).toContain("2 messages");
  });

  it("--resume <id> restores that session, by full id or a unique prefix", () => {
    const home = scratch();
    seed(home, "/proj", "aaaa-1111", "alpha", 1_800_000_000);
    seed(home, "/proj", "bbbb-2222", "beta", 1_700_000_000);

    expect(resolveResumeInit({ mode: "resume", id: "bbbb-2222" }, "/proj", home).sessionId).toBe("bbbb-2222");
    const byPrefix = resolveResumeInit({ mode: "resume", id: "bb" }, "/proj", home);
    expect(byPrefix.sessionId).toBe("bbbb-2222");
    expect(JSON.stringify(byPrefix.messages[0])).toContain("beta");
  });

  it("an unknown id or an empty directory starts fresh with a notice, not an error", () => {
    const home = scratch();
    seed(home, "/proj", "aaaa-1111", "alpha", 1_800_000_000);

    const missing = resolveResumeInit({ mode: "resume", id: "nope" }, "/proj", home);
    expect(missing).toMatchObject({ sessionId: null, messages: [] });
    expect(missing.notices[0]).toContain('No session matching "nope"');

    const empty = resolveResumeInit({ mode: "continue" }, "/nothing-here", home);
    expect(empty).toMatchObject({ sessionId: null, messages: [] });
    expect(empty.notices[0]).toContain("No earlier session");
  });

  it("a corrupt line is skipped, the rest restores, and the notice says so", () => {
    const home = scratch();
    const path = seed(home, "/proj", "damaged", "keep me", 1_800_000_000);
    appendFileSync(path, "{not json at all\n", "utf-8");

    const init = resolveResumeInit({ mode: "continue" }, "/proj", home);
    expect(init.sessionId).toBe("damaged");
    expect(init.messages.length).toBe(2);
    expect(init.notices.length).toBe(2);
    expect(init.notices[1]).toContain("Skipped 1 unreadable line");
  });

  it("list mode shows the sessions with how to start one, and restores nothing", () => {
    const home = scratch();
    seed(home, "/proj", "aaaa-1111", "write the report", 1_800_000_000);
    const init = resolveResumeInit({ mode: "list" }, "/proj", home);
    expect(init.sessionId).toBeNull();
    expect(init.messages).toEqual([]);
    expect(init.notices[0]).toContain("write the report");
    expect(init.notices[0]).toContain("aaaa-111");
    expect(init.notices[0]).toContain("ember --resume <id>");

    expect(resolveResumeInit({ mode: "list" }, "/nothing-here", home).notices[0]).toContain("No earlier sessions");
  });
});

describe("session list helpers", () => {
  it("recentSessionLogs are lite entries, newest first, carrying prompt and size", () => {
    const home = scratch();
    seed(home, "/proj", "older", "first", 1_700_000_000);
    seed(home, "/proj", "newer", "second", 1_800_000_000);
    const logs = recentSessionLogs("/proj", home);
    expect(logs.map((l) => l.sessionId)).toEqual(["newer", "older"]);
    expect(logs[0]).toMatchObject({ isLite: true, isSidechain: false, firstPrompt: "second", messageCount: 2, projectPath: "/proj" });
    expect(logs[0]!.messages).toEqual([]);
  });

  it("loadFullSessionLog fills in the messages and surfaces a corrupt-line notice", () => {
    const home = scratch();
    const path = seed(home, "/proj", "full", "load me", 1_800_000_000);
    appendFileSync(path, "garbage\n", "utf-8");
    const lite = recentSessionLogs("/proj", home)[0]!;
    const full = loadFullSessionLog(lite);
    expect(full.isLite).toBe(false);
    expect(full.messages.length).toBe(2);
    expect(full.notice).toContain("Skipped 1 unreadable line");

    const clean = recentSessionLogs("/proj", home);
    const gone = loadFullSessionLog({ ...clean[0]!, fullPath: join(home, "missing.jsonl") });
    expect(gone.isLite).toBe(true); // unreadable: the entry comes back untouched
  });

  it("formatSessionList numbers the rows with time, prompt, size and id prefix", () => {
    const text = formatSessionList([
      { modified: new Date(2026, 10, 3, 9, 5), firstPrompt: "fix login", messageCount: 4, sessionId: "abcdef12-3456" },
      { modified: new Date(2026, 10, 2, 18, 30), firstPrompt: "", messageCount: 1, sessionId: "zz" },
    ]);
    const lines = text.split("\n");
    expect(lines[0]).toBe("Recent sessions in this directory:");
    expect(lines[1]).toBe("   1. 2026-11-03 09:05  fix login  (4 messages)  abcdef12");
    expect(lines[2]).toContain("2. 2026-11-02 18:30  (no prompt)");
    expect(formatSessionTime(new Date(2026, 0, 2, 3, 4))).toBe("2026-01-02 03:04");
  });
});
