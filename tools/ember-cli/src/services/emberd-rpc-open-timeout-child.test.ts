// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

if (process.env["EMBERD_OPEN_TIMEOUT_CHILD"] === "1") {
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
  test("late connect after the open deadline cannot revive the request", async () => {
    lateConnect = true;
    socket = undefined;
    const { callEmberd } = await import("./emberd-rpc.ts?late-connect-regression");
    await expect(callEmberd({ pipeName: "\\\\.\\pipe\\emberd-late-connect", requestId: "late", method: "ping", params: {} }))
      .rejects.toThrow("open retry window elapsed");
    await new Promise((resolve) => setTimeout(resolve, 100));
    expect(socket?.destroyed).toBe(true);
  }, 12_000);
}