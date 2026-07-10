// services/__fixtures__/fake-brain-server.ts — synthetic stub for brain-server-supervisor's
// execution-binding tests (issue #122). Mimics serve_cbase_openai.py's /health readiness
// contract ({"status":"loading"} then {"status":"ready", model, device}) and clean SIGTERM
// exit, WITHOUT loading any model or touching the GPU -- this process never allocates VRAM
// and never imports torch/transformers, so it is safe to actually spawn during the
// 2026-07-10 planned GPU outage (the outage bans GPU-model servers / VRAM allocation, not
// harmless CPU test doubles).
//
// argv (all optional, read via env for simplicity across bun's script invocation):
//   FAKE_BRAIN_PORT            port to listen on (required)
//   FAKE_BRAIN_READY_DELAY_MS  ms to stay "loading" before flipping to "ready" (default 50)
//   FAKE_BRAIN_EXIT_IMMEDIATELY  if "1", exit(7) before ever listening (simulates a crash-on-
//                                 start, e.g. the bad-checkpoint-path failure class)
//   FAKE_BRAIN_NEVER_READY     if "1", stays "loading" forever (simulates a hang)
//
// Prints "FAKE_BRAIN_LISTENING <port>" once bound, so a test can synchronize without racing
// the OS socket-accept path.

const port = Number(process.env["FAKE_BRAIN_PORT"] ?? "0");
const readyDelayMs = Number(process.env["FAKE_BRAIN_READY_DELAY_MS"] ?? "50");
const exitImmediately = process.env["FAKE_BRAIN_EXIT_IMMEDIATELY"] === "1";
const neverReady = process.env["FAKE_BRAIN_NEVER_READY"] === "1";

if (exitImmediately) {
  process.exit(7);
}

let ready = false;
if (!neverReady) {
  setTimeout(() => { ready = true; }, readyDelayMs);
}

const server = Bun.serve({
  port,
  fetch(req) {
    const url = new URL(req.url);
    if (url.pathname === "/health") {
      if (ready) {
        return Response.json({ status: "ready", model: "fake-cbase-2.2b", device: "cpu" });
      }
      return Response.json({ status: "loading" });
    }
    return new Response("not found", { status: 404 });
  },
});

process.stdout.write(`FAKE_BRAIN_LISTENING ${server.port}\n`);

function shutdown(): void {
  server.stop(true);
  process.exit(0);
}
process.on("SIGTERM", shutdown);
process.on("SIGINT", shutdown);
