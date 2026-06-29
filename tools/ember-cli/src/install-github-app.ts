// install-github-app.ts — /install-github-app slash command.

import type { CommandContext } from './types/command-types.ts';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

export const GITHUB_APP_INSTALL_URL = 'https://github.com/apps/ember';
export const DEFAULT_SECRET_NAME = 'EMBER_API_KEY';
export const OAUTH_TOKEN_ENV_VAR = 'EMBER_OAUTH_TOKEN';
export const WORKFLOW_TEMPLATE_SECRET_VAR = 'ember_oauth_token';
export const WORKFLOW_FILE_EMBER = 'ember.yml';
export const DEFAULT_WORKFLOWS: Set<string> = new Set([WORKFLOW_FILE_EMBER]);

export const ANALYTICS_STARTED = 'tengu_github_setup_started';
export const ANALYTICS_COMPLETED = 'tengu_github_setup_completed';
export const ANALYTICS_ERROR = 'tengu_github_setup_error';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface RepoInfo {
  defaultBranch: string;
  headSha: string;
  hasExistingWorkflow: boolean;
  hasExistingSecret: boolean;
}

export interface WizardState {
  step: string;
  repo: string | null;
  apiKeyValue: string | null;
  apiKeySource: 'new' | 'existing' | 'oauth';
  oauthToken: string | null;
  secretName: string;
  selectedWorkflows: string[];
  skipWorkflow: boolean;
}

export interface InstallGithubAppDeps {
  checkGhCli: () => Promise<{
    authenticated: boolean;
    hasRepoScope: boolean;
    hasWorkflowScope: boolean;
    warnings: string[];
  }>;
  detectCurrentRepo: () => string | null;
  checkRepoAccess: (repo: string) => Promise<boolean>;
  getRepoInfo: (repo: string) => Promise<RepoInfo>;
  createBranch: (repo: string, branchName: string, sha: string) => Promise<void>;
  createWorkflowFile: (repo: string, branch: string, fileName: string, content: string) => Promise<void>;
  setRepoSecret: (repo: string, name: string, value: string) => Promise<void>;
  isOAuthProviderAvailable: () => boolean;
  getExistingApiKey: () => string | null;
  runOAuthFlow: () => Promise<{ success: boolean }>;
  openBrowser: (url: string) => Promise<void>;
  incrementGithubActionSetupCount: () => Promise<void>;
  logAnalyticsEvent: (event: string) => void;
  renderWizard: (ctx: CommandContext, state: WizardState) => Promise<WizardState>;
}

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------

export function makeInitialWizardState(): WizardState {
  return {
    step: 'check-gh',
    repo: null,
    apiKeyValue: null,
    apiKeySource: 'new',
    oauthToken: null,
    secretName: DEFAULT_SECRET_NAME,
    selectedWorkflows: Array.from(DEFAULT_WORKFLOWS),
    skipWorkflow: false,
  };
}

export function normaliseRepoInput(input: string): string | null {
  const trimmed = input.trim();
  // Match owner/repo directly
  if (/^[a-zA-Z0-9_.-]+\/[a-zA-Z0-9_.-]+$/.test(trimmed)) {
    return trimmed;
  }
  // Match https://github.com/owner/repo(.git)?
  const m = trimmed.match(/^https:\/\/github\.com\/([a-zA-Z0-9_.-]+\/[a-zA-Z0-9_.-]+?)(?:\.git)?$/);
  if (m?.[1]) {
    return m[1];
  }
  return null;
}

export function isValidSecretName(name: string): boolean {
  return /^[a-zA-Z0-9_]+$/.test(name) && name.length > 0;
}

export function makeBranchName(ts?: number): string {
  const timestamp = ts ?? Date.now();
  return `add-ember-github-actions-${timestamp}`;
}

// ---------------------------------------------------------------------------
// executeCreatingStep
// ---------------------------------------------------------------------------

export async function executeCreatingStep(
  state: WizardState,
  d: InstallGithubAppDeps,
): Promise<{ success: boolean; errorMessage?: string }> {
  if (state.repo === null) {
    return { success: false, errorMessage: 'No repository selected.' };
  }

  try {
    if (!state.skipWorkflow) {
      const branchName = makeBranchName();
      await d.createBranch(state.repo, branchName, 'HEAD');
      await d.createWorkflowFile(state.repo, branchName, WORKFLOW_FILE_EMBER, '');
    }

    const secretValue =
      state.apiKeySource === 'oauth'
        ? (state.oauthToken ?? '')
        : (state.apiKeyValue ?? '');
    await d.setRepoSecret(state.repo, state.secretName, secretValue);
    await d.incrementGithubActionSetupCount();
    d.logAnalyticsEvent(ANALYTICS_COMPLETED);
    return { success: true };
  } catch (err) {
    d.logAnalyticsEvent(ANALYTICS_ERROR);
    const msg = err instanceof Error ? err.message : String(err);
    return { success: false, errorMessage: msg };
  }
}

// ---------------------------------------------------------------------------
// Module-level mutable deps
// ---------------------------------------------------------------------------

const DEFAULT_DEPS: InstallGithubAppDeps = {
  checkGhCli: async () => ({
    authenticated: false,
    hasRepoScope: false,
    hasWorkflowScope: false,
    warnings: [],
  }),
  detectCurrentRepo: () => null,
  checkRepoAccess: async () => false,
  getRepoInfo: async () => ({
    defaultBranch: 'main',
    headSha: '',
    hasExistingWorkflow: false,
    hasExistingSecret: false,
  }),
  createBranch: async () => {},
  createWorkflowFile: async () => {},
  setRepoSecret: async () => {},
  isOAuthProviderAvailable: () => false,
  getExistingApiKey: () => null,
  runOAuthFlow: async () => ({ success: false }),
  openBrowser: async () => {},
  incrementGithubActionSetupCount: async () => {},
  logAnalyticsEvent: () => {},
  renderWizard: async (_ctx, state) => state,
};

let moduleDeps: InstallGithubAppDeps = { ...DEFAULT_DEPS };

export function setInstallGithubAppDeps(overrides: Partial<InstallGithubAppDeps>): void {
  moduleDeps = { ...DEFAULT_DEPS, ...overrides };
}

export function _resetInstallGithubAppDeps(): void {
  moduleDeps = { ...DEFAULT_DEPS };
}

// ---------------------------------------------------------------------------
// installGithubAppCommand
// ---------------------------------------------------------------------------

export const installGithubAppCommand = {
  name: 'install-github-app',
  type: 'local-jsx',
  description: 'Install the Ember GitHub App to automate code review workflows',
  availability: ['cloud', 'console'],

  isEnabled(): boolean {
    return !process.env['DISABLE_INSTALL_GITHUB_APP_COMMAND'];
  },

  async execute(_args: string, ctx: CommandContext): Promise<void> {
    const d = moduleDeps;

    d.logAnalyticsEvent(ANALYTICS_STARTED);

    const existingKey = d.getExistingApiKey();
    const oauthAvailable = d.isOAuthProviderAvailable();

    let apiKeySource: WizardState['apiKeySource'];
    if (existingKey !== null) {
      apiKeySource = 'existing';
    } else if (oauthAvailable) {
      apiKeySource = 'oauth';
    } else {
      apiKeySource = 'new';
    }

    const initialState: WizardState = {
      ...makeInitialWizardState(),
      repo: d.detectCurrentRepo(),
      apiKeyValue: existingKey,
      apiKeySource,
    };

    await d.renderWizard(ctx, initialState);
  },
};
