// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// cli/ready-sentinel.ts — the readiness marker bytes emitted only by the
// renderer-owned first-frame callback. Writer identity is established by the
// rendering pipeline, not inferred from stdout write order.
export const READY_OSC = "\u001b]7770;EMBER_READY;v1\u0007";

interface WritableLike {
  write(chunk: string | Uint8Array, ...rest: unknown[]): boolean;
}

/** Emit the marker after the renderer has flushed its first non-empty frame. */
export function emitReadySentinel(stream: WritableLike): void {
  stream.write(READY_OSC);
}
