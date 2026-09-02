// core/tool-use-context.ts
// Execution context injected into every tool call: app state, abort signal, model
// selection, registered tools, and budgeting.
//
// The canonical interface definition lives in core/tool-interface.ts; this module
// re-exports it as the public surface and adds the createToolUseContext factory.

export type {
  ToolUseContext,
  ToolUseContextOptions,
} from './tool-interface.ts';

import type { ToolUseContextOptions, ToolUseContext } from './tool-interface.ts';

/**
 * Creates a minimal ToolUseContext suitable for unit tests and embedded use cases
 * where the full session environment is not available.
 *
 * @param options - Context options (tools, model, prompts, budget, etc.)
 * @param abortSignal - Optional pre-existing abort signal; a new AbortController
 *   is created when omitted.
 */
export function createToolUseContext(
  options: ToolUseContextOptions,
  abortSignal?: AbortSignal,
): ToolUseContext {
  let appState: unknown = {};
  let abortController: AbortController;

  if (abortSignal) {
    // Wrap the external signal in a controller we can also abort from cancel().
    abortController = new AbortController();
    abortSignal.addEventListener('abort', () => abortController.abort(), { once: true });
  } else {
    abortController = new AbortController();
  }

  return {
    options,
    abortController,
    messages: [],
    getAppState: () => appState,
    setAppState: (updater: (prev: unknown) => unknown): void => {
      appState = updater(appState);
    },
  };
}
