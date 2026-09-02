// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// version.ts — version command and build-time output for the Ember CLI.

import type { RegistryCommand, CommandContext, CommandResult } from './types/command-types.ts';
import { VERSION } from './agent-identity.ts';

// ---- Injectable getters (overridden in tests) ----

type VersionFn = () => string;
type BuildTimeFn = () => string;

let _getVersion: VersionFn = () => VERSION;
let _getBuildTime: BuildTimeFn = () => new Date().toISOString();

/**
 * Overrides the version and build-time getters for unit tests.
 * TEST-ONLY: call _resetVersionGetters() in afterEach to restore defaults.
 */
export function _setVersionGettersForTests(
  versionFn: VersionFn,
  buildTimeFn: BuildTimeFn,
): void {
  _getVersion = versionFn;
  _getBuildTime = buildTimeFn;
}

/** Restores default getters after test injection. */
export function _resetVersionGetters(): void {
  _getVersion = () => VERSION;
  _getBuildTime = () => new Date().toISOString();
}

// ---- Output builder ----

/**
 * Returns a multi-line string containing the current version and build time.
 * Format: "Version: X.Y.Z\nBuild time: <ISO timestamp>"
 */
export function buildVersionOutput(): string {
  return `Version: ${_getVersion()}\nBuild time: ${_getBuildTime()}`;
}

// ---- Slash command definition ----

/**
 * Version command — prints the CLI version and build time.
 * Only enabled for internal (ant) users via USER_TYPE env var.
 */
export const versionCommand: RegistryCommand = {
  name: 'version',
  description: 'Display the current version of the CLI and build metadata',

  isEnabled(): boolean {
    return process.env['USER_TYPE'] === 'ant';
  },

  async execute(_args: string, _ctx: CommandContext): Promise<CommandResult> {
    return { type: 'message', message: buildVersionOutput() };
  },
};
