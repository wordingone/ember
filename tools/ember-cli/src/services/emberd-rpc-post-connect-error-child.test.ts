// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

if (process.env["EMBERD_POST_CONNECT_ERROR_CHILD"] === "1") {
  const { expect, mock, test } = await import("bun:test");
  const { EventEmitter } = await import("node:events");

  class ResetAfterConnectSocket extends EventEmitter {
    destroyed = false;
    destroy(): this { this.destroyed = true; return this; }
    write(): true { return true; }
  }

  test("connected reset rejects promptly", async () => {
    let socket: ResetAfterConnectSocket | undefined;
    mock.module("node:net", () => ({
      default: {
        createConnection(): ResetAfterConnectSocket {
          socket = new ResetAfterConnectSocket();
          queueMicrotask(() => {
            socket?.emit("connect");
            setTimeout(() => socket?.emit("error", Object.assign(new Error("transport reset"), { code: "ECONNRESET" })), 10);
          });
          return socket;
        },
      },
    }));

    const { callEmberd } = await import("./emberd-rpc.ts?post-connect-error-regression");
    const startedAt = performance.now();
    await expect(callEmberd({
      pipeName: "\\\\.\\pipe\\emberd-post-connect-reset",
      requestId: "reset",
      method: "ping",
      params: {},
      timeoutMs: 500,
    })).rejects.toThrow("transport reset");
    expect(performance.now() - startedAt).toBeLessThan(250);
    expect(socket?.destroyed).toBe(true);
  });
}
