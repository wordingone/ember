// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// /advisor — acceptance test suite
// Spec: specs/commands/advisor.md

import { describe, it, expect } from "bun:test";
import { createAdvisorCommand } from "./advisor.ts";
import type { CommandContext } from "../types/command-types.ts";
import type { AdvisorDeps } from "./advisor.ts";

const mockContext: CommandContext = {
  sessionId: "test-session",
  mode: "default",
  cwd: "/test",
};

function makeDefaultDeps(overrides?: Partial<AdvisorDeps>): AdvisorDeps {
  let advisorModel: string | null = null;

  return {
    canUserConfigureAdvisor: () => true,
    getAdvisorModel: () => advisorModel,
    setAdvisorModel: async (m) => { advisorModel = m; },
    clearAdvisorModel: async () => { advisorModel = null; },
    getBaseModel: () => "qwen-3.6",
    parseModelAlias: (input) => {
      // Simple pass-through for tests; map known aliases
      if (input === "opus") return "qwen-3.6";
      if (input === "sonnet") return "qwen-3.6-fast";
      if (input === "unknown-xyz") return null;
      return input;
    },
    isValidModel: (m) => ["qwen-3.6", "qwen-3.6-fast", "qwen-3.6-haiku"].includes(m),
    isValidAdvisorModel: (m) => ["qwen-3.6", "qwen-3.6-fast"].includes(m),
    baseModelSupportsAdvisors: (base) => base !== "basic-model",
    ...overrides,
  };
}

describe("/advisor", () => {
  describe("AC1: /advisor with no args and no advisor configured prints no-advisor message", () => {
    it("says no advisor is set when none is configured", async () => {
      const cmd = createAdvisorCommand(makeDefaultDeps());
      const result = await cmd.execute("", mockContext);
      expect((result as { message: string }).message).toContain("No advisor model configured");
    });
  });

  describe("AC2: incompatible base model appends an inactive warning", () => {
    it("appends inactive warning when base model doesn't support advisors", async () => {
      const deps = makeDefaultDeps({
        getAdvisorModel: () => "qwen-3.6",
        getBaseModel: () => "basic-model",
        baseModelSupportsAdvisors: () => false,
      });
      const cmd = createAdvisorCommand(deps);
      const result = await cmd.execute("", mockContext);
      const msg = (result as { message: string }).message;
      expect(msg).toContain("qwen-3.6");
      expect(msg).toContain("inactive");
    });

    it("does not append warning when base model supports advisors", async () => {
      const deps = makeDefaultDeps({
        getAdvisorModel: () => "qwen-3.6",
        getBaseModel: () => "qwen-3.6",
        baseModelSupportsAdvisors: () => true,
      });
      const cmd = createAdvisorCommand(deps);
      const result = await cmd.execute("", mockContext);
      const msg = (result as { message: string }).message;
      expect(msg).not.toContain("inactive");
    });
  });

  describe("AC3: /advisor <valid-advisor-model> persists the setting", () => {
    it("sets the advisor model and returns confirmation", async () => {
      let set = "";
      const deps = makeDefaultDeps({
        setAdvisorModel: async (m) => { set = m; },
      });
      const cmd = createAdvisorCommand(deps);
      const result = await cmd.execute("qwen-3.6", mockContext);
      expect(set).toBe("qwen-3.6");
      expect((result as { message: string }).message).toContain("qwen-3.6");
    });

    it("resolves alias to canonical name before persisting", async () => {
      let set = "";
      const deps = makeDefaultDeps({
        setAdvisorModel: async (m) => { set = m; },
      });
      const cmd = createAdvisorCommand(deps);
      await cmd.execute("opus", mockContext); // alias
      expect(set).toBe("qwen-3.6");
    });
  });

  describe("AC4: /advisor <unknown-model> returns error and leaves existing setting unchanged", () => {
    it("returns error for unknown model", async () => {
      let set = "";
      const deps = makeDefaultDeps({
        setAdvisorModel: async (m) => { set = m; },
      });
      const cmd = createAdvisorCommand(deps);
      const result = await cmd.execute("unknown-xyz", mockContext);
      expect((result as { message: string }).message).toContain("Unknown model");
      expect(set).toBe(""); // not set
    });

    it("returns error for non-advisor model", async () => {
      let set = "";
      const deps = makeDefaultDeps({
        setAdvisorModel: async (m) => { set = m; },
        isValidAdvisorModel: () => false,
        isValidModel: () => true,
      });
      const cmd = createAdvisorCommand(deps);
      const result = await cmd.execute("qwen-3.6-haiku", mockContext);
      const msg = (result as { message: string }).message;
      expect(msg).toContain("not a valid advisor model");
      expect(set).toBe(""); // not set
    });
  });

  describe("AC5: /advisor off clears advisor and confirms", () => {
    it("clears the advisor model on 'off'", async () => {
      let cleared = false;
      const deps = makeDefaultDeps({
        clearAdvisorModel: async () => { cleared = true; },
      });
      const cmd = createAdvisorCommand(deps);
      await cmd.execute("off", mockContext);
      expect(cleared).toBe(true);
    });

    it("clears the advisor model on 'unset'", async () => {
      let cleared = false;
      const deps = makeDefaultDeps({
        clearAdvisorModel: async () => { cleared = true; },
      });
      const cmd = createAdvisorCommand(deps);
      await cmd.execute("unset", mockContext);
      expect(cleared).toBe(true);
    });

    it("confirms the clear action", async () => {
      const cmd = createAdvisorCommand(makeDefaultDeps());
      const result = await cmd.execute("off", mockContext);
      expect((result as { message: string }).message).toContain("cleared");
    });
  });

  describe("AC6: command absent when eligibility gate is not met", () => {
    it("isEnabled() returns false when canUserConfigureAdvisor is false", () => {
      const cmd = createAdvisorCommand(
        makeDefaultDeps({ canUserConfigureAdvisor: () => false })
      );
      expect(cmd.isEnabled()).toBe(false);
    });
  });
});
