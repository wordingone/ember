// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// install-slack-app.ts — /install-slack-app slash command.

import type { CommandContext } from './types/command-types.ts';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

export const SLACK_MARKETPLACE_URL = 'https://ember.ai/slack';
export const ANALYTICS_EVENT = 'tengu_install_slack_app_clicked';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface InstallSlackAppDeps {
  logAnalyticsEvent: (event: string) => void;
  incrementSlackInstallCount: () => Promise<void>;
  openBrowser: (url: string) => Promise<boolean>;
}

// ---------------------------------------------------------------------------
// Module-level mutable deps
// ---------------------------------------------------------------------------

const DEFAULT_DEPS: InstallSlackAppDeps = {
  logAnalyticsEvent: () => {},
  incrementSlackInstallCount: async () => {},
  openBrowser: async () => false,
};

let moduleDeps: InstallSlackAppDeps = { ...DEFAULT_DEPS };

export function setInstallSlackAppDeps(overrides: Partial<InstallSlackAppDeps>): void {
  moduleDeps = { ...DEFAULT_DEPS, ...overrides };
}

export function _resetInstallSlackAppDeps(): void {
  moduleDeps = { ...DEFAULT_DEPS };
}

// ---------------------------------------------------------------------------
// runInstallSlackApp
// ---------------------------------------------------------------------------

type SlackResult = { type: 'message'; message: string };

export async function runInstallSlackApp(d: InstallSlackAppDeps): Promise<SlackResult> {
  d.logAnalyticsEvent(ANALYTICS_EVENT);
  const opened = await d.openBrowser(SLACK_MARKETPLACE_URL);
  await d.incrementSlackInstallCount();

  if (opened) {
    return {
      type: 'message',
      message: `Opening the Ember Slack app in your browser. You can also visit: ${SLACK_MARKETPLACE_URL}`,
    };
  }

  return {
    type: 'message',
    message: `Unable to open browser automatically. Please visit: ${SLACK_MARKETPLACE_URL}`,
  };
}

// ---------------------------------------------------------------------------
// installSlackAppCommand
// ---------------------------------------------------------------------------

export const installSlackAppCommand = {
  name: 'install-slack-app',
  type: 'local-jsx',
  description: 'Install the Ember Slack app to use Ember in Slack',
  availability: ['cloud'],

  isEnabled(): boolean {
    return true;
  },

  async execute(_args: string, _ctx: CommandContext): Promise<SlackResult> {
    return runInstallSlackApp(moduleDeps);
  },
};
