// /stubs — acceptance test suite
// Spec: specs/commands/stubs.md

import { describe, it, expect } from "bun:test";
import {
  fork,
  workflows,
  forceSnip,
  proactive,
  subscribePr,
  torch,
  buddy,
  peers,
  issue,
  bughunter,
  summary,
  share,
  antTrace,
  autofixPr,
  backfillSessions,
  breakCache,
  ctxViz,
  debugToolCall,
  goodAssistant,
  mockLimits,
  oauthRefresh,
  perfIssue,
  resetLimitsCommand,
  resetLimits,
  resetLimitsNonInteractive,
  launchAssistantCommandHandler,
  launchAssistantInstallWizard,
  launchAssistantSessionChooser,
  AssistantComponent,
  remoteControlServer,
  agentsPlatform,
  ALL_DISABLED_STUBS,
} from "./stubs.ts";

// AC4: isEnabled() returns false at startup — checked here before any registry interaction

describe("stubs", () => {
  describe("AC1 + AC4: null-export slots are null and no-op stubs have isEnabled()===false", () => {
    it("fork is null (null-export pattern)", () => {
      expect(fork).toBeNull();
    });

    it("workflows is null (null-export pattern)", () => {
      expect(workflows).toBeNull();
    });

    it("all disabled-stub entries have isEnabled() returning false", () => {
      for (const stub of ALL_DISABLED_STUBS) {
        expect(stub.isEnabled()).toBe(false);
      }
    });
  });

  describe("AC3: stubs do not appear in /help (isHidden === true)", () => {
    it("all disabled-stub entries have isHidden: true", () => {
      for (const stub of ALL_DISABLED_STUBS) {
        expect(stub.isHidden).toBe(true);
      }
    });

    it("individual stubs are hidden", () => {
      const stubs = [
        forceSnip, proactive, subscribePr, torch, buddy, peers,
        issue, bughunter, summary, share, antTrace, autofixPr,
        backfillSessions, breakCache, ctxViz, debugToolCall, goodAssistant,
        mockLimits, oauthRefresh, perfIssue,
      ];
      for (const stub of stubs) {
        expect(stub.isHidden).toBe(true);
        expect(stub.isEnabled()).toBe(false);
      }
    });
  });

  describe("AC2: invoking a stub does not crash", () => {
    it("executing a stub returns a none result without crashing", async () => {
      const ctx = { sessionId: "test", mode: "default" as const, cwd: "/" };
      const result = await forceSnip.execute("", ctx);
      expect(result).toBeDefined();
      expect((result as { type: string }).type).toBe("none");
    });
  });

  describe("AC5: resetLimits and resetLimitsNonInteractive are disabled stubs", () => {
    it("resetLimitsCommand is a disabled stub", () => {
      expect(resetLimitsCommand.isEnabled()).toBe(false);
      expect(resetLimitsCommand.isHidden).toBe(true);
    });

    it("resetLimits named export is a disabled stub", () => {
      expect(resetLimits.isEnabled()).toBe(false);
      expect(resetLimits.isHidden).toBe(true);
    });

    it("resetLimitsNonInteractive named export is a disabled stub", () => {
      expect(resetLimitsNonInteractive.isEnabled()).toBe(false);
      expect(resetLimitsNonInteractive.isHidden).toBe(true);
    });
  });

  describe("component-stub: assistant functions are no-ops", () => {
    it("launchAssistantCommandHandler returns void", () => {
      expect(launchAssistantCommandHandler()).toBeUndefined();
    });

    it("launchAssistantInstallWizard returns void", () => {
      expect(launchAssistantInstallWizard()).toBeUndefined();
    });

    it("launchAssistantSessionChooser returns void", () => {
      expect(launchAssistantSessionChooser()).toBeUndefined();
    });

    it("AssistantComponent is null (stub component)", () => {
      expect(AssistantComponent).toBeNull();
    });
  });

  describe("component-stub: remoteControlServer functions are no-ops", () => {
    it("handleRemoteControlServer returns void", () => {
      expect(remoteControlServer.handleRemoteControlServer()).toBeUndefined();
    });

    it("startRemoteControlServer returns void", () => {
      expect(remoteControlServer.startRemoteControlServer()).toBeUndefined();
    });

    it("stopRemoteControlServer returns void", () => {
      expect(remoteControlServer.stopRemoteControlServer()).toBeUndefined();
    });
  });

  describe("component-stub: agentsPlatform functions are no-ops", () => {
    it("launchAgentsPlatform returns void", () => {
      expect(agentsPlatform.launchAgentsPlatform()).toBeUndefined();
    });

    it("handleAgentsPlatform returns void", () => {
      expect(agentsPlatform.handleAgentsPlatform()).toBeUndefined();
    });
  });
});
