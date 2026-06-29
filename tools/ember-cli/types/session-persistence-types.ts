// Re-export shim. Root-level src/*.test.ts files import '../types/session-persistence-types.ts',
// which resolves here (above src/). The single source of truth is
// src/types/session-persistence-types.ts — this file only forwards it.
export * from '../src/types/session-persistence-types.ts';
