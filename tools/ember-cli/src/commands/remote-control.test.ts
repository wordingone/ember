// /remote-control — acceptance test suite
// Spec: specs/commands/remote-control.md

import { describe, it, expect } from "bun:test";
import { createRemoteControlCommand } from "./remote-control.ts";
import type { CommandContext } from "../types/command-types.ts";
import type { RemoteControlDeps } from "./remote-control.ts";

const mockContext: CommandContext = {
  sessionId: "test-session",
  mode: "default",
  cwd: "/test",
};

function makeDefaultDeps(overrides?: Partial<RemoteControlDeps>): RemoteControlDeps {
  const analyticsEvents: Array<{ event: string; action: string }> = [];
  let replBridgeEnabled = false;

  return {
    isBridgeModeEnabled: () => true,
    isBridgeEligible: () => true,
    isReplBridgeEnabled: () => replBridgeEnabled,
    isReplBridgeConnected: () => false,
    getSessionUrl: () => "https://ember.ai/session/abc",
    getConnectUrl: () => "https://ember.ai/connect",
    isSessionActive: () => false,
    setReplBridgeEnabled: (v) => { replBridgeEnabled = v; },
    setReplBridgeOutboundOnly: () => {},
    setShowRemoteCallout: () => {},
    setReplBridgeInitialName: () => {},
    runPrerequisiteChecks: async () => null, // passes by default
    shouldShowRemoteCallout: () => false,
    generateQrCode: (url) => `QR[${url}]`,
    emitAnalytics: (event, props) => analyticsEvents.push({ event, action: props.action }),
    renderBridgeDisconnectDialog: async (props) => {
      return props.onContinue();
    },
    ...overrides,
  };
}

