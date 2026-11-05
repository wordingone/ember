// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// resume.session.test.ts -- #2373: /resume lists this directory's sessions and restores one.

import { beforeEach, describe, expect, it } from "bun:test";
import { resetResumeDeps, resumeCommand, setResumeDeps } from "./resume.ts";
import type { CommandContext } from "./types/command-types.ts";
import type { LogOption } from "./types/session-persistence-types.ts";

function log(id: string, firstPrompt: string, at: Date, extra: Partial<LogOption> = {}): LogOption {
  return {
    date: at.toISOString(),
    messages: [],
    fullPath: `/sessions/${id}.jsonl`,
    value: 0,
    created: at,
    modified: at,
    firstPrompt,
    messageCount: 3,
    fileSize: 10,
    isSidechain: false,
    isLite: true,
    sessionId: id,
    projectPath: "/proj",
    ...extra,
  };
}

const ctx: CommandContext = { sessionId: "current", mode: "default", cwd: "/proj" };
const sessions = [
  log("aaaa1111", "write the report", new Date(2026, 10, 3, 9, 0)),
  log("bbbb2222", "fix the login bug", new Date(2026, 10, 2, 9, 0)),
  log("cccc3333", "fix the logout bug", new Date(2026, 10, 1, 9, 0)),
];

type Resumed = { id: string; log: LogOption };
let resumed: Resumed[] = [];

beforeEach(() => {
  resetResumeDeps();
  resumed = [];
  setResumeDeps({
    getSessions: async () => sessions,
    openPicker: undefined,
    loadFullLog: async (l) => ({ ...l, isLite: false, messages: [{ role: "user", content: [] }] }),
    onResume: async (id, l) => {
      resumed.push({ id, log: l });
      return { type: "message" as const, message: `Resumed ${id}` };
    },
  });
});

describe("/resume without a picker", () => {
  it("lists the sessions with first prompt and time, and says how to pick one", async () => {
    const res = await resumeCommand.execute("", ctx);
    expect(res).toMatchObject({ type: "message" });
    const text = (res as { message: string }).message;
    expect(text).toContain("write the report");
    expect(text).toContain("fix the login bug");
    expect(text).toContain("2026-11-03 09:00");
    expect(text).toContain("/resume <number|id|text>");
    expect(resumed).toEqual([]);
  });

  it("says so when there is nothing to resume", async () => {
    setResumeDeps({ getSessions: async () => [] });
    expect(await resumeCommand.execute("", ctx)).toEqual({ type: "message", message: "No earlier sessions in this directory." });
  });

  it("never offers the running session", async () => {
    setResumeDeps({ getSessions: async () => [log("current", "this very one", new Date()), ...sessions] });
    const res = (await resumeCommand.execute("", ctx)) as { message: string };
    expect(res.message).not.toContain("this very one");
  });
});

describe("/resume <selector>", () => {
  it("restores by list number", async () => {
    const res = await resumeCommand.execute("2", ctx);
    expect(resumed.map((r) => r.id)).toEqual(["bbbb2222"]);
    expect(resumed[0]!.log.isLite).toBe(false); // the full log is loaded before restoring
    expect(res).toEqual({ type: "message", message: "Resumed bbbb2222" });
  });

  it("restores by id prefix", async () => {
    await resumeCommand.execute("cccc", ctx);
    expect(resumed.map((r) => r.id)).toEqual(["cccc3333"]);
  });

  it("restores by a unique piece of the first prompt", async () => {
    await resumeCommand.execute("report", ctx);
    expect(resumed.map((r) => r.id)).toEqual(["aaaa1111"]);
  });

  it("an ambiguous or unknown selector restores nothing and shows the choices", async () => {
    const ambiguous = (await resumeCommand.execute("fix the", ctx)) as { message: string };
    expect(resumed).toEqual([]);
    expect(ambiguous.message).toContain("fix the login bug");
    expect(ambiguous.message).toContain("fix the logout bug");
    expect(ambiguous.message).not.toContain("write the report");

    const unknown = (await resumeCommand.execute("zzz", ctx)) as { message: string };
    expect(resumed).toEqual([]);
    expect(unknown.message).toContain("write the report");
  });

  it("an out-of-range number falls through to the list rather than throwing", async () => {
    const res = (await resumeCommand.execute("9", ctx)) as { message: string };
    expect(resumed).toEqual([]);
    expect(res.message).toContain("write the report");
  });
});
