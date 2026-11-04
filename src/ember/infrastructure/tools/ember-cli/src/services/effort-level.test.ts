// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// services/effort-level.test.ts -- issue #2370: the level -> chat_template_kwargs mapping,
// persistence, and the /effort command.

import { afterEach, beforeEach, describe, expect, it } from "bun:test";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createEffortCommand } from "../commands/effort.ts";
import { _resetConfigHomeMemo } from "../utils/env-detection.ts";
import {
  DEFAULT_EFFORT_LEVEL,
  EFFORT_LEVELS,
  _resetEffortLevelForTests,
  chatTemplateKwargsForEffort,
  getEffortLevel,
  maxTokensForEffort,
  parseEffortLevel,
} from "./effort-level.ts";

describe("effort level mapping", () => {
  it("maps each level to the template values the Qwen3.8 template accepts", () => {
    expect(chatTemplateKwargsForEffort("off")).toEqual({ enable_thinking: false });
    expect(chatTemplateKwargsForEffort("low")).toEqual({ enable_thinking: true, reasoning_effort: "low" });
    expect(chatTemplateKwargsForEffort("medium")).toEqual({ enable_thinking: true, reasoning_effort: "medium" });
    expect(chatTemplateKwargsForEffort("high")).toEqual({ enable_thinking: true, reasoning_effort: "xhigh" });
    expect(chatTemplateKwargsForEffort("max")).toEqual({ enable_thinking: true, reasoning_effort: "xhigh" });
  });

  it("never produces a reasoning_effort the template would reject", () => {
    for (const level of EFFORT_LEVELS) {
      const effort = chatTemplateKwargsForEffort(level).reasoning_effort;
      if (effort !== undefined) expect(["low", "medium", "xhigh"]).toContain(effort);
    }
  });

  it("raises the output cap to at least 32768 for max only", () => {
    expect(maxTokensForEffort("max", 8096)).toBe(32768);
    expect(maxTokensForEffort("max", 65536)).toBe(65536);
    for (const level of ["off", "low", "medium", "high"] as const) {
      expect(maxTokensForEffort(level, 8096)).toBe(8096);
    }
  });

  it("parses the five levels, case-insensitively, and nothing else", () => {
    expect(parseEffortLevel(" MAX ")).toBe("max");
    expect(parseEffortLevel("off")).toBe("off");
    expect(parseEffortLevel("xhigh")).toBeNull();
    expect(parseEffortLevel("")).toBeNull();
    expect(parseEffortLevel("auto")).toBeNull();
  });

  it("defaults to thinking on at the model's default level", () => {
    expect(DEFAULT_EFFORT_LEVEL).toBe("high");
    expect(chatTemplateKwargsForEffort(DEFAULT_EFFORT_LEVEL).enable_thinking).toBe(true);
  });
});

describe("effort level persistence and /effort", () => {
  let home: string;
  const origHome = process.env["EMBER_HOME"];

  beforeEach(async () => {
    home = await mkdtemp(join(tmpdir(), "ember-effort-"));
    process.env["EMBER_HOME"] = home;
    _resetConfigHomeMemo();
    _resetEffortLevelForTests();
  });

  afterEach(async () => {
    if (origHome === undefined) delete process.env["EMBER_HOME"];
    else process.env["EMBER_HOME"] = origHome;
    _resetConfigHomeMemo();
    _resetEffortLevelForTests();
    await rm(home, { recursive: true, force: true });
  });

  it("starts at the default when nothing is saved", () => {
    expect(getEffortLevel()).toBe("high");
  });

  it("/effort with no argument shows the current level", async () => {
    const r = await createEffortCommand().execute("", { cwd: ".", sessionId: "s", mode: "m" });
    expect(r && r.message).toContain("Thinking effort: high (default)");
  });

  it("/effort <level> changes the level and persists it in the ember home settings", async () => {
    const r = await createEffortCommand().execute("low", { cwd: ".", sessionId: "s", mode: "m" });
    expect(r && r.message).toContain("set to low");
    expect(getEffortLevel()).toBe("low");
    const saved = JSON.parse(await readFile(join(home, "settings.json"), "utf-8"));
    expect(saved.effortLevel).toBe("low");
  });

  it("keeps the other settings keys when saving the level", async () => {
    await writeFile(join(home, "settings.json"), JSON.stringify({ theme: "dark" }), "utf-8");
    await createEffortCommand().execute("max", { cwd: ".", sessionId: "s", mode: "m" });
    const saved = JSON.parse(await readFile(join(home, "settings.json"), "utf-8"));
    expect(saved).toEqual({ theme: "dark", effortLevel: "max" });
  });

  it("a new session reads the saved level back from settings", async () => {
    await writeFile(join(home, "settings.json"), JSON.stringify({ effortLevel: "off" }), "utf-8");
    expect(getEffortLevel()).toBe("off");
  });

  it("an invalid saved value falls back to the default", async () => {
    await writeFile(join(home, "settings.json"), JSON.stringify({ effortLevel: "ludicrous" }), "utf-8");
    expect(getEffortLevel()).toBe("high");
  });

  it("an unknown argument is refused and changes nothing", async () => {
    const r = await createEffortCommand().execute("ludicrous", { cwd: ".", sessionId: "s", mode: "m" });
    expect(r && r.message).toContain("Unknown effort level");
    expect(r && r.message).toContain("Usage: /effort [off|low|medium|high|max]");
    expect(getEffortLevel()).toBe("high");
  });
});
