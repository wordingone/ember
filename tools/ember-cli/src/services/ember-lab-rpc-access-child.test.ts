// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// This test is only registered inside the parent-spawned process below.
// It keeps the mocked transport isolated from normal Bun test discovery.

if (process.env["EMBER_LAB_ACCESS_CHILD"] === "1") {
  const { expect, mock, test } = await import("bun:test");
  const { EventEmitter } = await import("node:events");

  class DeniedSocket extends EventEmitter {
    destroy(): this { return this; }
  }

  test("one denied connection", async () => {
    let connections = 0;
    mock.module("node:net", () => ({
      default: {
        createConnection(): DeniedSocket {
          connections += 1;
          const socket = new DeniedSocket();
          queueMicrotask(() => {
            socket.emit("error", Object.assign(new Error("access denied"), { code: "EACCES" }));
          });
          return socket;
        },
      },
    }));

    const { callEmberLab } = await import("./ember-lab-rpc.ts?access-denied-regression");
    await expect(callEmberLab({
      pipeName: "\\\\.\\pipe\\ember-lab-access-denied",
      requestId: "denied",
      method: "ping",
      params: {},
    })).rejects.toThrow("same-user named-pipe access denied");
    expect(connections).toBe(1);
  });
}