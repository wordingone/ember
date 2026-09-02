// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// commands/files.ts — /files slash command.
// Lists all file paths currently held in the session context cache.

import type { CommandContext } from '../types/command-types.ts';

// ---------------------------------------------------------------------------
// Deps interface (injectable for testing)
// ---------------------------------------------------------------------------

interface FilesCommandDeps {
  getCachedFilePaths: () => string[];
  getUserType: () => string | undefined;
}

type FilesResult = { type: 'message'; message: string };

// ---------------------------------------------------------------------------
// Factory
// ---------------------------------------------------------------------------

export function createFilesCommand(deps: FilesCommandDeps) {
  return {
    name: 'files',
    description: 'List all files currently in the context cache',

    isEnabled(): boolean {
      return deps.getUserType() === 'ant';
    },

    async execute(_args: string, _ctx: CommandContext): Promise<FilesResult> {
      const paths = deps.getCachedFilePaths();

      if (paths.length === 0) {
        return { type: 'message', message: 'Context cache: no files loaded.' };
      }

      const sorted = [...paths].sort();
      return { type: 'message', message: sorted.join('\n') };
    },
  };
}
