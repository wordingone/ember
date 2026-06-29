// commit-push-pr.ts — /commit-push-pr slash command.
// Builds a prompt that instructs the model to stage, commit, push, and open a
// PR, pre-seeded with the current git context gathered via shell commands.

import type { CommandContext } from './types/command-types.ts';

// ---------------------------------------------------------------------------
// Deps
// ---------------------------------------------------------------------------

interface CommitPushPrDeps {
  evalShell: (cmd: string) => Promise<string>;
  getDefaultBranch: () => Promise<string>;
  getExistingPrNumber: () => Promise<number | null>;
  isUndercoverMode: () => boolean;
  getPrAttributionBlock: () => string;
}

const defaultCommitPushPrDeps: CommitPushPrDeps = {
  evalShell: async () => '',
  getDefaultBranch: async () => 'main',
  getExistingPrNumber: async () => null,
  isUndercoverMode: () => false,
  getPrAttributionBlock: () => '',
};

let commitDeps: CommitPushPrDeps = { ...defaultCommitPushPrDeps };

export function setCommitPushPrCommandDeps(
  overrides: Partial<CommitPushPrDeps>,
): void {
  commitDeps = { ...commitDeps, ...overrides };
}

export function _resetCommitPushPrCommandDepsForTests(): void {
  commitDeps = { ...defaultCommitPushPrDeps };
}

// ---------------------------------------------------------------------------
// Prompt builder (exported for direct testing)
// ---------------------------------------------------------------------------

export async function buildCommitPushPrPrompt(
  args: string,
  _cwd: string,
): Promise<string> {
  const [status, diff, branch, defaultBranch, existingPr] = await Promise.all([
    commitDeps.evalShell('git status'),
    commitDeps.evalShell('git diff HEAD'),
    commitDeps.evalShell('git rev-parse --abbrev-ref HEAD'),
    commitDeps.getDefaultBranch(),
    commitDeps.getExistingPrNumber(),
  ]);

  const defaultBranchDiff = await commitDeps.evalShell(
    `git diff ${defaultBranch}...`,
  );

  const prLine =
    existingPr !== null ? `Existing PR: #${existingPr}` : 'Existing PR: No existing PR';

  const undercover = commitDeps.isUndercoverMode();

  // Base context section
  let prompt =
    `You will commit, push, and create or update a pull request.\n\n` +
    `## Git status\n${status}\n\n` +
    `## Git diff HEAD\n${diff}\n\n` +
    `## Current branch\n${branch}\n\n` +
    `## Diff from ${defaultBranch}\n${defaultBranchDiff}\n\n` +
    `## Pull request\n${prLine}\n\n`;

  // Steps section
  prompt +=
    `## Steps\n` +
    `1. Stage and commit all changes with a clear, descriptive commit message.\n` +
    `2. Push to origin/${branch}.\n` +
    `3. Create or update the pull request with a clear title and body.\n`;

  if (!undercover) {
    prompt +=
      `4. Add or update a changelog entry describing these changes.\n` +
      `5. Use ToolSearch to read EMBER.md and identify the relevant Slack channels.\n` +
      `6. Before posting to any Slack channel, ask for user confirmation.\n`;
  }

  // Attribution block (e.g. co-author trailer)
  const attribution = commitDeps.getPrAttributionBlock();
  if (attribution) {
    prompt += `\n## Commit trailer\n${attribution}\n`;
  }

  // User-supplied additional instructions
  const userArgs = args.trim();
  if (userArgs) {
    prompt += `\nAdditional instructions: ${userArgs}`;
  }

  return prompt;
}

// ---------------------------------------------------------------------------
// Command
// ---------------------------------------------------------------------------

export const commitPushPrCommand = {
  name: 'commit-push-pr',
  type: 'prompt' as const,
  progressMessage: 'creating commit and PR',
  description: 'Stage, commit, push, and open a pull request',

  isEnabled(): boolean {
    return true;
  },

  async execute(args: string, ctx: CommandContext) {
    const message = await buildCommitPushPrPrompt(args, ctx.cwd);
    return { type: 'message' as const, message };
  },
};
