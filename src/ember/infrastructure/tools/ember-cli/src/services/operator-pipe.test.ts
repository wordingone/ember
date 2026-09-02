// operator-pipe.test.ts — named-pipe transport tests.
//
// Covers: real end-to-end pipe write -> onLine delivery (win32), clean no-op on
// non-Windows platforms (POSIX CI), and that the module never crashes on a
// misbehaving client.

import { describe, test, expect, afterEach } from "bun:test";
import net from "node:net";
import { startOperatorPipe, operatorPipeName, type OperatorPipeHandle } from "./operator-pipe.ts";

const openHandles: OperatorPipeHandle[] = [];

afterEach(() => {
  for (const h of openHandles.splice(0)) h.stop();
});

describe("operatorPipeName", () => {
  test("uses the well-known ember-operator-<pid> shape", () => {
    expect(operatorPipeName(1234)).toBe("\\\\.\\pipe\\ember-operator-1234");
  });

  test("defaults to the current process pid", () => {
    expect(operatorPipeName()).toBe(`\\\\.\\pipe\\ember-operator-${process.pid}`);
  });
});

describe("startOperatorPipe — non-Windows fails open", () => {
  test("no-ops cleanly when process.platform is not win32 (POSIX CI)", () => {
    const originalDescriptor = Object.getOwnPropertyDescriptor(process, "platform")!;
    Object.defineProperty(process, "platform", { value: "linux", configurable: true });

    try {
      const lines: string[] = [];
      const handle = startOperatorPipe((line) => lines.push(line));
      openHandles.push(handle);

      expect(handle.active).toBe(false);
      // stop() must be safe to call on a no-op handle.
      expect(() => handle.stop()).not.toThrow();
      expect(lines).toEqual([]);
    } finally {
      Object.defineProperty(process, "platform", originalDescriptor);
    }
  });
});

// The remaining tests exercise the real Windows named-pipe path end-to-end.
// This suite runs on the win32 CI/dev box this feature targets; on any other
// platform the transport itself already no-ops (covered above), so skipping
// here just avoids a redundant no-op assertion.
const winDescribe = process.platform === "win32" ? describe : describe.skip;

winDescribe("startOperatorPipe — real named pipe (win32)", () => {
  test("a line written to the pipe is delivered to onLine, split on newlines", async () => {
    const pid = 900000 + Math.floor(Math.random() * 90000);
    const received: string[] = [];
    const connected: string[] = [];

    const handle = startOperatorPipe((line) => received.push(line), {
      pid,
      onEvent: (e) => { if (e.kind === "pipe_connected") connected.push("connected"); },
    });
    openHandles.push(handle);

    expect(handle.active).toBe(true);
    expect(handle.pipeName).toBe(operatorPipeName(pid));

    await new Promise<void>((resolve, reject) => {
      const socket = net.connect(handle.pipeName, () => {
        socket.write("first operator line\n");
        socket.write("second line\r\n");
        socket.end();
      });
      socket.on("close", () => resolve());
      socket.on("error", reject);
    });

    // Give the server a tick to finish processing the final chunk.
    await new Promise((r) => setTimeout(r, 50));

    expect(connected).toEqual(["connected"]);
    expect(received).toEqual(["first operator line", "second line"]);
  });

  test("a chunk split mid-line is buffered until the newline arrives", async () => {
    const pid = 900000 + Math.floor(Math.random() * 90000);
    const received: string[] = [];
    const handle = startOperatorPipe((line) => received.push(line), { pid });
    openHandles.push(handle);

    await new Promise<void>((resolve, reject) => {
      const socket = net.connect(handle.pipeName, () => {
        socket.write("partial-");
        setTimeout(() => {
          socket.write("line\n");
          socket.end();
        }, 10);
      });
      socket.on("close", () => resolve());
      socket.on("error", reject);
    });

    await new Promise((r) => setTimeout(r, 50));
    expect(received).toEqual(["partial-line"]);
  });

  test("a socket error from a misbehaving client never crashes the server", async () => {
    const pid = 900000 + Math.floor(Math.random() * 90000);
    const events: string[] = [];
    const handle = startOperatorPipe(() => {}, {
      pid,
      onEvent: (e) => events.push(e.kind),
    });
    openHandles.push(handle);

    await new Promise<void>((resolve, reject) => {
      const socket = net.connect(handle.pipeName, () => {
        // Abruptly destroy with an error rather than a clean close.
        socket.destroy(new Error("simulated client failure"));
      });
      socket.on("close", () => resolve());
      socket.on("error", () => resolve());
      setTimeout(reject, 2000);
    });

    // The transport must still be listening — a second, well-behaved client works.
    const secondLine = await new Promise<string>((resolve, reject) => {
      const lines: string[] = [];
      const h2 = startOperatorPipe((line) => { lines.push(line); resolve(line); }, { pid: pid + 1 });
      openHandles.push(h2);
      const socket = net.connect(h2.pipeName, () => {
        socket.write("still alive\n");
      });
      socket.on("error", reject);
      setTimeout(() => reject(new Error("timed out waiting for second line")), 2000);
    });

    expect(secondLine).toBe("still alive");
    expect(events).toContain("pipe_connected");
  });
});
