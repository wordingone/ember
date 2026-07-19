// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// commands/ultraplan.ts — /ultraplan slash command for launching autonomous planning sessions.

import type { CommandContext } from '../types/command-types.ts';
import { referenceSeatModelName } from '../entrypoints/model-seat.ts';
import type { SelectedModelContract } from '../entrypoints/model-seat.ts';

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

/**
 * Fix #51 round-8 repair (routing vs seat authorization): the round-5 fix
 * above only separated the routing id from its display label -- it did not
 * stop the raw routing id from being selected and sent to
 * `launchRemoteSession` unconditionally whenever `getUltraplanModel()`
 * returned null. A REFERENCE_ONLY display label is not seat authorization.
 * Thrown (message surfaced as the command's return message; no
 * `launchRemoteSession` call ever happens) when `execute()` cannot obtain a
 * seat-produced `SelectedModelContract` at all, or when the resolved seat is
 * not an explicit REFERENCE_ONLY decision and no explicit config routing id
 * was supplied either.
 */
export class UltraplanNoModelSeatContractError extends Error {
  constructor() {
    super(
      'Ultraplan cannot launch: no seat-produced model identity contract is ' +
        'available (see entrypoints/model-seat.ts::selectedModelContract), ' +
        'and no explicit ultraplan model config is set. Refusing to launch ' +
        'with an unauthorized routing id.',
    );
    this.name = 'UltraplanNoModelSeatContractError';
  }
}

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
  /**
   * The seat-produced model identity contract (see
   * `entrypoints/model-seat.ts::selectedModelContract`). `execute()` never
   * derives a model routing id without this: absent (`undefined`, no
   * resolved seat) fails closed with no `launchRemoteSession` call, and a
   * resolved seat that is NOT an explicit `REFERENCE_ONLY` decision also
   * fails closed unless `getUltraplanModel()` supplies an explicit routing
   * id -- `ULTRAPLAN_DEFAULT_MODEL_ROUTING_ID` is reachable ONLY through an
   * explicit `REFERENCE_ONLY` seat decision, never as an unconditional
   * fallback.
   */
  getModelContract: () => SelectedModelContract | undefined;
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

      // Fix #51 round-8 (P1): model routing must come from a seat-produced
      // contract, never an unconditional module constant. No resolved seat
      // at all -> fail closed, no launchRemoteSession call.
      const modelContract = deps.getModelContract();
      if (!modelContract) {
        deps.setUltraplanLaunchPending(null);
        return {
          type: 'message',
          message: new UltraplanNoModelSeatContractError().message,
        };
      }

      const configuredModel = deps.getUltraplanModel();
      let model: string;
      let modelLabel: string;
      if (configuredModel) {
        // Feature-flag config already supplies a routing id (never a
        // label); only the hardcoded fallback carries a distinct display
        // label.
        model = configuredModel;
        modelLabel = configuredModel;
      } else if (modelContract.seat === 'REFERENCE_ONLY') {
        // The hardcoded fallback routing id is reachable ONLY through this
        // explicit REFERENCE_ONLY seat decision -- never merely because
        // config happens to be unset. `modelContract.modelName` here is
        // already the display label (see `referenceSeatModelName`), never
        // the routing id -- the two stay structurally distinct fields.
        model = ULTRAPLAN_DEFAULT_MODEL_ROUTING_ID;
        modelLabel = ULTRAPLAN_DEFAULT_MODEL_LABEL;
      } else {
        // A resolved OWNED_* seat with no explicit ultraplan config carries
        // no legitimate routing id for a remote reference-model launch --
        // fail closed rather than silently reusing an owned local identity
        // or the reference-only fallback it was never authorized for.
        deps.setUltraplanLaunchPending(null);
        return {
          type: 'message',
          message: new UltraplanNoModelSeatContractError().message,
        };
      }
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
