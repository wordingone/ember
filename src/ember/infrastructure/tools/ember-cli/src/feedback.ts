// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// feedback.ts — /feedback slash command.
// Submits product feedback. Disabled on managed cloud platforms, for internal
// users, in essential-traffic mode, and when the relevant policy is denied.

import type { CommandContext } from './types/command-types.ts';

// ---------------------------------------------------------------------------
// Deps
// ---------------------------------------------------------------------------

export interface FeedbackCommandDeps {
  isManagedCloudPlatform: () => boolean;
  isEssentialTrafficOnly: () => boolean;
  isPolicyAllowed: (policy: string) => boolean;
  renderFeedbackComponent: (ctx: CommandContext, description: string) => Promise<void>;
}

// ---------------------------------------------------------------------------
// Eligibility check (exported for direct testing)
// ---------------------------------------------------------------------------

export function isFeedbackEnabled(deps: FeedbackCommandDeps): boolean {
  if (deps.isManagedCloudPlatform()) return false;
  if (process.env['USER_TYPE'] === 'ant') return false;
  if (deps.isEssentialTrafficOnly()) return false;
  if (!deps.isPolicyAllowed('allow_product_feedback')) return false;
  return true;
}

// ---------------------------------------------------------------------------
// Module-level deps (replaced via setFeedbackCommandDeps in tests / wiring)
// ---------------------------------------------------------------------------

const defaultDeps: FeedbackCommandDeps = {
  isManagedCloudPlatform: () => false,
  isEssentialTrafficOnly: () => false,
  isPolicyAllowed: () => true,
  renderFeedbackComponent: async () => {},
};

let currentDeps: FeedbackCommandDeps = { ...defaultDeps };

export function setFeedbackCommandDeps(deps: FeedbackCommandDeps): void {
  currentDeps = deps;
}

export function _resetFeedbackCommandDeps(): void {
  currentDeps = { ...defaultDeps };
}

// ---------------------------------------------------------------------------
// Command
// ---------------------------------------------------------------------------

export const feedbackCommand = {
  name: 'feedback',
  type: 'local-jsx' as const,
  aliases: ['bug'],
  description: 'Submit feedback about your experience',

  isEnabled(): boolean {
    // Always registered; actual availability gated at execute time.
    return true;
  },

  async execute(args: string, ctx: CommandContext) {
    if (!isFeedbackEnabled(currentDeps)) {
      return {
        type: 'message' as const,
        message: 'Feedback is not available in this environment.',
      };
    }

    await currentDeps.renderFeedbackComponent(ctx, args.trim());
    return { type: 'none' as const };
  },
};
