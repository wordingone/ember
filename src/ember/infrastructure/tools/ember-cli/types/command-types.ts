// Re-export shim. Root-level src/*.test.ts files import '../types/command-types.ts',
// which resolves here (above src/). The single source of truth is
// src/types/command-types.ts — this file only forwards it so both the root-level
// tests and src/commands/*.test.ts (whose '../types/...' resolves into src/types/)
// bind the SAME definitions. Do not add declarations here; edit src/types/command-types.ts.
export * from '../src/types/command-types.ts';
