// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// cli/ready-sentinel.ts — positive, product-emitted readiness signal for the
// interactive TUI, observable by a headless ConPTY driver.
//
// Why this exists: the cockpit repaints a live clock, so it NEVER quiesces —
// any driver-side inference ("frame stopped changing", "N ms elapsed") is
// structurally unable to detect readiness (burst receipt 2026-07-25). The
// only reliable signal is one the product itself states when it is genuinely
// ready to accept input.
//
// Design: an OSC (Operating System Command) escape sequence written to stdout
// immediately after the FIRST real frame flush of the mounted REPL render
// tree. Properties:
//   - Stream-positional, not frame-positional: a repainting surface cannot
//     erase or obscure bytes already emitted on the stream. A driver scanning
//     the raw ConPTY byte stream sees it exactly once, forever.
//   - Invisible: xterm-family parsers consume unknown OSC sequences without
//     rendering anything, so frame geometry and pixel checks are unaffected.
//   - Unfakeable-by-accident: armReadySentinel() is called only after the
//     REPL component imports resolved and the render tree mounted without
//     throwing, and the sentinel is appended only after ink's first frame
//     write actually reaches the stream. A boot that dies at the seat gate,
//     fails an import, or mounts a renderer that never paints emits nothing.
export const READY_OSC = "\u001b]7770;EMBER_READY;v1\u0007";

interface WritableLike {
  write(chunk: string | Uint8Array, ...rest: unknown[]): boolean;
}

/**
 * Arms a one-shot readiness sentinel on `stream`.
 *
 * Call this immediately BEFORE the initial render() of the interactive REPL
 * tree (all boot gates already passed at that point). The very next write to
 * `stream` — ink's first frame flush — gets the sentinel appended directly
 * after it, then the wrapper removes itself. No write, no sentinel: a render
 * tree that throws before painting, or a renderer that never flushes, cannot
 * satisfy the gate.
 */
export function armReadySentinel(stream: WritableLike): void {
  const originalWrite = stream.write;
  let fired = false;
  stream.write = ((chunk: string | Uint8Array, ...rest: unknown[]): boolean => {
    const result = originalWrite.call(stream, chunk, ...rest);
    if (!fired) {
      fired = true;
      stream.write = originalWrite;
      originalWrite.call(stream, READY_OSC);
    }
    return result;
  }) as WritableLike["write"];
}
