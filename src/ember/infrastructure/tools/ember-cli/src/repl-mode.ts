// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// repl-mode.ts — REPL mode detection and primitive-tool filtering.
// Covers AC1–AC6.

import { buildTool } from '../core/tool-interface.ts';
import type { Tool } from '../core/tool-interface.ts';

// ---------------------------------------------------------------------------
// AC5/AC6: Primitive tool names hidden from model when REPL mode is active
// ---------------------------------------------------------------------------

export const REPL_PRIMITIVE_TOOL_NAMES = [
  'read',
  'write',
  'edit',
  'glob',
  'grep',
  'bash',
  'notebook_edit',
  'agent',
] as const;

// ---------------------------------------------------------------------------
// isReplMode — AC2/AC3/AC4
// ---------------------------------------------------------------------------

export function isReplMode(): boolean {
  const explicitEnv = process.env['EMBER_REPL'] ?? process.env['EMBER_REPL_MODE'];

  // AC2/AC3: explicit env override takes priority
  if (explicitEnv !== undefined) {
    return explicitEnv === '1' || explicitEnv === 'true';
  }

  // Build-time default: ant + cli entrypoint
  const userType = process.env['USER_TYPE'];
  const entrypoint = process.env['EMBER_ENTRYPOINT'];
  if (userType === 'ant' && entrypoint === 'cli') return true;

  // AC4: SDK sessions default off
  return false;
}

// ---------------------------------------------------------------------------
// Singleton primitive tools list (AC5)
// ---------------------------------------------------------------------------

let _primitiveTools: Tool<unknown, unknown>[] | null = null;

export function getReplPrimitiveTools(): Tool<unknown, unknown>[] {
  if (_primitiveTools !== null) return _primitiveTools;

  _primitiveTools = REPL_PRIMITIVE_TOOL_NAMES.map(name =>
    buildTool<unknown, unknown>({
      name,
      description: () => `Primitive tool: ${name}`,
      call: async () => ({ data: null as unknown }),
      mapToolResultToToolResultBlockParam: (_, id) => ({
        type: 'tool_result' as const,
        tool_use_id: id,
        content: '',
      }),
    }),
  );

  return _primitiveTools;
}

// ---------------------------------------------------------------------------
// filterToolsForReplMode — AC1
// ---------------------------------------------------------------------------

export function filterToolsForReplMode<O>(tools: Tool<unknown, O>[]): Tool<unknown, O>[] {
  // Generic over the tool output type: the filter only inspects `.name`, so it must accept
  // any Tool<unknown, O>[] the caller holds (the test passes Tool<unknown, null>[]; the
  // non-generic Tool<unknown, unknown>[] param rejected it on output-type variance).
  if (!isReplMode()) return tools;

  const primitiveSet = new Set<string>(REPL_PRIMITIVE_TOOL_NAMES);
  return tools.filter(t => !primitiveSet.has(t.name));
}
