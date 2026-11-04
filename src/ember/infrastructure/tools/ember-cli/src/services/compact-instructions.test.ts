// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// services/compact-instructions.test.ts -- standing compaction instructions (#2372).

import { afterEach, describe, expect, it } from "bun:test";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { extractCompactSection, loadStandingCompactInstructions } from "./compact-instructions.ts";

const made: string[] = [];
function scratch(): string {
  const d = mkdtempSync(join(tmpdir(), "ember-compact-"));
  made.push(d);
  return d;
}
afterEach(() => {
  for (const d of made.splice(0)) rmSync(d, { recursive: true, force: true });
});

describe("extractCompactSection", () => {
  it("returns the body up to the next heading of the same or higher level", () => {
    const md = ["# Project", "intro", "## Compact Instructions", "Keep test names.", "", "- and file paths", "### Detail", "kept too", "## Other", "not this"].join("\n");
    expect(extractCompactSection(md)).toBe("Keep test names.\n\n- and file paths\n### Detail\nkept too");
  });

  it("accepts the Summary Instructions spelling, any case, and CRLF", () => {
    expect(extractCompactSection("# summary INSTRUCTIONS\r\nBe brief.\r\n")).toBe("Be brief.");
  });

  it("is null without the section or with an empty one", () => {
    expect(extractCompactSection("# Notes\ntext")).toBeNull();
    expect(extractCompactSection("## Compact instructions\n\n## Next\nx")).toBeNull();
  });
});

describe("loadStandingCompactInstructions", () => {
  it("combines the settings field with sections from user and project instruction files", async () => {
    const home = scratch();
    const repo = scratch();
    mkdirSync(join(repo, ".git"));
    writeFileSync(join(home, "EMBER.md"), "# Mine\n## Compact Instructions\nUSER-RULE\n");
    writeFileSync(join(repo, "AGENTS.md"), "## Compact Instructions\nPROJECT-RULE\n");
    writeFileSync(join(repo, "CLAUDE.md"), "no section here");
    const text = await loadStandingCompactInstructions({
      cwd: repo,
      home,
      loadSettings: async () => ({ compactInstructions: "SETTINGS-RULE" }),
    });
    expect(text).toBe("SETTINGS-RULE\n\nUSER-RULE\n\nPROJECT-RULE");
  });

  it("is undefined when nothing is configured, and survives unreadable settings", async () => {
    const home = scratch();
    const repo = scratch();
    expect(await loadStandingCompactInstructions({ cwd: repo, home, loadSettings: async () => ({}) })).toBeUndefined();
    const failing = await loadStandingCompactInstructions({
      cwd: repo,
      home,
      loadSettings: async () => {
        throw new Error("bad json");
      },
    });
    expect(failing).toBeUndefined();
  });

  it("ignores a non-string compactInstructions value", async () => {
    const home = scratch();
    const repo = scratch();
    const text = await loadStandingCompactInstructions({ cwd: repo, home, loadSettings: async () => ({ compactInstructions: 42 }) });
    expect(text).toBeUndefined();
  });
});
