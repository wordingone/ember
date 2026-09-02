// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// commands/ultrareview.ts — /ultrareview slash command for AI-powered code review.

import type { CommandContext } from '../types/command-types.ts';
import { referenceSeatModelName } from '../entrypoints/model-seat.ts';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

export const BUGHUNTER_DRY_RUN = '1';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type UltrareviewBillingGate =
  | { type: 'proceed'; reviewsRemaining?: number; totalReviews?: number }
  | { type: 'low-balance'; balance: number }
  | { type: 'not-enabled'; settingsUrl: string }
  | { type: 'needs-confirm' };

export interface UltrareviewLaunchResult {
  sessionUrl: string;
}

interface BundleResult {
  tooLarge: boolean;
  bundlePath?: string;
}

export interface UltrareviewDeps {
  isBughunterEnabled: () => boolean;
  fetchBillingGate: () => Promise<UltrareviewBillingGate>;
  hasConfirmedOverage: () => boolean;
  confirmOverage: () => void;
  renderOverageDialog: () => Promise<boolean>;
  checkRemoteEligibility: () => Promise<{ type: string }>;
  getCurrentRepository: () => Promise<string | null>;
  getDefaultBranch: () => Promise<string>;
  computeMergeBase: () => Promise<string | null>;
  getDiffBetween: (base: string, head: string) => Promise<string>;
  bundleWorkingTree: () => Promise<BundleResult>;
  onEscape: (cb: () => void) => () => void;
  launchRemoteSession: (opts: {
    env: Record<string, string>;
    prRef?: string;
    useBundle?: boolean;
    bundlePath?: string;
  }) => Promise<UltrareviewLaunchResult | null>;
  setShouldQuery: (v: boolean) => void;
  emitAnalytics: (event: string, props: Record<string, unknown>) => void;
  getBughunterConfig: () => ReturnType<typeof defaultBughunterConfig>;
}

// ---------------------------------------------------------------------------
// defaultBughunterConfig
// ---------------------------------------------------------------------------

export function defaultBughunterConfig() {
  return {
    enabled: true,
    // Fix #51 fiction purge: was the bare literal 'qwen3-5' -- an
    // unverified claim about which model actually runs the review.
    // Labeled through the same `referenceSeatModelName` convention every
    // other borrowed/unverified identity in the codebase uses.
    model: referenceSeatModelName('qwen3-5'),
    maxFiles: 50,
  };
}

// ---------------------------------------------------------------------------
// createUltrareviewCommand
// ---------------------------------------------------------------------------

type UltrareviewResult = { type: 'message'; message: string } | { type: 'none' };

async function checkAndHandleBillingGate(
  deps: UltrareviewDeps,
): Promise<{ proceed: false; result: UltrareviewResult } | { proceed: true; freeReviewInfo?: { remaining: number; total: number } }> {
  const gate = await deps.fetchBillingGate();

  if (gate.type === 'low-balance') {
    return {
      proceed: false,
      result: {
        type: 'message',
        message: `Your balance (${gate.balance}) is too low to run a review. Please add funds to continue.`,
      },
    };
  }

  if (gate.type === 'not-enabled') {
    return {
      proceed: false,
      result: {
        type: 'message',
        message: `Billing not enabled. Visit ${gate.settingsUrl} to configure billing.`,
      },
    };
  }

  if (gate.type === 'needs-confirm') {
    if (!deps.hasConfirmedOverage()) {
      const confirmed = await deps.renderOverageDialog();
      if (!confirmed) {
        return { proceed: false, result: { type: 'none' } };
      }
      deps.confirmOverage();
    }
    return { proceed: true };
  }

  // type === 'proceed'
  const freeReviewInfo =
    gate.reviewsRemaining != null && gate.totalReviews != null
      ? { remaining: gate.reviewsRemaining, total: gate.totalReviews }
      : undefined;

  return { proceed: true, freeReviewInfo };
}

export function createUltrareviewCommand(deps: UltrareviewDeps) {
  return {
    name: 'ultrareview',
    type: 'local-jsx',
    description: 'Run an AI-powered review on your code changes',

    isEnabled(): boolean {
      return deps.isBughunterEnabled();
    },

    async execute(args: string, _ctx: CommandContext): Promise<UltrareviewResult> {
      // Billing gate
      const gateResult = await checkAndHandleBillingGate(deps);
      if (!gateResult.proceed) {
        return gateResult.result;
      }
      const freeReviewInfo = gateResult.freeReviewInfo;

      const prArg = args.trim();
      const isPrMode = prArg !== '' && /^\d+$/.test(prArg);

      let launchOpts: Parameters<UltrareviewDeps['launchRemoteSession']>[0];

      if (isPrMode) {
        // PR review mode
        const repo = await deps.getCurrentRepository();
        if (repo === null) {
          return {
            type: 'message',
            message: 'This command requires a GitHub repository. Please run it inside a git repository connected to GitHub.',
          };
        }

        launchOpts = {
          prRef: `refs/pull/${prArg}/head`,
          env: {
            BUGHUNTER_PR_NUMBER: prArg,
            BUGHUNTER_REPOSITORY: repo,
            BUGHUNTER_DRY_RUN,
          },
        };
      } else {
        // Branch / working-tree mode
        const defaultBranch = await deps.getDefaultBranch();
        const mergeBase = await deps.computeMergeBase();

        if (mergeBase === null) {
          return {
            type: 'message',
            message: 'Could not determine merge base. Please ensure your branch has a common ancestor with the default branch.',
          };
        }

        const diff = await deps.getDiffBetween(mergeBase, 'HEAD');
        if (!diff) {
          return {
            type: 'message',
            message: 'No changes detected between your branch and the default branch. Nothing to review.',
          };
        }

        const bundle = await deps.bundleWorkingTree();
        if (bundle.tooLarge) {
          return {
            type: 'message',
            message: 'The working tree is too large to bundle for review. Try reviewing a subset of changes.',
          };
        }

        launchOpts = {
          useBundle: true,
          bundlePath: bundle.bundlePath,
          env: {
            BUGHUNTER_BASE_BRANCH: mergeBase,
            BUGHUNTER_DRY_RUN,
          },
        };

        void defaultBranch; // referenced but not needed in env directly
      }

      // Escape handling
      let escaped = false;
      const unsubscribe = deps.onEscape(() => {
        escaped = true;
      });

      let launchResult: UltrareviewLaunchResult | null = null;
      try {
        launchResult = await deps.launchRemoteSession(launchOpts);
      } finally {
        unsubscribe();
      }

      if (escaped) {
        return { type: 'none' };
      }

      if (launchResult === null) {
        return { type: 'message', message: 'Failed to launch review session.' };
      }

      deps.setShouldQuery(true);
      deps.emitAnalytics('ultrareview_launched', { sessionUrl: launchResult.sessionUrl });

      if (freeReviewInfo != null) {
        return {
          type: 'message',
          message: `Review started! This is free review ${freeReviewInfo.remaining} of ${freeReviewInfo.total}.`,
        };
      }

      return {
        type: 'message',
        message: `Review session started.`,
      };
    },
  };
}
