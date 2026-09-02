// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// /bridge-kick — acceptance test suite
// Spec: specs/commands/bridge-kick.md

import { describe, it, expect } from "bun:test";
import { createBridgeKickCommand } from "./bridge-kick.ts";
import type { CommandContext } from "../types/command-types.ts";

const mockContext: CommandContext = {
  sessionId: "test-session",
  mode: "default",
  cwd: "/test",
};

function makeMockBridge() {
  const called: string[] = [];
  return {
    called,
    bridge: {
      close: () => { called.push("close"); },
      poll: () => { called.push("poll"); },
      register: () => { called.push("register"); },
      reconnectSession: () => { called.push("reconnect-session"); },
      heartbeat: () => { called.push("heartbeat"); },
      reconnect: () => { called.push("reconnect"); },
      getStatus: () => "connected; last event: heartbeat; session: abc123",
    },
  };
}

describe("/bridge-kick", () => {
  describe("AC1: command absent for non-ant users", () => {
    it("isEnabled() returns false when USER_TYPE is not 'ant'", () => {
      const { bridge } = makeMockBridge();
      const cmd = createBridgeKickCommand({ getUserType: () => "external", bridge });
      expect(cmd.isEnabled()).toBe(false);
    });

    it("isEnabled() returns true for ant users", () => {
      const { bridge } = makeMockBridge();
      const cmd = createBridgeKickCommand({ getUserType: () => "ant", bridge });
      expect(cmd.isEnabled()).toBe(true);
    });
  });

  describe("AC2: each valid subcommand calls the corresponding bridge operation", () => {
    async function runSubcommand(sub: string) {
      const { called, bridge } = makeMockBridge();
      const cmd = createBridgeKickCommand({ getUserType: () => "ant", bridge });
      await cmd.execute(sub, mockContext);
      return called;
    }

    it("close calls bridge.close()", async () => {
      const called = await runSubcommand("close");
      expect(called).toContain("close");
    });

    it("poll calls bridge.poll()", async () => {
      const called = await runSubcommand("poll");
      expect(called).toContain("poll");
    });

    it("register calls bridge.register()", async () => {
      const called = await runSubcommand("register");
      expect(called).toContain("register");
    });

    it("reconnect-session calls bridge.reconnectSession()", async () => {
      const called = await runSubcommand("reconnect-session");
      expect(called).toContain("reconnect-session");
    });

    it("heartbeat calls bridge.heartbeat()", async () => {
      const called = await runSubcommand("heartbeat");
      expect(called).toContain("heartbeat");
    });

    it("reconnect calls bridge.reconnect()", async () => {
      const called = await runSubcommand("reconnect");
      expect(called).toContain("reconnect");
    });
  });

  describe("AC3: unrecognized subcommand returns a usage error", () => {
    it("returns a usage error for unknown subcommand", async () => {
      const { bridge } = makeMockBridge();
      const cmd = createBridgeKickCommand({ getUserType: () => "ant", bridge });
      const result = await cmd.execute("unknown-action", mockContext);
      const message = (result as { message: string }).message;
      expect(message).toContain("Unknown subcommand");
      expect(message).toContain("close");
      expect(message).toContain("status");
    });

    it("returns usage error for empty args", async () => {
      const { bridge } = makeMockBridge();
      const cmd = createBridgeKickCommand({ getUserType: () => "ant", bridge });
      const result = await cmd.execute("", mockContext);
      const message = (result as { message: string }).message;
      expect(message).toContain("Unknown subcommand");
    });
  });

  describe("AC4: status returns current bridge connection state", () => {
    it("returns bridge.getStatus() output for 'status' subcommand", async () => {
      const { bridge } = makeMockBridge();
      const cmd = createBridgeKickCommand({ getUserType: () => "ant", bridge });
      const result = await cmd.execute("status", mockContext);
      expect((result as { message: string }).message).toContain("connected");
    });
  });

  describe("AC5: command works in non-interactive sessions", () => {
    it("execute completes in a headless context", async () => {
      const { bridge } = makeMockBridge();
      const cmd = createBridgeKickCommand({ getUserType: () => "ant", bridge });
      const headlessCtx: CommandContext = {
        sessionId: "headless",
        mode: "default",
        cwd: "/",
      };
      const result = await cmd.execute("status", headlessCtx);
      expect(result).toBeDefined();
    });
  });
});
