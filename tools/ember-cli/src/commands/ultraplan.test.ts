// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// /ultraplan — acceptance test suite
// Spec: specs/commands/ultraplan.md

import { describe, it, expect } from "bun:test";
import { createUltraplanCommand, stopUltraplan, ULTRAPLAN_DEFAULT_MODEL } from "./ultraplan.ts";
import type { CommandContext } from "../types/command-types.ts";
import type { UltraplanDeps, UltraplanLaunchResult } from "./ultraplan.ts";

const mockContext: CommandContext = {
  sessionId: "test-session",
  mode: "default",
  cwd: "/test",
};

function makeDefaultDeps(overrides?: Partial<UltraplanDeps>): UltraplanDeps {
  let sessionUrl: string | null = null;
  let launchPending: { blurb: string } | null = null;
  let pendingChoice: unknown = null;
  let launching = false;
  const analytics: Array<{ event: string }> = [];
  const notifications: string[] = [];

  return {
    isUltraplanEligible: () => true,
    getUltraplanModel: () => null, // use default
    getUltraplanSessionUrl: () => sessionUrl,
    setUltraplanSessionUrl: (url) => { sessionUrl = url; },
    setUltraplanLaunching: (v) => { launching = v; },
    setUltraplanLaunchPending: (p) => { launchPending = p; },
    setUltraplanPendingChoice: (p) => { pendingChoice = p; },
    checkRemoteSessionEligibility: async () => true,
    launchRemoteSession: async (opts) => ({
      sessionUrl: "https://ccr.ember.ai/session/abc123",
      executionTarget: "remote",
    }),
    archiveSession: async () => {},
    killRemoteTask: async () => {},
    notifyUser: (msg) => notifications.push(msg),
    emitAnalytics: (event) => analytics.push({ event }),
    ...overrides,
  };
}

