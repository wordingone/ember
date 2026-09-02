// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// chrome.ts — /chrome slash command for ember-in-chrome integration.

import type { CommandContext } from './types/command-types.ts';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

export const EMBER_IN_CHROME_MCP_SERVER_NAME = 'ember-in-chrome';
export const CHROME_DOCS_URL = 'https://ember.ai/docs/chrome';
export const CHROME_INSTALL_URL = 'https://ember.ai/chrome';
export const CHROME_PERMISSIONS_URL = 'https://clau.de/chrome/permissions';
export const CHROME_RECONNECT_URL = 'https://clau.de/chrome/reconnect';
export const CHROME_CONFIG_KEY = 'emberInChromeDefaultEnabled';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ChromePanelState {
  isWsl: boolean;
  isSubscriber: boolean;
  isExtensionInstalled: boolean;
  isChromeConnected: boolean;
  defaultEnabled: boolean;
}

export interface ChromePanelCallbacks {
  onReconnect: () => Promise<void>;
  onInstall: () => Promise<void>;
  onToggleDefault: () => void;
  onDone: () => void;
}

interface ChromeCommandDeps {
  isCloudSurface?: () => boolean;
  isInteractiveSession?: () => boolean;
  isWsl?: () => boolean;
  probeExtensionInstalled?: () => Promise<boolean>;
  getConfigValue?: (key: string) => boolean;
  setConfigValue?: (key: string, value: boolean) => void;
  isSubscriber?: () => boolean;
  isChromeConnected?: () => boolean;
  openUrl?: (url: string) => void;
  renderChromePanel?: (state: ChromePanelState, callbacks: ChromePanelCallbacks | null) => void;
}

// ---------------------------------------------------------------------------
// Module-level mutable deps
// ---------------------------------------------------------------------------

const DEFAULT_DEPS: Required<ChromeCommandDeps> = {
  isCloudSurface: () => false,
  isInteractiveSession: () => true,
  isWsl: () => false,
  probeExtensionInstalled: async () => false,
  getConfigValue: () => false,
  setConfigValue: () => {},
  isSubscriber: () => false,
  isChromeConnected: () => false,
  openUrl: () => {},
  renderChromePanel: () => {},
};

let deps: ChromeCommandDeps = { ...DEFAULT_DEPS };

export function setChromeCommandDeps(overrides: ChromeCommandDeps): void {
  deps = { ...DEFAULT_DEPS, ...overrides };
}

export function resetChromeCommandDeps(): void {
  deps = { ...DEFAULT_DEPS };
}

// ---------------------------------------------------------------------------
// collectChromeState
// ---------------------------------------------------------------------------

export async function collectChromeState(): Promise<ChromePanelState> {
  const isWsl = (deps.isWsl ?? DEFAULT_DEPS.isWsl)();
  const isExtensionInstalled = await (deps.probeExtensionInstalled ?? DEFAULT_DEPS.probeExtensionInstalled)();
  const isSubscriber = (deps.isSubscriber ?? DEFAULT_DEPS.isSubscriber)();
  const isChromeConnected = (deps.isChromeConnected ?? DEFAULT_DEPS.isChromeConnected)();
  const defaultEnabled = (deps.getConfigValue ?? DEFAULT_DEPS.getConfigValue)(CHROME_CONFIG_KEY);
  return { isWsl, isExtensionInstalled, isSubscriber, isChromeConnected, defaultEnabled };
}

// ---------------------------------------------------------------------------
// chromeCommand
// ---------------------------------------------------------------------------

type ExtendedCtx = CommandContext & { onDone?: () => void };

export const chromeCommand = {
  name: 'chrome',
  type: 'local-jsx',
  description: 'Connect or configure ember-in-chrome',
  availability: ['cloud'],

  isEnabled(): boolean {
    const isCloud = (deps.isCloudSurface ?? DEFAULT_DEPS.isCloudSurface)();
    const isInteractive = (deps.isInteractiveSession ?? DEFAULT_DEPS.isInteractiveSession)();
    return isCloud && isInteractive;
  },

  async execute(_args: string, ctx: CommandContext): Promise<void> {
    const extCtx = ctx as ExtendedCtx;
    const mutableState = await collectChromeState();

    const callbacks: ChromePanelCallbacks = {
      async onReconnect() {
        const installed = await (deps.probeExtensionInstalled ?? DEFAULT_DEPS.probeExtensionInstalled)();
        mutableState.isExtensionInstalled = installed;
      },
      async onInstall() {
        (deps.openUrl ?? DEFAULT_DEPS.openUrl)(CHROME_INSTALL_URL);
        mutableState.isExtensionInstalled = false;
      },
      onToggleDefault() {
        const current = (deps.getConfigValue ?? DEFAULT_DEPS.getConfigValue)(CHROME_CONFIG_KEY);
        (deps.setConfigValue ?? DEFAULT_DEPS.setConfigValue)(CHROME_CONFIG_KEY, !current);
      },
      onDone() {
        extCtx.onDone?.();
      },
    };

    (deps.renderChromePanel ?? DEFAULT_DEPS.renderChromePanel)(mutableState, callbacks);
  },
};
