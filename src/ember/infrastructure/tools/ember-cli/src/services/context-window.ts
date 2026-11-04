// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// services/context-window.ts -- the model server's context size (n_ctx), shared as a leaf.
//
// session-init.ts probes /props once and publishes the result here; the query engine and
// compaction read it back without importing the entrypoint layer. Null until probed.

let contextWindowTokens: number | null = null;

export function setContextWindowTokens(tokens: number | null): void {
  contextWindowTokens = tokens !== null && Number.isFinite(tokens) && tokens > 0 ? Math.floor(tokens) : null;
}

export function getContextWindowTokens(): number | null {
  return contextWindowTokens;
}
