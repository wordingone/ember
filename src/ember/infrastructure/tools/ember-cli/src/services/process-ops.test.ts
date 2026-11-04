// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// #2378: the Windows process operations behind the model-server lease.  parseNetstatListeners is
// pure; the rest drives the real kernel32/ntdll calls against processes THIS TEST spawns (a
// throwaway bun child), never against anything else on the machine.

import { describe, expect, it } from "bun:test";
import { spawn } from "node:child_process";
import { createServer } from "node:net";

import { createWin32ProcessOps, parseNetstatListeners } from "./process-ops.ts";

const NETSTAT = `
Active Connections

  Proto  Local Address          Foreign Address        State           PID
  TCP    0.0.0.0:135            0.0.0.0:0              LISTENING       2344
  TCP    0.0.0.0:8080           0.0.0.0:0              LISTENING       500
  TCP    127.0.0.1:18080        0.0.0.0:0              LISTENING       501
  TCP    127.0.0.1:8080         127.0.0.1:53211        ESTABLISHED     500
  TCP    127.0.0.1:53211        127.0.0.1:8080         ESTABLISHED     777
  TCP    [::]:8081              [::]:0                 LISTENING       600
  TCP    [::]:8082              [::]:0                 ABHOEREN        601
  TCP    0.0.0.0:8082           0.0.0.0:0              ABHOEREN        602
`;

describe("parseNetstatListeners", () => {
  it("finds the listener of an exact port, not a port that merely ends in the same digits", () => {
    expect(parseNetstatListeners(NETSTAT, 8080)).toEqual([500]);
    expect(parseNetstatListeners(NETSTAT, 18080)).toEqual([501]);
  });
  it("ignores established connections to the port (clients are not owners)", () => {
    expect(parseNetstatListeners(NETSTAT, 53211)).toEqual([]);
  });
  it("reads IPv6 listeners and does not depend on the localized state word", () => {
    expect(parseNetstatListeners(NETSTAT, 8081)).toEqual([600]);
  });
  it("returns every distinct owner when several processes listen on the port", () => {
    expect(parseNetstatListeners(NETSTAT, 8082).sort()).toEqual([601, 602]);
  });
  it("tolerates empty and garbage output", () => {
    expect(parseNetstatListeners("", 8080)).toEqual([]);
    expect(parseNetstatListeners("not netstat at all", 8080)).toEqual([]);
  });
});

const live = process.platform === "win32" ? describe : describe.skip;

live("createWin32ProcessOps (real Windows API, on processes this test spawns)", () => {
  const ops = createWin32ProcessOps();

  function spawnIdler() {
    // A distinctive, harmless command line; the child exits by itself after 60 s if a test fails.
    return spawn(process.execPath, ["-e", "setTimeout(() => {}, 60000)", "ember-2378-test-idler"], { stdio: "ignore", windowsHide: true });
  }
  async function waitFor<T>(fn: () => T | null, ms = 3000): Promise<T> {
    const end = Date.now() + ms;
    for (;;) {
      const v = fn();
      if (v !== null) return v;
      if (Date.now() > end) throw new Error("timed out");
      await new Promise((r) => setTimeout(r, 25));
    }
  }

  it("is available", () => { expect(ops).not.toBeNull(); });

  it("identifies this process by PID, creation time and full command line", () => {
    const me = ops!.self()!;
    expect(me.pid).toBe(process.pid);
    expect(/^\d+$/.test(me.startTime)).toBe(true);
    expect(me.cmdline.toLowerCase()).toContain("bun");
    const createdMs = Number(BigInt(me.startTime) / 10000n) - 11644473600000; // FILETIME -> Unix ms
    expect(Math.abs(createdMs - (Date.now() - process.uptime() * 1000))).toBeLessThan(5000);
  });

  it("returns null for a PID that does not exist", () => {
    expect(ops!.identify(4_000_000_000 % 0x7fffffff)).toBeNull();
    expect(ops!.identify(-1)).toBeNull();
  });

  it("finds the PID that owns a listening socket", async () => {
    const server = createServer();
    await new Promise<void>((r) => server.listen(0, "127.0.0.1", r));
    try {
      const port = (server.address() as { port: number }).port;
      expect(ops!.listenerPid(port)).toBe(process.pid);
    } finally {
      server.close();
    }
  });

  it("reports no owner for a port nobody listens on", async () => {
    const server = createServer();
    await new Promise<void>((r) => server.listen(0, "127.0.0.1", r));
    const port = (server.address() as { port: number }).port;
    await new Promise<void>((r) => server.close(() => r()));
    expect(ops!.listenerPid(port)).toBeNull();
  });

  it("terminates a process only when creation time and command line match, on the same handle", async () => {
    const child = spawnIdler();
    const exited = new Promise<void>((r) => child.once("exit", () => r()));
    try {
      const id = await waitFor(() => ops!.identify(child.pid!));
      expect(id.cmdline).toContain("ember-2378-test-idler");

      // wrong command line, wrong creation time, or a refusing accept(): the process is left alone
      expect(ops!.terminate({ ...id, cmdline: id.cmdline + " x" }, () => true)).toBe("mismatch");
      expect(ops!.terminate({ ...id, startTime: String(BigInt(id.startTime) + 1n) }, () => true)).toBe("mismatch");
      expect(ops!.terminate(id, () => false)).toBe("mismatch");
      expect(ops!.identify(child.pid!)).not.toBeNull();

      expect(ops!.terminate(id, (live) => live.cmdline.includes("ember-2378-test-idler"))).toBe("terminated");
      await exited;
      expect(ops!.identify(child.pid!)).toBeNull();
      expect(ops!.terminate(id, () => true)).toBe("gone");
    } finally {
      child.kill(); // the child is this test's own; a no-op once it has exited
    }
  });
});
