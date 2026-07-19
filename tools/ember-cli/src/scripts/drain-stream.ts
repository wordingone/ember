// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// scripts/drain-stream.ts — reads a spawned process's stream to completion without ever waiting
// on it forever. Shared by test-gate.ts and test-gate.e2e.test.ts (the e2e test spawns a gate
// which itself spawns a killed child, so the same failure mode shows up one level up too).
//
// Verified empirically (2026-07-19) on this bun/Windows combination: after `proc.kill()` on a
// hung child (e.g. a test awaiting a never-resolving promise), the child's OS process DOES
// terminate (`proc.exited` resolves), but its stdout/stderr ReadableStream can still never signal
// close -- `new Response(stream).text()` hangs forever even though nothing is left alive to
// write to it. A single fixed-grace race around the WHOLE read (an earlier attempt here) avoids
// the hang but throws away everything actually written, because bun test's own "killed N
// dangling process" warning describes a stream that keeps its already-buffered bytes readable
// forever, just without ever emitting a final `done`. The fix is to read chunk-by-chunk and only
// give up once an INDIVIDUAL `read()` call stalls past a short idle window -- by the time the
// process has exited, every byte it wrote is already sitting in the stream's internal buffer, so
// real chunks arrive near-instantly and only the phantom "wait for done" step hangs.
export async function drainAvailable(stream: ReadableStream<Uint8Array> | null, idleMs: number): Promise<string> {
  if (!stream) return "";
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let result = "";
  try {
    while (true) {
      const chunk = reader.read();
      const idle = new Promise<"idle">((resolve) => setTimeout(() => resolve("idle"), idleMs));
      const outcome = await Promise.race([chunk, idle]);
      if (outcome === "idle" || outcome.done) break;
      result += decoder.decode(outcome.value, { stream: true });
    }
  } finally {
    try { reader.releaseLock(); } catch { /* stream may already be closed/errored */ }
  }
  return result;
}
