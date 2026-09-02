// usage.ts — /usage slash command.
// Renders the usage and rate-limit status screen (cloud surface only).

import type { CommandContext } from './types/command-types.ts';

export const usageCommand = {
  name: 'usage',
  type: 'local-jsx' as const,
  availability: ['cloud'] as string[],
  description: 'View your usage and rate limit status',

  isEnabled(): boolean {
    return true;
  },

  // In headless contexts the TUI-rendered settings screen is unavailable, so
  // the command is a no-op. The interactive path mounts a React/Ink component.
  async execute(_args: string, _ctx: CommandContext) {
    return { type: 'none' as const };
  },
};
