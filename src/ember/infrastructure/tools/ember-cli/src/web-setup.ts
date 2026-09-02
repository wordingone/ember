// web-setup.ts — /web-setup command for configuring web-based remote sessions.

import type { CommandContext } from './types/command-types.ts';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

export const EMBER_WEB_URL_LEGACY = 'https://ember.ai/code';
export const GH_TOKEN_TIMEOUT_MS = 5_000;
export const IMPORT_TOKEN_TIMEOUT_MS = 15_000;
export const IMPORT_TOKEN_BETA_HEADER = 'ccr-byoc-2025-07-29';

// ---------------------------------------------------------------------------
// RedactedGithubToken
// ---------------------------------------------------------------------------

export class RedactedGithubToken {
  readonly #value: string;

  constructor(value: string) {
    this.#value = value;
  }

  toString(): string {
    return '[REDACTED_GITHUB_TOKEN]';
  }

  toJSON(): string {
    return '[REDACTED_GITHUB_TOKEN]';
  }

  reveal(): string {
    return this.#value;
  }
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ImportTokenError {
  type: 'import-error';
  message: string;
}

export interface WebSetupDeps {
  isCobaltLanternEnabled: () => boolean;
  isPolicyAllowed: () => boolean;
  isSignedIn: () => boolean;
  getGhAuthToken: () => Promise<string>;
  importGithubToken: (token: string, header?: string) => Promise<void>;
  createDefaultEnvironment: () => Promise<void>;
  openBrowser: (url: string) => Promise<void>;
  logAnalyticsEvent: (event: string) => void;
  openLoginPage: () => Promise<void>;
}

// ---------------------------------------------------------------------------
// isWebSetupEnabled
// ---------------------------------------------------------------------------

export function isWebSetupEnabled(d: WebSetupDeps): boolean {
  return d.isCobaltLanternEnabled() && d.isPolicyAllowed();
}

// ---------------------------------------------------------------------------
// runWebSetup
// ---------------------------------------------------------------------------

type WebSetupResult = { type: 'message'; message: string };

export async function runWebSetup(d: WebSetupDeps): Promise<WebSetupResult> {
  if (!d.isSignedIn()) {
    await d.openLoginPage();
    return {
      type: 'message',
      message: 'Please sign in to use web setup. Opening the sign-in page now.',
    };
  }

  // Fetch GitHub CLI token
  let ghToken: string;
  try {
    ghToken = await d.getGhAuthToken();
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    if (msg.includes('not_installed')) {
      return {
        type: 'message',
        message:
          'GitHub CLI (gh) not installed. Please install gh from https://cli.github.com/ and run `gh auth login`, then try again.',
      };
    }
    return {
      type: 'message',
      message:
        'Unable to get GitHub authentication token. Please ensure the GitHub CLI is authenticated (`gh auth login`).',
    };
  }

  // Import the token
  await d.importGithubToken(ghToken, IMPORT_TOKEN_BETA_HEADER);

  // Create default environment (non-fatal)
  try {
    await d.createDefaultEnvironment();
  } catch {
    // Non-fatal: proceed
  }

  // Open the web app
  await d.openBrowser(EMBER_WEB_URL_LEGACY);

  d.logAnalyticsEvent('web_setup_completed');

  return {
    type: 'message',
    message: 'Web setup success! Opening Ember in your browser.',
  };
}

// ---------------------------------------------------------------------------
// Module-level mutable deps
// ---------------------------------------------------------------------------

const DEFAULT_DEPS: WebSetupDeps = {
  isCobaltLanternEnabled: () => false,
  isPolicyAllowed: () => false,
  isSignedIn: () => false,
  getGhAuthToken: async () => '',
  importGithubToken: async () => {},
  createDefaultEnvironment: async () => {},
  openBrowser: async () => {},
  logAnalyticsEvent: () => {},
  openLoginPage: async () => {},
};

let moduleDeps: WebSetupDeps = { ...DEFAULT_DEPS };

export function setWebSetupDeps(overrides: Partial<WebSetupDeps>): void {
  moduleDeps = { ...DEFAULT_DEPS, ...overrides };
}

export function _resetWebSetupDeps(): void {
  moduleDeps = { ...DEFAULT_DEPS };
}

// ---------------------------------------------------------------------------
// webSetupCommand
// ---------------------------------------------------------------------------

export const webSetupCommand = {
  name: 'web-setup',
  type: 'local-jsx',
  description: 'Configure Ember for web-based remote sessions',

  isEnabled(): boolean {
    return isWebSetupEnabled(moduleDeps);
  },

  async execute(_args: string, _ctx: CommandContext): Promise<WebSetupResult> {
    return runWebSetup(moduleDeps);
  },
};
