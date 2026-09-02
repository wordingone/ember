// Re-export shim. Root-level src/*.test.ts files import '../services/mcp-config.ts',
// which resolves here (above src/). The single source of truth is
// src/mcp-config.ts — this file only forwards it so the root-level tests bind the
// SAME definitions. Do not add declarations here; edit src/mcp-config.ts.
export * from '../src/mcp-config.ts';
