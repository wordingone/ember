// commands/ultraplan.ts — /ultraplan slash command for launching autonomous planning sessions.

import type { CommandContext } from '../types/command-types.ts';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

export const ULTRAPLAN_DEFAULT_MODEL = 'qwen3-5';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface UltraplanLaunchResult {
  sessionUrl: string;
  executionTarget: 'remote' | 'local';
  planContent?: string;
}

export interface UltraplanDeps {
  isUltraplanEligible: () => boolean;
  getUltraplanModel: () => string | null;
  getUltraplanSessionUrl: () => string | null;
  setUltraplanSessionUrl: (url: string | null) => void;
  setUltraplanLaunching: (v: boolean) => void;
  setUltraplanLaunchPending: (p: { blurb: string } | null) => void;
  setUltraplanPendingChoice: (p: unknown) => void;
  checkRemoteSessionEligibility: () => Promise<boolean>;
  launchRemoteSession: (opts: {
    model: string;
    blurb: string;
    [key: string]: unknown;
  }) => Promise<UltraplanLaunchResult | null>;
  archiveSession: (url: string) => Promise<void>;
  killRemoteTask: (url: string) => Promise<void>;
  notifyUser: (msg: string) => void;
  emitAnalytics: (event: string) => void;
}

// ---------------------------------------------------------------------------
// stopUltraplan
// ---------------------------------------------------------------------------

export async function stopUltraplan(deps: UltraplanDeps): Promise<void> {
  const url = deps.getUltraplanSessionUrl();
  if (url === null) return;

  await deps.killRemoteTask(url);
  await deps.archiveSession(url);
  deps.setUltraplanSessionUrl(null);
}

// ---------------------------------------------------------------------------
// createUltraplanCommand
// ---------------------------------------------------------------------------

type UltraplanResult = { type: 'message'; message: string } | { type: 'none' };

export function createUltraplanCommand(deps: UltraplanDeps) {
  return {
    name: 'ultraplan',
    type: 'local-jsx',
    description: 'Launch an autonomous planning and coding session',

    isEnabled(): boolean {
      return deps.isUltraplanEligible();
    },

    async execute(args: string, _ctx: CommandContext): Promise<UltraplanResult> {
      const blurb = args.trim();

      if (!blurb) {
        return {
          type: 'message',
          message: 'Usage: /ultraplan <description>\n\nDescribe what you want to plan or build.',
        };
      }

      // Signal launch pending
      deps.setUltraplanLaunchPending({ blurb });

      // Check remote eligibility
      const eligible = await deps.checkRemoteSessionEligibility();
      if (!eligible) {
        deps.setUltraplanLaunchPending(null);
        return {
          type: 'message',
          message: 'You are not eligible to use ultraplan at this time.',
        };
      }

      const model = deps.getUltraplanModel() ?? ULTRAPLAN_DEFAULT_MODEL;
      deps.setUltraplanLaunching(true);

      let launchResult: UltraplanLaunchResult | null = null;
      try {
        launchResult = await deps.launchRemoteSession({ model, blurb });
      } finally {
        deps.setUltraplanLaunching(false);
        deps.setUltraplanLaunchPending(null);
      }

      if (launchResult === null) {
        return { type: 'message', message: 'Failed to launch ultraplan session.' };
      }

      if (launchResult.executionTarget === 'remote') {
        deps.setUltraplanSessionUrl(null);
        deps.notifyUser('Ember is now coding your plan. You will be notified when it is ready.');
        return {
          type: 'message',
          message: `Ultraplan session started. Ember is coding your plan.`,
        };
      }

      // local execution: set pending choice
      deps.setUltraplanPendingChoice({
        planContent: launchResult.planContent,
        sessionUrl: launchResult.sessionUrl,
      });

      return {
        type: 'message',
        message: `Ultraplan session started locally.`,
      };
    },
  };
}
