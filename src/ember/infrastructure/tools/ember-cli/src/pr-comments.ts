// pr-comments.ts — /pr-comments slash command.
// For internal users: points to the marketplace plugin.
// For external users: emits an inline prompt that uses gh CLI to fetch and
// analyse PR comments without leaving the tool.

import type { CommandContext } from './types/command-types.ts';

// ---------------------------------------------------------------------------
// User-type gate (injectable for testing)
// ---------------------------------------------------------------------------

let isAntUserChecker: () => boolean = () => false;

export function setPrCommentsUserTypeChecker(checker: () => boolean): void {
  isAntUserChecker = checker;
}

export function _resetPrCommentsForTests(): void {
  isAntUserChecker = () => false;
}

// ---------------------------------------------------------------------------
// Messages
// ---------------------------------------------------------------------------

const ANT_INSTALL_MESSAGE =
  'To use PR comment analysis, run:\n' +
  '  /plugin install pr-comments@ember-marketplace\n\n' +
  'Once the plugin is installed it will handle PR comment fetching and summarisation inline.';

const INLINE_PROMPT_BASE =
  'Analyse the pull request comments for the current repository using the gh CLI.\n\n' +
  'Steps:\n' +
  '1. Run `gh pr view --json number,title,body` to get the current PR info.\n' +
  '2. Fetch issue-level comments:\n' +
  '   `gh api repos/{owner}/{repo}/issues/{number}/comments`\n' +
  '3. Fetch review-level (inline) comments:\n' +
  '   `gh api repos/{owner}/{repo}/pulls/{number}/comments`\n' +
  '   Each review comment exposes: diff_hunk, path, line, body, author.\n' +
  '4. Summarise all feedback grouped into:\n' +
  '   - Issue-level comments (general PR discussion)\n' +
  '   - Review-level comments (inline code feedback)\n' +
  '5. For each review comment reference the file path and line number.\n' +
  '6. Use gh api for all GitHub API calls — no direct HTTP clients.';

// ---------------------------------------------------------------------------
// Command
// ---------------------------------------------------------------------------

export const prCommentsCommand = {
  name: 'pr-comments',
  type: 'prompt' as const,
  pluginName: 'pr-comments',
  progressMessage: 'fetching PR comments',
  description: 'Fetch and analyse PR comments using the gh CLI',

  isEnabled(): boolean {
    return true;
  },

  async execute(args: string, _ctx: CommandContext) {
    if (isAntUserChecker()) {
      return { type: 'message' as const, message: ANT_INSTALL_MESSAGE };
    }

    const userInput = args.trim();
    let prompt = INLINE_PROMPT_BASE;

    if (userInput) {
      prompt += `\n\nAdditional user input: ${userInput}`;
    }

    return { type: 'message' as const, message: prompt };
  },
};
