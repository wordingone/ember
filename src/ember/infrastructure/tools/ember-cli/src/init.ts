// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// init.ts — /init slash command (EMBER.md initializer).

import type { RegistryCommand, CommandContext, CommandResult } from './types/command-types.ts';

// ---------------------------------------------------------------------------
// Prompt constants
// ---------------------------------------------------------------------------

export const OLD_PATH_PROMPT =
  'Please create an EMBER.md file in the current directory. ' +
  'Do not ask for confirmation before writing. ' +
  'The file should summarize the project structure and key conventions.';

export const NEW_PATH_PROMPT =
  'You will guide the user through an 8-phase project initialization wizard.\n\n' +
  'Phase 1: Gather project context — ask the user to describe their project.\n' +
  'Phase 2: Identify the technology stack and language(s) used.\n' +
  'Phase 3: Understand team conventions and coding standards.\n' +
  'Phase 4: Begin writing the EMBER.md file (do not write any files until phase 4 at the earliest).\n' +
  'Phase 5: Review architecture decisions and document key components.\n' +
  'Phase 6: Add workflow and build instructions.\n' +
  'Phase 7: Document testing conventions and quality gates.\n' +
  'Phase 8: Final review — ask the user if anything is missing.\n\n' +
  'Start with Phase 1 and wait for the user to respond before proceeding.';

// ---------------------------------------------------------------------------
// Deps
// ---------------------------------------------------------------------------

export interface InitCommandDeps {
  maybeMarkProjectOnboardingComplete: () => void;
  isNewInitEnabled: () => boolean;
}

const defaultDeps: InitCommandDeps = {
  maybeMarkProjectOnboardingComplete: () => {},
  isNewInitEnabled: () =>
    !!process.env['EMBER_NEW_INIT'] || process.env['USER_TYPE'] === 'ant',
};

let deps: InitCommandDeps = { ...defaultDeps };

export function setInitCommandDeps(overrides: Partial<InitCommandDeps>): void {
  deps = { ...deps, ...overrides };
}

export function _resetInitCommandDeps(): void {
  deps = { ...defaultDeps };
}

// ---------------------------------------------------------------------------
// Core logic
// ---------------------------------------------------------------------------

export function buildInitPrompt(d: InitCommandDeps): string {
  d.maybeMarkProjectOnboardingComplete();
  return d.isNewInitEnabled() ? NEW_PATH_PROMPT : OLD_PATH_PROMPT;
}

// ---------------------------------------------------------------------------
// Command object
// ---------------------------------------------------------------------------

export const initCommand: RegistryCommand = {
  name: 'init',
  description: 'Initialize a project EMBER.md file',
  type: 'prompt',

  isEnabled(): boolean {
    return true;
  },

  async execute(_args: string, _ctx: CommandContext): Promise<CommandResult> {
    const message = buildInitPrompt(deps);
    return { type: 'message', message };
  },
};
