// commands/advisor.ts — /advisor slash command.
// Manages the per-user advisor model override.

import type { CommandContext } from '../types/command-types.ts';

// ---------------------------------------------------------------------------
// Deps interface (injectable for testing)
// ---------------------------------------------------------------------------

export interface AdvisorDeps {
  canUserConfigureAdvisor: () => boolean;
  getAdvisorModel: () => string | null;
  setAdvisorModel: (model: string) => Promise<void>;
  clearAdvisorModel: () => Promise<void>;
  getBaseModel: () => string;
  parseModelAlias: (input: string) => string | null;
  isValidModel: (model: string) => boolean;
  isValidAdvisorModel: (model: string) => boolean;
  baseModelSupportsAdvisors: (baseModel: string) => boolean;
}

// ---------------------------------------------------------------------------
// Result type
// ---------------------------------------------------------------------------

type AdvisorResult = { type: 'message'; message: string };

// ---------------------------------------------------------------------------
// Factory
// ---------------------------------------------------------------------------

export function createAdvisorCommand(deps: AdvisorDeps) {
  return {
    name: 'advisor',
    description: 'Configure the advisor model for enhanced responses',

    isEnabled(): boolean {
      return deps.canUserConfigureAdvisor();
    },

    async execute(args: string, _ctx: CommandContext): Promise<AdvisorResult> {
      const input = args.trim();

      // No args: show current advisor state
      if (!input) {
        const current = deps.getAdvisorModel();
        if (!current) {
          return { type: 'message', message: 'No advisor model configured.' };
        }
        const base = deps.getBaseModel();
        const supported = deps.baseModelSupportsAdvisors(base);
        let message = `Advisor model: ${current}`;
        if (!supported) {
          message += ' (inactive — current base model does not support advisors)';
        }
        return { type: 'message', message };
      }

      // Clear subcommands
      if (input === 'off' || input === 'unset') {
        await deps.clearAdvisorModel();
        return { type: 'message', message: 'Advisor model cleared.' };
      }

      // Resolve alias → canonical name
      const resolved = deps.parseModelAlias(input);
      if (resolved === null) {
        return { type: 'message', message: `Unknown model: "${input}".` };
      }

      if (!deps.isValidModel(resolved)) {
        return { type: 'message', message: `Unknown model: "${resolved}".` };
      }

      if (!deps.isValidAdvisorModel(resolved)) {
        return { type: 'message', message: `"${resolved}" is not a valid advisor model.` };
      }

      await deps.setAdvisorModel(resolved);
      return { type: 'message', message: `Advisor model set to: ${resolved}.` };
    },
  };
}