describe("/ultraplan", () => {
  describe("AC1: /ultraplan with no args returns usage message", () => {
    it("returns usage message for empty args", async () => {
      const cmd = createUltraplanCommand(makeDefaultDeps());
      const result = await cmd.execute("", mockContext);
      expect((result as { message: string }).message).toContain("Usage");
    });

    it("does not call launchRemoteSession for empty args", async () => {
      let launched = false;
      const cmd = createUltraplanCommand(makeDefaultDeps({
        launchRemoteSession: async () => { launched = true; return null; },
      }));
      await cmd.execute("", mockContext);
      expect(launched).toBe(false);
    });
  });

  describe("AC2: /ultraplan <text> sets ultraplanLaunchPending in app state", () => {
    it("sets ultraplanLaunchPending with the blurb at some point during execution", async () => {
      // Track whether it was EVER set to a non-null value (it may be cleared later)
      let wasEverSet = false;
      const cmd = createUltraplanCommand(makeDefaultDeps({
        setUltraplanLaunchPending: (p) => { if (p !== null) wasEverSet = true; },
      }));
      await cmd.execute("Build a chat app", mockContext);
      expect(wasEverSet).toBe(true);
    });
  });

  describe("AC3: non-eligible user cannot trigger launch", () => {
    it("returns eligibility error and does not launch", async () => {
      let launched = false;
      const cmd = createUltraplanCommand(makeDefaultDeps({
        checkRemoteSessionEligibility: async () => false,
        launchRemoteSession: async () => { launched = true; return null; },
      }));
      const result = await cmd.execute("Build something", mockContext);
      expect(launched).toBe(false);
      expect((result as { message: string }).message).toContain("not eligible");
    });
  });

  describe("AC4: model from feature-flag config; fallback to local model", () => {
    it("uses configured model when getUltraplanModel returns a value", async () => {
      let usedModel = "";
      const cmd = createUltraplanCommand(makeDefaultDeps({
        getUltraplanModel: () => "qwen3.6-fast",
        launchRemoteSession: async (opts) => {
          usedModel = opts.model;
          return { sessionUrl: "https://x", executionTarget: "remote" };
        },
      }));
      await cmd.execute("Build", mockContext);
      expect(usedModel).toBe("qwen3.6-fast");
    });

    it("falls back to ULTRAPLAN_DEFAULT_MODEL when config returns null", async () => {
      let usedModel = "";
      const cmd = createUltraplanCommand(makeDefaultDeps({
        getUltraplanModel: () => null,
        launchRemoteSession: async (opts) => {
          usedModel = opts.model;
          return { sessionUrl: "https://x", executionTarget: "remote" };
        },
      }));
      await cmd.execute("Build", mockContext);
      expect(usedModel).toBe(ULTRAPLAN_DEFAULT_MODEL);
    });

    it("ULTRAPLAN_DEFAULT_MODEL is labeled REFERENCE_ONLY (Fix #51 fiction purge), never a bare borrowed model-name literal", () => {
      // Prior to the #51 fiction-purge repair this was the bare literal
      // 'qwen3-5' -- an unverified claim about which model actually serves
      // ultraplan sessions. It must now go through the same
      // `referenceSeatModelName` labeling every other reference-only
      // identity in the codebase uses, so it can never be read as a
      // verified served identity.
      expect(ULTRAPLAN_DEFAULT_MODEL.startsWith("REFERENCE_ONLY: ")).toBe(true);
      expect(ULTRAPLAN_DEFAULT_MODEL).not.toBe("qwen3-5");
    });
  });

  describe("AC5: executionTarget='remote' → clear sessionUrl, notify user", () => {
    it("sets sessionUrl to null after remote execution starts", async () => {
      let sessionUrl: string | null = "initial";
      const cmd = createUltraplanCommand(makeDefaultDeps({
        setUltraplanSessionUrl: (url) => { sessionUrl = url; },
        launchRemoteSession: async () => ({
          sessionUrl: "https://ccr/session/abc",
          executionTarget: "remote",
        }),
      }));
      await cmd.execute("Plan this", mockContext);
      expect(sessionUrl).toBeNull();
    });

    it("notifies the user that coding has begun", async () => {
      const notifications: string[] = [];
      const cmd = createUltraplanCommand(makeDefaultDeps({
        notifyUser: (msg) => notifications.push(msg),
        launchRemoteSession: async () => ({
          sessionUrl: "https://ccr/session/abc",
          executionTarget: "remote",
        }),
      }));
      await cmd.execute("Plan this", mockContext);
      expect(notifications.some((n) => n.includes("coding"))).toBe(true);
    });
  });

  describe("AC6: executionTarget='local' → set ultraplanPendingChoice", () => {
    it("sets ultraplanPendingChoice when execution is local", async () => {
      let pendingChoice: unknown = "not-set";
      const cmd = createUltraplanCommand(makeDefaultDeps({
        setUltraplanPendingChoice: (p) => { pendingChoice = p; },
        launchRemoteSession: async () => ({
          sessionUrl: "https://ccr/session/abc",
          executionTarget: "local",
          planContent: "Step 1: ...",
        }),
      }));
      await cmd.execute("Plan this", mockContext);
      expect(pendingChoice).not.toBe("not-set");
    });
  });

  describe("AC7: stopUltraplan kills remote task and clears sessionUrl", () => {
    it("kills the remote task and clears the session URL", async () => {
      let killed = "";
      let archived = "";
      let sessionUrl: string | null = "https://ccr/session/abc";

      const deps = makeDefaultDeps({
        getUltraplanSessionUrl: () => sessionUrl,
        setUltraplanSessionUrl: (url) => { sessionUrl = url; },
        archiveSession: async (url) => { archived = url; },
        killRemoteTask: async (url) => { killed = url; },
      });

      await stopUltraplan(deps);
      expect(killed).toBe("https://ccr/session/abc");
      expect(archived).toBe("https://ccr/session/abc");
      expect(sessionUrl).toBeNull();
    });

    it("does nothing when sessionUrl is null", async () => {
      let killed = false;
      const deps = makeDefaultDeps({
        getUltraplanSessionUrl: () => null,
        killRemoteTask: async () => { killed = true; },
      });
      await stopUltraplan(deps);
      expect(killed).toBe(false);
    });
  });

  describe("AC8: command hidden and non-callable for non-privileged users", () => {
    it("isEnabled() returns false for non-privileged users", () => {
      const cmd = createUltraplanCommand(
        makeDefaultDeps({ isUltraplanEligible: () => false })
      );
      expect(cmd.isEnabled()).toBe(false);
    });
  });
});
