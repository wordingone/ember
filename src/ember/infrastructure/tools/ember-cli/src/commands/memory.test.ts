// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { afterEach, describe, expect, it } from "bun:test";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createMemoryCommand } from "./memory.ts";
import { memoryDirFor } from "../services/project-context.ts";

const made: string[] = [];
afterEach(() => {
  for (const d of made.splice(0)) rmSync(d, { recursive: true, force: true });
});

describe("/memory", () => {
  it("lists the instruction files and memory index the session loaded, and the memory files", async () => {
    const base = mkdtempSync(join(tmpdir(), "ember-memcmd-"));
    made.push(base);
    const home = join(base, "home");
    const repo = join(base, "repo");
    mkdirSync(home, { recursive: true });
    mkdirSync(join(repo, ".git"), { recursive: true });
    writeFileSync(join(repo, "AGENTS.md"), "be careful", "utf-8");
    const mem = memoryDirFor(repo, home);
    mkdirSync(mem, { recursive: true });
    writeFileSync(join(mem, "MEMORY.md"), "- [Tabs](tabs.md) - prefers tabs\n", "utf-8");
    writeFileSync(join(mem, "tabs.md"), "---\nname: tabs\ndescription: prefers tabs\ntype: user\n---\nTabs.\n", "utf-8");

    const cmd = createMemoryCommand({ home: () => home });
    expect(cmd.name).toBe("memory");
    expect(cmd.isEnabled()).toBe(true);
    const res = await cmd.execute("", { sessionId: "s", mode: "default", cwd: repo });
    expect(res).toMatchObject({ type: "message" });
    const text = (res as { message: string }).message;
    expect(text).toContain("AGENTS.md");
    expect(text).toContain("MEMORY.md");
    expect(text).toContain("1 entries");
    expect(text).toContain("tabs.md - prefers tabs");
    expect(text).toContain(mem);
  });
});
