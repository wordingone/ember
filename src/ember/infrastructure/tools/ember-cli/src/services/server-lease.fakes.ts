// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// Test doubles for the model-server lease (#2378): a fake machine of processes and listeners, and
// per-instance ProcessOps views of it, so adopt/spawn/exit/crash/reuse scenarios run with no real
// process, no model server and no Windows API.

import type { ProcessIdentity, ProcessOps, TerminateOutcome } from "./process-ops.ts";

interface FakeProc {
  startTime: string;
  /** Computed lazily so a command line can mention a port the test only learns during main(). */
  cmdline: () => string;
}

export class FakeWorld {
  procs = new Map<number, FakeProc>();
  listeners = new Map<number, number | "ambiguous">();
  /** Every terminate() call that reached the "kill" step, in order. */
  killed: number[] = [];
  /** Every terminate() call, with its outcome. */
  terminateCalls: Array<{ pid: number; outcome: TerminateOutcome }> = [];
  /** When set, this PID owns the listening socket on whatever port is asked about. */
  anyPortListener: number | null = null;
  askedPorts: number[] = [];
  events: string[] = [];

  addProcess(pid: number, cmdline: string | (() => string), startTime = String(1000 + pid)): void {
    this.procs.set(pid, { startTime, cmdline: typeof cmdline === "function" ? cmdline : () => cmdline });
  }

  llamaServer(pid: number, port: number | (() => number), exe = "C:\\llama\\llama-server.exe"): void {
    this.addProcess(pid, () => `"${exe}" --model m.gguf --port ${typeof port === "function" ? port() : port}`);
  }

  die(pid: number): void { this.procs.delete(pid); }

  /** The PID is recycled by an unrelated process. */
  reuse(pid: number, cmdline: string): void { this.addProcess(pid, cmdline, String(9_000_000 + pid)); }

  isAlive(pid: number): boolean { return this.procs.has(pid); }

  /** ProcessOps as seen from the process `selfPid`. */
  ops(selfPid: number): ProcessOps {
    const identify = (pid: number): ProcessIdentity | null => {
      const p = this.procs.get(pid);
      return p ? { pid, startTime: p.startTime, cmdline: p.cmdline() } : null;
    };
    return {
      identify,
      self: () => identify(selfPid),
      listenerPid: (port) => {
        this.askedPorts.push(port);
        return this.listeners.get(port) ?? this.anyPortListener;
      },
      terminate: (expected, accept) => {
        const live = identify(expected.pid);
        let outcome: TerminateOutcome;
        if (!live) outcome = "gone";
        else if (live.startTime !== expected.startTime || live.cmdline !== expected.cmdline || !accept(live)) outcome = "mismatch";
        else { this.procs.delete(expected.pid); this.killed.push(expected.pid); outcome = "terminated"; }
        this.terminateCalls.push({ pid: expected.pid, outcome });
        this.events.push(`terminate:${expected.pid}:${outcome}`);
        return outcome;
      },
    };
  }
}
