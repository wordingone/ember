// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// Per-engine app state for ToolUseContext.getAppState/setAppState. The REPL used to hand tools a
// fresh `{cwd}` on every read and a no-op setter, so state a tool wrote (TodoWrite's list) was
// gone by the next call (blind test T10: every call reported oldTodos: []).

export interface SessionAppState {
  get: () => Record<string, unknown>;
  set: (updater: (prev: unknown) => unknown) => void;
}

export function createSessionAppState(cwd: string): SessionAppState {
  let state: Record<string, unknown> = { cwd };
  return {
    get: () => state,
    set: (updater) => {
      const next = updater(state);
      if (next !== null && typeof next === "object") state = { ...(next as Record<string, unknown>), cwd };
    },
  };
}
