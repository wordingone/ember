// /ultrareview — acceptance test suite
// Spec: specs/commands/ultrareview.md

import { describe, it, expect } from "bun:test";
import {
  createUltrareviewCommand,
  defaultBughunterConfig,
  BUGHUNTER_DRY_RUN,
} from "./ultrareview.ts";
import type { CommandContext } from "../types/command-types.ts";
import type {
  UltrareviewDeps,
  UltrareviewBillingGate,
  UltrareviewLaunchResult,
} from "./ultrareview.ts";

const mockContext: CommandContext = {
  sessionId: "test-session",
  mode: "default",
  cwd: "/repo",
};

function makeDefaultDeps(overrides?: Partial<UltrareviewDeps>): UltrareviewDeps {
  let overageConfirmed = false;
  return {
    isBughunterEnabled: () => true,
    fetchBillingGate: async (): Promise<UltrareviewBillingGate> => ({ type: "proceed" }),
    hasConfirmedOverage: () => overageConfirmed,
    confirmOverage: () => { overageConfirmed = true; },
    renderOverageDialog: async () => true,
    checkRemoteEligibility: async () => ({ type: "ok" }),
    getCurrentRepository: async () => "owner/repo",
    getDefaultBranch: async () => "main",
    computeMergeBase: async () => "abc123sha",
    getDiffBetween: async () => "diff --git a/foo.ts b/foo.ts\n+changed",
    bundleWorkingTree: async () => ({ tooLarge: false, bundlePath: "/tmp/bundle.tar" }),
    onEscape: (_cb) => () => {},
    launchRemoteSession: async () => ({ sessionUrl: "https://ccr/session/xyz" }),
    setShouldQuery: (_v) => {},
    emitAnalytics: (_e, _p) => {},
    getBughunterConfig: () => defaultBughunterConfig(),
    ...overrides,
  };
}

