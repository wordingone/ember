// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// magic-docs.ts — Auto-updating magic documentation files for privileged users.

import type { SelectedModelContract } from './entrypoints/model-seat';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** User type required for magic-docs to be active. */
export const PRIVILEGED_USER_TYPE = 'ant';

/** Query source identifier for the main REPL thread. */
export const MAIN_REPL_QUERY_SOURCE = 'main_repl';

/** Pattern that a file must match in its content to be considered a magic-docs file. */
export const MAGIC_DOCS_HEADER_PATTERN = /<!--\s*magic-docs\s+version=\d+\s*-->/;

// ---------------------------------------------------------------------------
// Default system prompt (used when no custom prompt.md exists)
// ---------------------------------------------------------------------------

const DEFAULT_SYSTEM_PROMPT =
  'You are maintaining a special documentation file that begins with a magic header comment ' +
  '(e.g. `<!-- magic-docs version=1 -->`). Your task is to update the body of this file to reflect ' +
  'the current state of the codebase while preserving the magic header exactly as-is. ' +
  'Return only the complete updated file content — header plus body — with no additional commentary.';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface MagicDocsServiceOptions {
  /**
   * User type string. The service is entirely inactive unless this equals
   * `PRIVILEGED_USER_TYPE` ("ant").
   */
  userType: string | undefined;

  /**
   * Function that calls the model to regenerate a magic-docs file.
   * Receives `{ prompt, model, fileContent }` and returns the new file content.
   */
  callModel: (opts: {
    prompt: string;
    model: string;
    fileContent: string;
  }) => Promise<string>;

  /** Read a file from disk (may throw on missing file). */
  readFileFn: (path: string) => Promise<string>;

  /** Write updated content back to a file. */
  writeFileFn: (path: string, content: string) => Promise<void>;

  /**
   * Absolute path to the optional custom system prompt file
   * (e.g. `~/.ember/magic-docs/prompt.md`). If the file does not exist,
   * `readFileFn` should throw and the built-in default prompt is used.
   */
  customPromptPath: string;

  /**
   * The currently selected model identity + capability contract (see
   * `entrypoints/model-seat.ts::selectedModelContract`) — NOT a bare
   * modelName string, so a caller can never inject an arbitrary model
   * identity without it being seat-authorized. `undefined` means no seat
   * currently carries a model (e.g. OFFLINE or a refused seat); the service
   * fails closed and makes no model call in that case.
   */
  modelContract: SelectedModelContract | undefined;
}

interface MagicDocsService {
  /** Call when any file is read during a turn to register it for updates. */
  onFileRead(path: string, content: string, source: string): void;

  /**
   * Call when the current turn completes. If source is `MAIN_REPL_QUERY_SOURCE`
   * and the service is active, all registered paths that appear in `paths` are
   * regenerated asynchronously.
   */
  onTurnComplete(source: string, paths: string[]): void;

  /** Returns a snapshot of currently registered magic-docs paths. */
  getRegisteredPaths(): Set<string>;
}

// ---------------------------------------------------------------------------
// createMagicDocsService
// ---------------------------------------------------------------------------

export function createMagicDocsService(options: MagicDocsServiceOptions): MagicDocsService {
  const registeredPaths = new Set<string>();

  function isActive(): boolean {
    return options.userType === PRIVILEGED_USER_TYPE;
  }

  async function runUpdates(paths: string[]): Promise<void> {
    // Fail closed: no seat-authorized model identity means no model call.
    if (!options.modelContract) return;
    const modelName = options.modelContract.modelName;

    // Resolve the prompt to use for this batch
    let prompt: string;
    try {
      prompt = await options.readFileFn(options.customPromptPath);
    } catch {
      prompt = DEFAULT_SYSTEM_PROMPT;
    }

    // Update each path independently (parallel)
    await Promise.all(
      paths.map(async (path) => {
        let fileContent: string;
        try {
          fileContent = await options.readFileFn(path);
        } catch {
          // Cannot read the file — skip silently
          return;
        }

        const updated = await options.callModel({
          prompt,
          model: modelName,
          fileContent,
        });

        await options.writeFileFn(path, updated);
      }),
    );
  }

  return {
    onFileRead(path: string, content: string, _source: string): void {
      if (!isActive()) return;
      if (MAGIC_DOCS_HEADER_PATTERN.test(content)) {
        registeredPaths.add(path);
      }
    },

    onTurnComplete(source: string, paths: string[]): void {
      if (!isActive()) return;
      if (source !== MAIN_REPL_QUERY_SOURCE) return;

      // Only update paths that are both registered and were part of this turn
      const turnSet = new Set(paths);
      const toUpdate = [...registeredPaths].filter((p) => turnSet.has(p));
      if (toUpdate.length === 0) return;

      // Fire-and-forget; caller does not await this
      void runUpdates(toUpdate);
    },

    getRegisteredPaths(): Set<string> {
      // Return a snapshot to avoid exposing internal mutability
      return new Set(registeredPaths);
    },
  };
}
