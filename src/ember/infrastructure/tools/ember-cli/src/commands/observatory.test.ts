// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// commands/observatory.test.ts — tests for /observatory slash command (AC6-AC8)
// Spec: specs/surface6-fireball-observatory.md

import { describe, it, expect } from "bun:test";
import { runObservatory, createObservatoryCommand } from "./observatory.ts";
import type { CognitiveMode } from "../cognitive-mode.ts";

// ---------------------------------------------------------------------------
// AC6: registered under name 'observatory' with alias 'obs'
// ---------------------------------------------------------------------------

describe("AC6: /observatory command registration", () => {
  it("command name is 'observatory'", () => {
    const cmd = createObservatoryCommand({ getModeHistory: () => [] });
    expect(cmd.name).toBe("observatory");
  });

  it("command has alias 'obs'", () => {
    const cmd = createObservatoryCommand({ getModeHistory: () => [] });
    expect(cmd.aliases).toContain("obs");
  });

  it("isEnabled returns true", () => {
    const cmd = createObservatoryCommand({ getModeHistory: () => [] });
    expect(cmd.isEnabled()).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// AC7: runObservatory returns multi-line view (header, current mode, timeline)
// ---------------------------------------------------------------------------

describe("AC7: runObservatory — multi-line view structure", () => {
  it("returns a non-empty header as the first line", () => {
    const output = runObservatory([]);
    const lines = output.split("\n");
    expect(lines[0]!.length).toBeGreaterThan(0);
  });

  it("empty history → 'no activity yet' line, no crash", () => {
    const output = runObservatory([]);
    expect(output).toContain("no activity yet");
  });

  it("non-empty history → output contains the current mode label (last entry)", () => {
    const history: CognitiveMode[] = ["observe", "orient", "act"];
    const output = runObservatory(history);
    expect(output).toContain("act");
  });

  it("single-element history shows that mode's label", () => {
    const output = runObservatory(["rollback"]);
    expect(output).toContain("rollback");
  });

  it("non-empty history → output is multi-line", () => {
    const history: CognitiveMode[] = ["observe", "orient"];
    const output = runObservatory(history);
    expect(output).toContain("\n");
  });

  it("timeline section appears for non-empty history", () => {
    const history: CognitiveMode[] = ["observe", "orient", "act"];
    const output = runObservatory(history);
    // Timeline contains at least one glyph
    expect(output.split("\n").length).toBeGreaterThanOrEqual(3);
  });

  it("shows at most 20 entries in the timeline for a 25-entry history", () => {
    const history: CognitiveMode[] = (Array(25).fill("orient") as CognitiveMode[]);
    const output = runObservatory(history);
    // The timeline line starts with "timeline:"; count glyphs on that line only
    const timelineLine = output.split("\n").find((l) => l.startsWith("timeline:")) ?? "";
    const fireball = "🔥";
    const count = [...timelineLine].filter((ch) => ch === fireball).length;
    expect(count).toBeLessThanOrEqual(20);
    expect(count).toBeGreaterThan(0);
  });
});

// ---------------------------------------------------------------------------
// AC8: output contains current mode label and is deterministic
// ---------------------------------------------------------------------------

describe("AC8: runObservatory — determinism and label presence", () => {
  it("same history always produces identical output", () => {
    const history: CognitiveMode[] = ["observe", "orient", "act", "verify"];
    expect(runObservatory(history)).toBe(runObservatory(history));
  });

  it("output contains the current mode label for 'ask'", () => {
    const output = runObservatory(["observe", "ask"]);
    expect(output).toContain("ask");
  });

  it("output contains the current mode label for 'consolidate'", () => {
    const output = runObservatory(["observe", "consolidate"]);
    expect(output).toContain("consolidate");
  });

  it("output contains no random or timestamp elements (deterministic)", () => {
    const history: CognitiveMode[] = ["observe", "report"];
    const a = runObservatory(history);
    const b = runObservatory(history);
    // Byte-identical — no Date.now(), no Math.random()
    expect(a).toBe(b);
  });

  it("execute() returns a message result with the mode label in it", async () => {
    const history: CognitiveMode[] = ["observe", "verify"];
    const cmd = createObservatoryCommand({ getModeHistory: () => history });
    const result = await cmd.execute("", { sessionId: "s", mode: "auto", cwd: "/" });
    expect(result).toBeDefined();
    const msg = (result as { type: string; message: string }).message;
    expect(msg).toContain("verify");
  });
});