describe("/ultrareview", () => {
  // -------------------------------------------------------------------------
  // AC1: feature gate
  // -------------------------------------------------------------------------
  describe("AC1: command absent when tengu_review_bughunter_config is not set", () => {
    it("isEnabled() returns false when gate is off", () => {
      const cmd = createUltrareviewCommand(
        makeDefaultDeps({ isBughunterEnabled: () => false })
      );
      expect(cmd.isEnabled()).toBe(false);
    });

    it("isEnabled() returns true when gate is on", () => {
      const cmd = createUltrareviewCommand(makeDefaultDeps());
      expect(cmd.isEnabled()).toBe(true);
    });
  });

  // -------------------------------------------------------------------------
  // AC2: Team/Enterprise bypass billing gate
  // -------------------------------------------------------------------------
  describe("AC2: Team/Enterprise accounts bypass billing gate and proceed", () => {
    it("does not call renderOverageDialog for type:proceed", async () => {
      let dialogCalled = false;
      const cmd = createUltrareviewCommand(
        makeDefaultDeps({
          fetchBillingGate: async () => ({ type: "proceed" }),
          renderOverageDialog: async () => { dialogCalled = true; return true; },
        })
      );
      await cmd.execute("", mockContext);
      expect(dialogCalled).toBe(false);
    });

    it("launches successfully for team account", async () => {
      let launched = false;
      const cmd = createUltrareviewCommand(
        makeDefaultDeps({
          fetchBillingGate: async () => ({ type: "proceed" }),
          launchRemoteSession: async () => { launched = true; return { sessionUrl: "https://x" }; },
        })
      );
      await cmd.execute("", mockContext);
      expect(launched).toBe(true);
    });
  });

  // -------------------------------------------------------------------------
  // AC3: consumer account with free reviews remaining
  // -------------------------------------------------------------------------
  describe("AC3: consumer with reviews_remaining > 0 shows 'free review N of M'", () => {
    it("includes free review count in success message", async () => {
      const cmd = createUltrareviewCommand(
        makeDefaultDeps({
          fetchBillingGate: async () => ({
            type: "proceed",
            reviewsRemaining: 4,
            totalReviews: 5,
          }),
        })
      );
      const result = await cmd.execute("", mockContext);
      expect((result as { message: string }).message).toContain("free review");
      expect((result as { message: string }).message).toContain("of 5");
    });
  });

  // -------------------------------------------------------------------------
  // AC4: consumer with exhausted reviews + balance < $10 sees low-balance gate
  // -------------------------------------------------------------------------
  describe("AC4: low-balance gate blocks launch", () => {
    it("returns an error message and does not launch", async () => {
      let launched = false;
      const cmd = createUltrareviewCommand(
        makeDefaultDeps({
          fetchBillingGate: async () => ({ type: "low-balance", balance: 5.25 }),
          launchRemoteSession: async () => { launched = true; return { sessionUrl: "x" }; },
        })
      );
      const result = await cmd.execute("", mockContext);
      expect(launched).toBe(false);
      expect((result as { message: string }).message).toContain("5.25");
    });

    it("not-enabled gate returns settings URL", async () => {
      let launched = false;
      const cmd = createUltrareviewCommand(
        makeDefaultDeps({
          fetchBillingGate: async () => ({
            type: "not-enabled",
            settingsUrl: "https://ember.ai/settings/billing",
          }),
          launchRemoteSession: async () => { launched = true; return null; },
        })
      );
      const result = await cmd.execute("", mockContext);
      expect(launched).toBe(false);
      expect((result as { message: string }).message).toContain("ember.ai/settings/billing");
    });
  });

  // -------------------------------------------------------------------------
  // AC5: PR mode env vars
  // -------------------------------------------------------------------------
  describe("AC5: PR mode sets correct ref and env vars", () => {
    it("sends refs/pull/<N>/head as the pr ref", async () => {
      type LaunchOpts = { env: Record<string, string>; prRef?: string; useBundle?: boolean; bundlePath?: string };
      const cap: { opts: LaunchOpts | null } = { opts: null };
      const cmd = createUltrareviewCommand(
        makeDefaultDeps({
          launchRemoteSession: async (opts) => {
            cap.opts = opts;
            return { sessionUrl: "https://x" };
          },
        })
      );
      await cmd.execute("42", mockContext);
      expect(cap.opts?.prRef).toBe("refs/pull/42/head");
    });

    it("sets BUGHUNTER_PR_NUMBER and BUGHUNTER_REPOSITORY in env", async () => {
      let capturedEnv: Record<string, string> = {};
      const cmd = createUltrareviewCommand(
        makeDefaultDeps({
          getCurrentRepository: async () => "myorg/myrepo",
          launchRemoteSession: async (opts) => {
            capturedEnv = opts.env;
            return { sessionUrl: "https://x" };
          },
        })
      );
      await cmd.execute("7", mockContext);
      expect(capturedEnv["BUGHUNTER_PR_NUMBER"]).toBe("7");
      expect(capturedEnv["BUGHUNTER_REPOSITORY"]).toBe("myorg/myrepo");
    });

    it("returns an error when not a GitHub repo", async () => {
      let launched = false;
      const cmd = createUltrareviewCommand(
        makeDefaultDeps({
          getCurrentRepository: async () => null,
          launchRemoteSession: async () => { launched = true; return null; },
        })
      );
      const result = await cmd.execute("5", mockContext);
      expect(launched).toBe(false);
      expect((result as { message: string }).message).toContain("GitHub");
    });

    it("always sets BUGHUNTER_DRY_RUN to '1'", async () => {
      let capturedEnv: Record<string, string> = {};
      const cmd = createUltrareviewCommand(
        makeDefaultDeps({
          launchRemoteSession: async (opts) => {
            capturedEnv = opts.env;
            return { sessionUrl: "https://x" };
          },
        })
      );
      await cmd.execute("99", mockContext);
      expect(capturedEnv["BUGHUNTER_DRY_RUN"]).toBe(BUGHUNTER_DRY_RUN);
    });
  });

  // -------------------------------------------------------------------------
  // AC6: branch mode — empty diff aborts
  // -------------------------------------------------------------------------
  describe("AC6: branch mode aborts when diff between HEAD and merge-base is empty", () => {
    it("returns error and does not launch when diff is empty", async () => {
      let launched = false;
      const cmd = createUltrareviewCommand(
        makeDefaultDeps({
          getDiffBetween: async () => "",
          launchRemoteSession: async () => { launched = true; return { sessionUrl: "x" }; },
        })
      );
      const result = await cmd.execute("", mockContext);
      expect(launched).toBe(false);
      expect((result as { message: string }).message).toContain("No changes");
    });

    it("returns error when no merge base is found", async () => {
      let launched = false;
      const cmd = createUltrareviewCommand(
        makeDefaultDeps({
          computeMergeBase: async () => null,
          launchRemoteSession: async () => { launched = true; return { sessionUrl: "x" }; },
        })
      );
      const result = await cmd.execute("", mockContext);
      expect(launched).toBe(false);
      expect((result as { message: string }).message).toContain("merge base");
    });
  });

  // -------------------------------------------------------------------------
  // AC7: bundle too large aborts
  // -------------------------------------------------------------------------
  describe("AC7: branch mode aborts when bundle is too large", () => {
    it("returns bundle-size error and does not launch", async () => {
      let launched = false;
      const cmd = createUltrareviewCommand(
        makeDefaultDeps({
          bundleWorkingTree: async () => ({ tooLarge: true }),
          launchRemoteSession: async () => { launched = true; return { sessionUrl: "x" }; },
        })
      );
      const result = await cmd.execute("", mockContext);
      expect(launched).toBe(false);
      expect((result as { message: string }).message).toContain("too large");
    });
  });

  // -------------------------------------------------------------------------
  // AC8: shouldQuery: true after successful launch
  // -------------------------------------------------------------------------
  describe("AC8: model is triggered after successful launch", () => {
    it("calls setShouldQuery(true) on success", async () => {
      let queriedValue: boolean | undefined;
      const cmd = createUltrareviewCommand(
        makeDefaultDeps({ setShouldQuery: (v) => { queriedValue = v; } })
      );
      await cmd.execute("", mockContext);
      expect(queriedValue).toBe(true);
    });

    it("does NOT call setShouldQuery when launch returns null", async () => {
      let queriedValue: boolean | undefined;
      const cmd = createUltrareviewCommand(
        makeDefaultDeps({
          launchRemoteSession: async () => null,
          setShouldQuery: (v) => { queriedValue = v; },
        })
      );
      await cmd.execute("", mockContext);
      expect(queriedValue).toBeUndefined();
    });
  });

  // -------------------------------------------------------------------------
  // AC9: escape during launch window cancels cleanly
  // -------------------------------------------------------------------------
  describe("AC9: escape during ~5-second launch window cancels cleanly", () => {
    it("returns none result and does not trigger model when escaped", async () => {
      let queriedValue: boolean | undefined;
      let escapeCallback: (() => void) | null = null;

      const cmd = createUltrareviewCommand(
        makeDefaultDeps({
          onEscape: (cb) => {
            escapeCallback = cb;
            return () => {};
          },
          launchRemoteSession: async () => {
            // Fire escape during the "launch window"
            escapeCallback?.();
            return { sessionUrl: "https://ccr/session/abc" };
          },
          setShouldQuery: (v) => { queriedValue = v; },
        })
      );

      const result = await cmd.execute("", mockContext);
      expect(queriedValue).toBeUndefined();
      expect((result as { type: string }).type).toBe("none");
    });
  });

  // -------------------------------------------------------------------------
  // AC10: confirmOverage persists across invocations
  // -------------------------------------------------------------------------
  describe("AC10: confirmOverage() flag prevents dialog on subsequent invocations", () => {
    it("calls renderOverageDialog on first needs-confirm invocation", async () => {
      let dialogCalls = 0;
      const cmd = createUltrareviewCommand(
        makeDefaultDeps({
          fetchBillingGate: async () => ({ type: "needs-confirm" }),
          renderOverageDialog: async () => { dialogCalls++; return true; },
        })
      );
      await cmd.execute("", mockContext);
      expect(dialogCalls).toBe(1);
    });

    it("does not show dialog again once overage is confirmed", async () => {
      let dialogCalls = 0;
      let confirmed = false;
      const cmd = createUltrareviewCommand(
        makeDefaultDeps({
          fetchBillingGate: async () => ({ type: "needs-confirm" }),
          hasConfirmedOverage: () => confirmed,
          confirmOverage: () => { confirmed = true; },
          renderOverageDialog: async () => { dialogCalls++; return true; },
        })
      );
      // First invocation — shows dialog
      await cmd.execute("", mockContext);
      expect(dialogCalls).toBe(1);
      // Second invocation — confirmed, no dialog
      await cmd.execute("", mockContext);
      expect(dialogCalls).toBe(1);
    });

    it("returns none when user cancels the overage dialog", async () => {
      let launched = false;
      const cmd = createUltrareviewCommand(
        makeDefaultDeps({
          fetchBillingGate: async () => ({ type: "needs-confirm" }),
          renderOverageDialog: async () => false,
          launchRemoteSession: async () => { launched = true; return { sessionUrl: "x" }; },
        })
      );
      const result = await cmd.execute("", mockContext);
      expect(launched).toBe(false);
      expect((result as { type: string }).type).toBe("none");
    });
  });

  // -------------------------------------------------------------------------
  // Branch mode: BUGHUNTER_BASE_BRANCH is set to merge-base SHA
  // -------------------------------------------------------------------------
  describe("Branch mode env", () => {
    it("sets BUGHUNTER_BASE_BRANCH to merge-base SHA", async () => {
      let capturedEnv: Record<string, string> = {};
      const cmd = createUltrareviewCommand(
        makeDefaultDeps({
          computeMergeBase: async () => "deadbeef1234",
          launchRemoteSession: async (opts) => {
            capturedEnv = opts.env;
            return { sessionUrl: "https://x" };
          },
        })
      );
      await cmd.execute("", mockContext);
      expect(capturedEnv["BUGHUNTER_BASE_BRANCH"]).toBe("deadbeef1234");
    });

    it("uses bundle in branch mode", async () => {
      type LaunchOpts = { env: Record<string, string>; prRef?: string; useBundle?: boolean; bundlePath?: string };
      const cap: { opts: LaunchOpts | null } = { opts: null };
      const cmd = createUltrareviewCommand(
        makeDefaultDeps({
          bundleWorkingTree: async () => ({ tooLarge: false, bundlePath: "/tmp/b.tar" }),
          launchRemoteSession: async (opts) => {
            cap.opts = opts;
            return { sessionUrl: "https://x" };
          },
        })
      );
      await cmd.execute("", mockContext);
      expect(cap.opts?.useBundle).toBe(true);
      expect(cap.opts?.bundlePath).toBe("/tmp/b.tar");
    });
  });
});