describe("/remote-control", () => {
  describe("AC1: command absent when BRIDGE_MODE is disabled", () => {
    it("isEnabled() returns false when isBridgeModeEnabled is false", () => {
      const cmd = createRemoteControlCommand(
        makeDefaultDeps({ isBridgeModeEnabled: () => false })
      );
      expect(cmd.isEnabled()).toBe(false);
    });

    it("isEnabled() returns false when isBridgeEligible is false", () => {
      const cmd = createRemoteControlCommand(
        makeDefaultDeps({ isBridgeEligible: () => false })
      );
      expect(cmd.isEnabled()).toBe(false);
    });

    it("isEnabled() returns true when both flags are on", () => {
      const cmd = createRemoteControlCommand(makeDefaultDeps());
      expect(cmd.isEnabled()).toBe(true);
    });
  });

  describe("AC2: not connected + prerequisites pass → set replBridgeEnabled:true", () => {
    it("sets replBridgeEnabled to true", async () => {
      let enabled = false;
      const cmd = createRemoteControlCommand(makeDefaultDeps({
        isReplBridgeEnabled: () => false,
        isReplBridgeConnected: () => false,
        setReplBridgeEnabled: (v) => { enabled = v; },
      }));
      await cmd.execute("", mockContext);
      expect(enabled).toBe(true);
    });

    it("returns 'Remote Control connecting…'", async () => {
      const cmd = createRemoteControlCommand(makeDefaultDeps({
        isReplBridgeEnabled: () => false,
        isReplBridgeConnected: () => false,
      }));
      const result = await cmd.execute("", mockContext);
      expect((result as { message: string }).message).toContain("connecting");
    });

    it("emits action=connect analytics", async () => {
      const events: string[] = [];
      const cmd = createRemoteControlCommand(makeDefaultDeps({
        isReplBridgeEnabled: () => false,
        isReplBridgeConnected: () => false,
        emitAnalytics: (_e, p) => events.push(p.action),
      }));
      await cmd.execute("", mockContext);
      expect(events).toContain("connect");
    });
  });

  describe("AC3: bridge connected → show disconnect dialog", () => {
    it("renders disconnect dialog when bridge is enabled", async () => {
      let dialogRendered = false;
      const cmd = createRemoteControlCommand(makeDefaultDeps({
        isReplBridgeEnabled: () => true,
        renderBridgeDisconnectDialog: async (props) => {
          dialogRendered = true;
          return props.onContinue();
        },
      }));
      await cmd.execute("", mockContext);
      expect(dialogRendered).toBe(true);
    });
  });

  describe("AC4: Disconnect → set replBridgeEnabled:false + log disconnect", () => {
    it("sets replBridgeEnabled to false on disconnect", async () => {
      let enabled = true;
      const cmd = createRemoteControlCommand(makeDefaultDeps({
        isReplBridgeEnabled: () => enabled,
        setReplBridgeEnabled: (v) => { enabled = v; },
        renderBridgeDisconnectDialog: async (props) => props.onDisconnect(),
      }));
      await cmd.execute("", mockContext);
      expect(enabled).toBe(false);
    });

    it("emits action=disconnect analytics on disconnect", async () => {
      const events: string[] = [];
      const cmd = createRemoteControlCommand(makeDefaultDeps({
        isReplBridgeEnabled: () => true,
        emitAnalytics: (_e, p) => events.push(p.action),
        renderBridgeDisconnectDialog: async (props) => props.onDisconnect(),
      }));
      await cmd.execute("", mockContext);
      expect(events).toContain("disconnect");
    });
  });

  describe("AC5: Show QR renders QR code of display URL", () => {
    it("returns QR code text when Show QR is chosen", async () => {
      const cmd = createRemoteControlCommand(makeDefaultDeps({
        isReplBridgeEnabled: () => true,
        getConnectUrl: () => "https://ember.ai/connect/xyz",
        isSessionActive: () => false,
        generateQrCode: (url) => `QR[${url}]`,
        renderBridgeDisconnectDialog: async (props) => props.onShowQr(),
      }));
      const result = await cmd.execute("", mockContext);
      expect((result as { message: string }).message).toContain("QR[");
    });
  });

  describe("AC6: Continue dismisses dialog without changing state", () => {
    it("returns none result on Continue", async () => {
      const cmd = createRemoteControlCommand(makeDefaultDeps({
        isReplBridgeEnabled: () => true,
        renderBridgeDisconnectDialog: async (props) => props.onContinue(),
      }));
      const result = await cmd.execute("", mockContext);
      expect((result as { type: string }).type).toBe("none");
    });

    it("does not change replBridgeEnabled on Continue", async () => {
      let enabled = true;
      const cmd = createRemoteControlCommand(makeDefaultDeps({
        isReplBridgeEnabled: () => enabled,
        setReplBridgeEnabled: (v) => { enabled = v; },
        renderBridgeDisconnectDialog: async (props) => props.onContinue(),
      }));
      await cmd.execute("", mockContext);
      expect(enabled).toBe(true);
    });
  });

  describe("AC7: prerequisite failure → error, replBridgeEnabled stays false", () => {
    it("returns error message and does not set replBridgeEnabled", async () => {
      let enabled = false;
      const cmd = createRemoteControlCommand(makeDefaultDeps({
        isReplBridgeEnabled: () => false,
        isReplBridgeConnected: () => false,
        runPrerequisiteChecks: async () => "No internet connection.",
        setReplBridgeEnabled: (v) => { enabled = v; },
      }));
      const result = await cmd.execute("", mockContext);
      expect((result as { message: string }).message).toContain("No internet connection");
      expect(enabled).toBe(false);
    });

    it("emits action=preflight_failed on prerequisite failure", async () => {
      const events: string[] = [];
      const cmd = createRemoteControlCommand(makeDefaultDeps({
        isReplBridgeEnabled: () => false,
        runPrerequisiteChecks: async () => "Auth required.",
        emitAnalytics: (_e, p) => events.push(p.action),
      }));
      await cmd.execute("", mockContext);
      expect(events).toContain("preflight_failed");
    });
  });

  describe("command has aliases", () => {
    it("has 'rc' as an alias", () => {
      const cmd = createRemoteControlCommand(makeDefaultDeps());
      expect(cmd.aliases).toContain("rc");
    });
  });
});
