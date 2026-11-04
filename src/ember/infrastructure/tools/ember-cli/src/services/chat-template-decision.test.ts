// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { describe, expect, it } from "bun:test";
import { existsSync, readFileSync } from "node:fs";

import { decideTemplate, templateFor, templatePath, type ToolProbeResult } from "./chat-template-decision.ts";

const pass: ToolProbeResult = { ok: true, stage: "pass", detail: "get_weather" };
const renderFail: ToolProbeResult = { ok: false, stage: "render", detail: "apply-template HTTP 500: jinja error" };
const noCall: ToolProbeResult = { ok: false, stage: "tool-call", detail: "no get_weather tool call" };

describe("template architecture match", () => {
  it("maps the architectures avir fixed, and nothing else", () => {
    expect(templateFor("qwen35", "Qwen3.8-27B")).toBe("qwen36");
    expect(templateFor("qwen35moe", "Qwen3.6-35B-A3B")).toBe("qwen36");
    expect(templateFor("qwen35", "Qwen3.5-27B")).toBe("qwen35");
    expect(templateFor("gemma4", "gemma-4-26b")).toBe("gemma4");
    expect(templateFor("qwen3", "Qwen3-4B")).toBeNull();
    expect(templateFor("llama", "x")).toBeNull();
    expect(templateFor(null, "x")).toBeNull();
  });

  it("ships the three avir templates with the repo header and their fixes intact", () => {
    for (const t of ["qwen35", "qwen36", "gemma4"] as const) {
      expect(existsSync(templatePath(t))).toBe(true);
      const text = readFileSync(templatePath(t), "utf-8");
      expect(text.split("\n").slice(0, 3)).toEqual(["{#- goal_id: EMBER-02 -#}", "{#- workstream_id: EMBER-02A -#}", "{#- next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember -#}"]);
    }
    expect(readFileSync(templatePath("qwen36"), "utf-8")).toContain("preserve_thinking");
    expect(readFileSync(templatePath("qwen36"), "utf-8")).toContain('is_error="true"');
  });
});

describe("template decision", () => {
  it("keeps the embedded template when no fixed template matches", () => {
    const d = decideTemplate({ template: null, arch: "qwen3" });
    expect(d.use).toBe(false);
    expect(d.reason).toContain("no avir fixed template for architecture qwen3");
  });

  it("keeps the embedded template when it passes the probe", () => {
    const d = decideTemplate({ template: "qwen36", arch: "qwen35", embeddedProbe: pass });
    expect(d.use).toBe(false);
    expect(d.reason).toContain("passed the tool-call probe");
  });

  it("adopts the fixed template only when the embedded one fails to render and the fixed one passes", () => {
    const d = decideTemplate({ template: "qwen36", arch: "qwen35", embeddedProbe: renderFail, fixedProbe: pass });
    expect(d).toMatchObject({ use: true, template: "qwen36" });
    expect(d.embeddedProbe).toEqual(renderFail);
    expect(d.fixedProbe).toEqual(pass);
  });

  it("does not adopt when the fixed template fails too", () => {
    const d = decideTemplate({ template: "gemma4", arch: "gemma4", embeddedProbe: renderFail, fixedProbe: renderFail });
    expect(d.use).toBe(false);
    expect(d.reason).toContain("also failed");
  });

  it("treats a rendered-but-no-tool-call result as inconclusive, not a template fault", () => {
    const d = decideTemplate({ template: "qwen36", arch: "qwen35", embeddedProbe: noCall, fixedProbe: pass });
    expect(d.use).toBe(false);
    expect(d.reason).toContain("INCONCLUSIVE");
  });

  it("never adopts on an unprobed embedded template", () => {
    expect(decideTemplate({ template: "qwen36", arch: "qwen35" }).use).toBe(false);
  });
});
