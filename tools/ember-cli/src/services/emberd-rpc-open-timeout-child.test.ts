// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

if (process.env["EMBERD_OPEN_TIMEOUT_CASE"] === "silent") {
  const { expect, mock, test } = await import("bun:test");
  const { EventEmitter } = await import("node:events");

  let lateConnect = false;
  let socket: SilentSocket | undefined;
  class SilentSocket extends EventEmitter {
    destroyed = false;
    destroy(): this { this.destroyed = true; return this; }
  }

  test("open deadline destroys a silent socket and rejects", async () => {
    mock.module("node:net", () => ({
      default: { createConnection(): SilentSocket { socket = new SilentSocket(); if (lateConnect) setTimeout(() => socket?.emit("connect"), 10_050); return socket; } },
    }));
    const { callEmberd } = await import("./emberd-rpc.ts?open-timeout-regression");
    await expect(callEmberd({ pipeName: "\\\\.\\pipe\\emberd-open-timeout", requestId: "silent", method: "ping", params: {} }))
      .rejects.toThrow("open retry window elapsed");
    expect(socket?.destroyed).toBe(true);
  }, 12_000);
}

if (process.env["EMBERD_OPEN_TIMEOUT_CASE"] === "late") {
  const { expect, test } = await import("bun:test");
  const net = await import("node:net");
  const { callEmberd } = await import("./emberd-rpc.ts?late-connect-regression");

  test("late pipe availability after the open deadline cannot revive the request", async () => {
    const pipe = `\\\\.\\pipe\\emberd-late-connect-${process.pid}-${Math.random().toString(16).slice(2)}`;
    let connections = 0;
    const server = net.createServer((socket) => {
      connections += 1;
      socket.destroy();
    });
    const result = callEmberd({ pipeName: pipe, requestId: "late", method: "ping", params: {} })
      .then(() => "resolved", (error: unknown) => error);
    await new Promise((resolve) => setTimeout(resolve, 10_050));
    await new Promise<void>((resolve, reject) => server.listen(pipe, () => resolve()).once("error", reject));
    const settled = await result;
    await new Promise((resolve) => setTimeout(resolve, 100));
    await new Promise<void>((resolve) => server.close(() => resolve()));
    expect(settled).toBeInstanceOf(Error);
    expect((settled as Error).message).toContain("open retry window elapsed");
    expect(connections).toBe(0);
  }, 12_000);
}
