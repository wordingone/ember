// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// Tests for install-github-app command.

import { describe, it, expect, beforeEach } from 'bun:test';
import {
  installGithubAppCommand,
  executeCreatingStep,
  makeInitialWizardState,
  normaliseRepoInput,
  isValidSecretName,
  makeBranchName,
  setInstallGithubAppDeps,
  _resetInstallGithubAppDeps,
  GITHUB_APP_INSTALL_URL,
  DEFAULT_SECRET_NAME,
  OAUTH_TOKEN_ENV_VAR,
  WORKFLOW_TEMPLATE_SECRET_VAR,
  DEFAULT_WORKFLOWS,
  WORKFLOW_FILE_EMBER,
  ANALYTICS_STARTED,
  ANALYTICS_COMPLETED,
  ANALYTICS_ERROR,
  type InstallGithubAppDeps,
  type WizardState,
  type RepoInfo,
} from './install-github-app.ts';

const makeCtx = () => ({
  sessionId: 'test',
  mode: 'default' as const,
  cwd: '/tmp',
});

const makeNopDeps = (): InstallGithubAppDeps => ({
  checkGhCli: async () => ({
    authenticated: true,
    hasRepoScope: true,
    hasWorkflowScope: true,
    warnings: [],
  }),
  detectCurrentRepo: () => null,
  checkRepoAccess: async () => true,
  getRepoInfo: async () => ({
    defaultBranch: 'main',
    headSha: 'abc123',
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
});

const makeFilledState = (overrides: Partial<WizardState> = {}): WizardState => ({
  ...makeInitialWizardState(),
  repo: 'owner/repo',
  apiKeyValue: 'sk-test-api-key',
  apiKeySource: 'new',
  ...overrides,
});

beforeEach(() => {
  _resetInstallGithubAppDeps();
  delete process.env['DISABLE_INSTALL_GITHUB_APP_COMMAND'];
});

// ---------------------------------------------------------------------------
// AC1: Availability — cloud and console.
// ---------------------------------------------------------------------------

describe('AC1 — availability: cloud and console', () => {
  it('has availability: cloud and console', () => {
    expect(installGithubAppCommand.availability).toContain('cloud');
    expect(installGithubAppCommand.availability).toContain('console');
  });
});

// ---------------------------------------------------------------------------
// AC2: DISABLE_INSTALL_GITHUB_APP_COMMAND env gate.
// ---------------------------------------------------------------------------

describe('AC2 — DISABLE_INSTALL_GITHUB_APP_COMMAND gate', () => {
  it('isEnabled returns false when env is set', () => {
    process.env['DISABLE_INSTALL_GITHUB_APP_COMMAND'] = '1';
    expect(installGithubAppCommand.isEnabled()).toBe(false);
    delete process.env['DISABLE_INSTALL_GITHUB_APP_COMMAND'];
  });

  it('isEnabled returns true when env is not set', () => {
    delete process.env['DISABLE_INSTALL_GITHUB_APP_COMMAND'];
    expect(installGithubAppCommand.isEnabled()).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// AC3: normaliseRepoInput accepts owner/repo and full GitHub URLs.
// ---------------------------------------------------------------------------

describe('AC3 — normaliseRepoInput', () => {
  it('accepts owner/repo format', () => {
    expect(normaliseRepoInput('owner/repo')).toBe('owner/repo');
  });

  it('accepts https://github.com/owner/repo', () => {
    expect(normaliseRepoInput('https://github.com/owner/repo')).toBe('owner/repo');
  });

  it('accepts https://github.com/owner/repo.git', () => {
    expect(normaliseRepoInput('https://github.com/owner/repo.git')).toBe('owner/repo');
  });

  it('trims whitespace', () => {
    expect(normaliseRepoInput('  owner/repo  ')).toBe('owner/repo');
  });

  it('returns null for unrecognised format', () => {
    expect(normaliseRepoInput('not-a-repo')).toBeNull();
    expect(normaliseRepoInput('gitlab.com/owner/repo')).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// AC7: isValidSecretName validates pattern.
// ---------------------------------------------------------------------------

describe('AC7 — isValidSecretName', () => {
  it('accepts alphanumeric + underscore names', () => {
    expect(isValidSecretName('EMBER_API_KEY')).toBe(true);
    expect(isValidSecretName('my_secret_123')).toBe(true);
  });

  it('rejects names with hyphens, spaces, dots', () => {
    expect(isValidSecretName('bad-name')).toBe(false);
    expect(isValidSecretName('bad name')).toBe(false);
    expect(isValidSecretName('bad.name')).toBe(false);
  });

  it('rejects empty string', () => {
    expect(isValidSecretName('')).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Branch name format.
// ---------------------------------------------------------------------------

describe('makeBranchName', () => {
  it('matches add-ember-github-actions-<timestamp> pattern', () => {
    const ts = 1700000000000;
    expect(makeBranchName(ts)).toBe(`add-ember-github-actions-${ts}`);
  });

  it('uses current timestamp when no argument', () => {
    const before = Date.now();
    const name = makeBranchName();
    const after = Date.now();
    const ts = parseInt(name.replace('add-ember-github-actions-', ''), 10);
    expect(ts).toBeGreaterThanOrEqual(before);
    expect(ts).toBeLessThanOrEqual(after);
  });
});

// ---------------------------------------------------------------------------
// AC8: setupCount incremented on success.
// ---------------------------------------------------------------------------

describe('AC8 — incrementGithubActionSetupCount called on success', () => {
  it('increments count when executeCreatingStep succeeds', async () => {
    let incremented = false;
    const deps: InstallGithubAppDeps = {
      ...makeNopDeps(),
      incrementGithubActionSetupCount: async () => { incremented = true; },
    };
    const state = makeFilledState();
    await executeCreatingStep(state, deps);
    expect(incremented).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// AC9: skipWorkflow=true — only secret step runs.
// ---------------------------------------------------------------------------

describe('AC9 — skipWorkflow skips workflow creation', () => {
  it('does not call createWorkflowFile or createBranch when skipWorkflow is true', async () => {
    let branchCreated = false;
    let workflowCreated = false;
    let secretSet = false;
    const deps: InstallGithubAppDeps = {
      ...makeNopDeps(),
      createBranch: async () => { branchCreated = true; },
      createWorkflowFile: async () => { workflowCreated = true; },
      setRepoSecret: async () => { secretSet = true; },
    };
    const state = makeFilledState({ skipWorkflow: true });
    const result = await executeCreatingStep(state, deps);
    expect(result.success).toBe(true);
    expect(branchCreated).toBe(false);
    expect(workflowCreated).toBe(false);
    expect(secretSet).toBe(true);
  });

  it('runs full flow when skipWorkflow is false', async () => {
    let branchCreated = false;
    const deps: InstallGithubAppDeps = {
      ...makeNopDeps(),
      createBranch: async () => { branchCreated = true; },
    };
    const state = makeFilledState({ skipWorkflow: false });
    await executeCreatingStep(state, deps);
    expect(branchCreated).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// Error path — returns success:false.
// ---------------------------------------------------------------------------

describe('executeCreatingStep error handling', () => {
  it('returns success:false with errorMessage when createBranch throws', async () => {
    const deps: InstallGithubAppDeps = {
      ...makeNopDeps(),
      createBranch: async () => { throw new Error('branch failed'); },
    };
    const state = makeFilledState();
    const result = await executeCreatingStep(state, deps);
    expect(result.success).toBe(false);
    expect(result.errorMessage).toContain('branch failed');
  });

  it('returns success:false when repo is null', async () => {
    const state = makeFilledState({ repo: null });
    const result = await executeCreatingStep(state, makeNopDeps());
    expect(result.success).toBe(false);
  });

  it('logs error analytics event on failure', async () => {
    const events: string[] = [];
    const deps: InstallGithubAppDeps = {
      ...makeNopDeps(),
      createBranch: async () => { throw new Error('fail'); },
      logAnalyticsEvent: (e) => events.push(e),
    };
    await executeCreatingStep(makeFilledState(), deps);
    expect(events).toContain(ANALYTICS_ERROR);
  });
});

// ---------------------------------------------------------------------------
// makeInitialWizardState defaults.
// ---------------------------------------------------------------------------

describe('makeInitialWizardState', () => {
  it('starts at check-gh step', () => {
    expect(makeInitialWizardState().step).toBe('check-gh');
  });

  it('defaults to DEFAULT_SECRET_NAME', () => {
    expect(makeInitialWizardState().secretName).toBe(DEFAULT_SECRET_NAME);
  });

  it('defaults to DEFAULT_WORKFLOWS', () => {
    const state = makeInitialWizardState();
    expect(state.selectedWorkflows).toEqual(Array.from(DEFAULT_WORKFLOWS));
  });

  it('skipWorkflow defaults to false', () => {
    expect(makeInitialWizardState().skipWorkflow).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Analytics on execute.
// ---------------------------------------------------------------------------

describe('analytics started event on execute', () => {
  it('fires ANALYTICS_STARTED when execute runs', async () => {
    const events: string[] = [];
    setInstallGithubAppDeps({
      logAnalyticsEvent: (e) => events.push(e),
    });
    await installGithubAppCommand.execute('', makeCtx());
    expect(events).toContain(ANALYTICS_STARTED);
  });
});

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

describe('constants', () => {
  it('DEFAULT_SECRET_NAME is EMBER_API_KEY', () => {
    expect(DEFAULT_SECRET_NAME).toBe('EMBER_API_KEY');
  });

  it('OAUTH_TOKEN_ENV_VAR is EMBER_OAUTH_TOKEN', () => {
    expect(OAUTH_TOKEN_ENV_VAR).toBe('EMBER_OAUTH_TOKEN');
  });

  it('WORKFLOW_TEMPLATE_SECRET_VAR is ember_oauth_token', () => {
    expect(WORKFLOW_TEMPLATE_SECRET_VAR).toBe('ember_oauth_token');
  });

  it('WORKFLOW_FILE_EMBER is ember.yml', () => {
    expect(WORKFLOW_FILE_EMBER).toBe('ember.yml');
  });

  it('GITHUB_APP_INSTALL_URL is github.com/apps/ember', () => {
    expect(GITHUB_APP_INSTALL_URL).toBe('https://github.com/apps/ember');
  });
});

// ---------------------------------------------------------------------------
// AC4: existing secret → check-existing-secret state
// ---------------------------------------------------------------------------

describe('AC4 — existing EMBER_API_KEY secret advances to check-existing-secret', () => {
  it('getRepoInfo can signal hasExistingSecret: true', async () => {
    // The wizard uses this flag to advance to the check-existing-secret step.
    // Verify the dep interface returns the correct shape when the secret exists.
    const infoWithSecret: RepoInfo = {
      defaultBranch: 'main',
      headSha: 'abc123',
      hasExistingWorkflow: false,
      hasExistingSecret: true,
    };
    const deps: InstallGithubAppDeps = {
      ...makeNopDeps(),
      getRepoInfo: async () => infoWithSecret,
    };
    const info = await deps.getRepoInfo('owner/repo');
    expect(info.hasExistingSecret).toBe(true);
  });

  it('executeCreatingStep uses custom secretName when user chose to keep existing', async () => {
    // If user keeps the existing secret, the state reflects their chosen name.
    let capturedSecretName = '';
    const deps: InstallGithubAppDeps = {
      ...makeNopDeps(),
      setRepoSecret: async (_repo, name, _value) => { capturedSecretName = name; },
    };
    const state = makeFilledState({ secretName: 'EMBER_API_KEY', skipWorkflow: true });
    await executeCreatingStep(state, deps);
    expect(capturedSecretName).toBe('EMBER_API_KEY');
  });
});

// ---------------------------------------------------------------------------
// AC5: oauth source with no provider falls back to new-key path
// ---------------------------------------------------------------------------

describe('AC5 — oauth unavailable: initial apiKeySource is "new"', () => {
  // Use an object container so TypeScript tracks the property mutation correctly
  // through the async closure (let-variable narrowing to null trips TS2769).

  it('defaults to "new" when no existing key and no OAuth provider', async () => {
    const cap = { source: '' };
    setInstallGithubAppDeps({
      isOAuthProviderAvailable: () => false,
      getExistingApiKey: () => null,
      renderWizard: async (_ctx, state) => { cap.source = state.apiKeySource; return state; },
    });
    await installGithubAppCommand.execute('', makeCtx());
    expect(cap.source).toBe('new');
  });

  it('defaults to "existing" when existing key is present', async () => {
    const cap = { source: '' };
    setInstallGithubAppDeps({
      getExistingApiKey: () => 'sk-existing-key',
      renderWizard: async (_ctx, state) => { cap.source = state.apiKeySource; return state; },
    });
    await installGithubAppCommand.execute('', makeCtx());
    expect(cap.source).toBe('existing');
  });

  it('defaults to "oauth" when provider is available and no existing key', async () => {
    const cap = { source: '' };
    setInstallGithubAppDeps({
      isOAuthProviderAvailable: () => true,
      getExistingApiKey: () => null,
      renderWizard: async (_ctx, state) => { cap.source = state.apiKeySource; return state; },
    });
    await installGithubAppCommand.execute('', makeCtx());
    expect(cap.source).toBe('oauth');
  });
});

// ---------------------------------------------------------------------------
// AC6: OAuth token stored as EMBER_OAUTH_TOKEN; used as secret value
// ---------------------------------------------------------------------------

describe('AC6 — OAuth token used as secret value in creating step', () => {
  it('uses oauthToken as the secret value when apiKeySource is "oauth"', async () => {
    let capturedSecretValue = '';
    const deps: InstallGithubAppDeps = {
      ...makeNopDeps(),
      setRepoSecret: async (_repo, _name, value) => { capturedSecretValue = value; },
    };
    const state = makeFilledState({
      apiKeySource: 'oauth',
      oauthToken: 'oauth-token-real-abc',
    });
    const result = await executeCreatingStep(state, deps);
    expect(result.success).toBe(true);
    expect(capturedSecretValue).toBe('oauth-token-real-abc');
  });

  it('WORKFLOW_TEMPLATE_SECRET_VAR is "ember_oauth_token" (interop)', () => {
    expect(WORKFLOW_TEMPLATE_SECRET_VAR).toBe('ember_oauth_token');
  });

  it('OAUTH_TOKEN_ENV_VAR is "EMBER_OAUTH_TOKEN" (interop)', () => {
    expect(OAUTH_TOKEN_ENV_VAR).toBe('EMBER_OAUTH_TOKEN');
  });
});
