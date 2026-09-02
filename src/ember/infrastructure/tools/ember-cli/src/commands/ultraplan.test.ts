// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// /ultraplan — acceptance test suite
// Spec: specs/commands/ultraplan.md

import { describe, it, expect } from "bun:test";
import {
  createUltraplanCommand,
  stopUltraplan,
  ULTRAPLAN_DEFAULT_MODEL_ROUTING_ID,
  ULTRAPLAN_DEFAULT_MODEL_LABEL,
} from "./ultraplan.ts";
import type { CommandContext } from "../types/command-types.ts";
import type { UltraplanDeps, UltraplanLaunchResult } from "./ultraplan.ts";
import type { SelectedModelContract } from "../entrypoints/model-seat.ts";

// PR948 round-8 (P1): the default test seat contract -- an explicit
// REFERENCE_ONLY seat decision. This is what authorizes
// ULTRAPLAN_DEFAULT_MODEL_ROUTING_ID as a fallback; without a resolved seat
// contract at all, execute() must fail closed and never call
// launchRemoteSession (see the "no model seat contract" describe block below).
const REFERENCE_ONLY_CONTRACT: SelectedModelContract = {
  seat: "REFERENCE_ONLY",
  modelName: ULTRAPLAN_DEFAULT_MODEL_LABEL,
  modelConfigSha256: null,
  structuredOutputs: false,
};

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
    // Default test seat: an explicit REFERENCE_ONLY decision, matching what
    // ultraplan's whole purpose is (launching a borrowed reference model
    // session) -- see REFERENCE_ONLY_CONTRACT above.
    getModelContract: () => REFERENCE_ONLY_CONTRACT,
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

    it("falls back to ULTRAPLAN_DEFAULT_MODEL_ROUTING_ID when config returns null", async () => {
      let usedModel = "";
      const cmd = createUltraplanCommand(makeDefaultDeps({
        getUltraplanModel: () => null,
        launchRemoteSession: async (opts) => {
          usedModel = opts.model;
          return { sessionUrl: "https://x", executionTarget: "remote" };
        },
      }));
      await cmd.execute("Build", mockContext);
      expect(usedModel).toBe(ULTRAPLAN_DEFAULT_MODEL_ROUTING_ID);
    });

    it("ULTRAPLAN_DEFAULT_MODEL_LABEL is labeled REFERENCE_ONLY (Fix #51 fiction purge), never a bare borrowed model-name literal", () => {
      // Prior to the #51 fiction-purge repair this was the bare literal
      // 'qwen3-5' -- an unverified claim about which model actually serves
      // ultraplan sessions. It must now go through the same
      // `referenceSeatModelName` labeling every other reference-only
      // identity in the codebase uses, so it can never be read as a
      // verified served identity.
      expect(ULTRAPLAN_DEFAULT_MODEL_LABEL.startsWith("REFERENCE_ONLY: ")).toBe(true);
      expect(ULTRAPLAN_DEFAULT_MODEL_LABEL).not.toBe("qwen3-5");
    });

    // Reviewer defect #1 (routing vs label): ULTRAPLAN_DEFAULT_MODEL used to
    // equal the display label "REFERENCE_ONLY: qwen3-5" and production passed
    // that label straight to launchRemoteSession({ model }) -- the provider
    // session API never receives a "REFERENCE_ONLY: " prefix in a real
    // routing id, so every default-model ultraplan launch was silently
    // handed a non-functional value. The routing id and the provenance label
    // must be two structured fields; only the routing id ever reaches
    // launchRemoteSession's `model` param.
    it("RED->GREEN: launchRemoteSession never receives a REFERENCE_ONLY-prefixed model id on default-model launch", async () => {
      let usedModel = "";
      const cmd = createUltraplanCommand(makeDefaultDeps({
        getUltraplanModel: () => null,
        launchRemoteSession: async (opts) => {
          usedModel = opts.model;
          return { sessionUrl: "https://x", executionTarget: "remote" };
        },
      }));
      await cmd.execute("Build", mockContext);
      expect(usedModel.startsWith("REFERENCE_ONLY: ")).toBe(false);
    });

    it("the REFERENCE_ONLY label field never reaches launchRemoteSession's model param", async () => {
      let usedModel = "";
      let usedLabel: unknown;
      const cmd = createUltraplanCommand(makeDefaultDeps({
        getUltraplanModel: () => null,
        launchRemoteSession: async (opts) => {
          usedModel = opts.model;
          usedLabel = (opts as Record<string, unknown>).modelLabel;
          return { sessionUrl: "https://x", executionTarget: "remote" };
        },
      }));
      await cmd.execute("Build", mockContext);
      expect(usedModel).toBe(ULTRAPLAN_DEFAULT_MODEL_ROUTING_ID);
      expect(usedModel).not.toBe(usedLabel);
      expect(usedLabel).toBe(ULTRAPLAN_DEFAULT_MODEL_LABEL);
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

  // PR948 round-8 (P1): reviewer reject on 28187c0 -- with ordinary unset
  // config, ULTRAPLAN_DEFAULT_MODEL_ROUTING_ID (a raw module constant) was
  // selected and sent straight to launchRemoteSession as `model`, with no
  // seat authorization at all. A REFERENCE_ONLY display label is not a
  // routing authorization. Fix: execute() now requires a seat-produced
  // SelectedModelContract (getModelContract) and fails closed -- no
  // launchRemoteSession call, no session-pending state left dangling --
  // when no contract is available, or when a contract IS available but is
  // not an explicit REFERENCE_ONLY decision (the only decision shape that
  // authorizes the hardcoded fallback routing id).
  describe("PR948 round-8 (P1): model routing requires a seat-produced contract, never a bare fallback constant", () => {
    it("fails closed and never calls launchRemoteSession when no model seat contract is available at all", async () => {
      let launched = false;
      const cmd = createUltraplanCommand(makeDefaultDeps({
        getModelContract: () => undefined,
        launchRemoteSession: async () => { launched = true; return null; },
      }));
      const result = await cmd.execute("Build something", mockContext);
      expect(launched).toBe(false);
      expect((result as { message: string }).message.length).toBeGreaterThan(0);
    });

    it("clears launchPending/launching state on the no-contract fail-closed path (never leaves the UI stuck mid-launch)", async () => {
      let launchPendingEverSet = false;
      let launchPendingFinal: unknown = "unset";
      let launchingFinal: unknown = "unset";
      const cmd = createUltraplanCommand(makeDefaultDeps({
        getModelContract: () => undefined,
        setUltraplanLaunchPending: (p) => {
          if (p !== null) launchPendingEverSet = true;
          launchPendingFinal = p;
        },
        setUltraplanLaunching: (v) => { launchingFinal = v; },
      }));
      await cmd.execute("Build something", mockContext);
      expect(launchPendingEverSet).toBe(true);
      expect(launchPendingFinal).toBeNull();
      expect(launchingFinal).not.toBe(true);
    });

    it("fails closed and never calls launchRemoteSession when the seat resolved to an OWNED identity (not an explicit REFERENCE_ONLY decision) and no config is set", async () => {
      let launched = false;
      const cmd = createUltraplanCommand(makeDefaultDeps({
        getUltraplanModel: () => null,
        getModelContract: () => ({
          seat: "OWNED_ADMITTED",
          modelName: "ember-owned:abc123",
          modelConfigSha256: "e".repeat(64),
          structuredOutputs: false,
        }),
        launchRemoteSession: async (opts) => { launched = true; return { sessionUrl: "https://x", executionTarget: "remote" }; },
      }));
      const result = await cmd.execute("Build something", mockContext);
      expect(launched).toBe(false);
      expect((result as { message: string }).message.length).toBeGreaterThan(0);
    });

    it("still uses ULTRAPLAN_DEFAULT_MODEL_ROUTING_ID when config is unset AND the seat contract is an explicit REFERENCE_ONLY decision", async () => {
      let usedModel = "";
      const cmd = createUltraplanCommand(makeDefaultDeps({
        getUltraplanModel: () => null,
        getModelContract: () => REFERENCE_ONLY_CONTRACT,
        launchRemoteSession: async (opts) => {
          usedModel = opts.model;
          return { sessionUrl: "https://x", executionTarget: "remote" };
        },
      }));
      await cmd.execute("Build", mockContext);
      expect(usedModel).toBe(ULTRAPLAN_DEFAULT_MODEL_ROUTING_ID);
    });

    it("configured model still wins even when the seat contract is REFERENCE_ONLY", async () => {
      let usedModel = "";
      const cmd = createUltraplanCommand(makeDefaultDeps({
        getUltraplanModel: () => "qwen3.6-fast",
        getModelContract: () => REFERENCE_ONLY_CONTRACT,
        launchRemoteSession: async (opts) => {
          usedModel = opts.model;
          return { sessionUrl: "https://x", executionTarget: "remote" };
        },
      }));
      await cmd.execute("Build", mockContext);
      expect(usedModel).toBe("qwen3.6-fast");
    });
  });
});
