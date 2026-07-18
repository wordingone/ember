// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// commands/ultraplan.ts — /ultraplan slash command for launching autonomous planning sessions.

import type { CommandContext } from '../types/command-types.ts';
import { referenceSeatModelName } from '../entrypoints/model-seat.ts';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/**
 * Fix #51 round-5 repair (routing vs label): the prior single constant
 * `ULTRAPLAN_DEFAULT_MODEL` equaled the display label
 * "REFERENCE_ONLY: qwen3-5" and production passed that label straight to
 * `launchRemoteSession({ model })` -- the provider session API needs the
 * functional routing id, never a provenance-labeled string. These are now
 * two structured fields:
 *
 * - `ULTRAPLAN_DEFAULT_MODEL_ROUTING_ID`: the exact value the session API
 *   expects in its `model` param. Never prefixed, never labeled.
 * - `ULTRAPLAN_DEFAULT_MODEL_LABEL`: the same `referenceSeatModelName`
 *   provenance/display label every other borrowed/unverified identity in
 *   the codebase uses, for logging and display ONLY. It must never reach
 *   `launchRemoteSession`'s `model` param.
 */
export const ULTRAPLAN_DEFAULT_MODEL_ROUTING_ID = 'qwen3-5';
export const ULTRAPLAN_DEFAULT_MODEL_LABEL = referenceSeatModelName(
  ULTRAPLAN_DEFAULT_MODEL_ROUTING_ID,
);

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
    /** Functional routing id passed to the provider session API. Never a display label. */
    model: string;
    /** Provenance/display label only (e.g. "REFERENCE_ONLY: qwen3-5"); never sent as `model`. */
    modelLabel: string;
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

      const configuredModel = deps.getUltraplanModel();
      const model = configuredModel ?? ULTRAPLAN_DEFAULT_MODEL_ROUTING_ID;
      // Feature-flag config already supplies a routing id (never a label);
      // only the hardcoded fallback carries a distinct display label.
      const modelLabel = configuredModel ?? ULTRAPLAN_DEFAULT_MODEL_LABEL;
      deps.setUltraplanLaunching(true);

      let launchResult: UltraplanLaunchResult | null = null;
      try {
        launchResult = await deps.launchRemoteSession({ model, modelLabel, blurb });
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
