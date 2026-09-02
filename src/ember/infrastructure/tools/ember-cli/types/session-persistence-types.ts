// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// Re-export shim. Root-level src/*.test.ts files import '../types/session-persistence-types.ts',
// which resolves here (above src/). The single source of truth is
// src/types/session-persistence-types.ts — this file only forwards it.
export * from '../src/types/session-persistence-types.ts';
