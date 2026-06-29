// upgrade.ts — /upgrade slash command.
// Opens the upgrade flow so the user can move to a higher subscription tier.
// Available on cloud surface only; blocked for enterprise accounts and when the
// DISABLE_UPGRADE_COMMAND env var is set.

import type { CommandContext } from './types/command-types.ts';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

export const UPGRADE_URL = 'https://ember.ai/upgrade/max';
export const MAX_20X_RATE_LIMIT_TIER = 'default_cloud_max_20x';

// ---------------------------------------------------------------------------
// Deps
// ---------------------------------------------------------------------------

export interface UpgradeCommandDeps {
  isCloudSurface: () => boolean;
  isEnterpriseSubscription: () => boolean;
  getOAuthTokenInfo: () => { subscriptionType: string; rateLimitTier: string } | null;
  getOAuthProfileFromToken: () => Promise<{
    organization_type: string;
    rate_limit_tier: string;
  } | null>;
  openBrowser: (url: string) => Promise<boolean>;
  renderLoginComponent: () => Promise<boolean>;
  onChangeAPIKey: () => void;
}

const defaultDeps: UpgradeCommandDeps = {
  isCloudSurface: () => false,
  isEnterpriseSubscription: () => false,
  getOAuthTokenInfo: () => null,
  getOAuthProfileFromToken: async () => null,
  openBrowser: async () => false,
  renderLoginComponent: async () => false,
  onChangeAPIKey: () => {},
};

let currentDeps: UpgradeCommandDeps = { ...defaultDeps };

export function setUpgradeCommandDeps(overrides: Partial<UpgradeCommandDeps>): void {
  currentDeps = { ...currentDeps, ...overrides };
}

export function _resetUpgradeCommandDeps(): void {
  currentDeps = { ...defaultDeps };
}

// ---------------------------------------------------------------------------
// Eligibility helpers (exported for direct testing)
// ---------------------------------------------------------------------------

export function isUpgradeEnabled(deps: UpgradeCommandDeps): boolean {
  if (!deps.isCloudSurface()) return false;
  if (process.env['DISABLE_UPGRADE_COMMAND']) return false;
  if (deps.isEnterpriseSubscription()) return false;
  return true;
}

export async function isAlreadyOnMax20x(deps: UpgradeCommandDeps): Promise<boolean> {
  const tokenInfo = deps.getOAuthTokenInfo();

  if (tokenInfo !== null) {
    return (
      tokenInfo.subscriptionType === 'max' &&
      tokenInfo.rateLimitTier === MAX_20X_RATE_LIMIT_TIER
    );
  }

  // Fall back to profile API call
  const profile = await deps.getOAuthProfileFromToken();
  if (!profile) return false;

  return (
    profile.organization_type === 'cloud_max' &&
    profile.rate_limit_tier === MAX_20X_RATE_LIMIT_TIER
  );
}

// ---------------------------------------------------------------------------
// Command
// ---------------------------------------------------------------------------

export const upgradeCommand = {
  name: 'upgrade',
  type: 'local-jsx' as const,
  availability: ['cloud'] as string[],
  description: 'Upgrade your subscription to Max',

  isEnabled(): boolean {
    return isUpgradeEnabled(currentDeps);
  },

  async execute(_args: string, _ctx: CommandContext) {
    if (await isAlreadyOnMax20x(currentDeps)) {
      return {
        type: 'message' as const,
        message: 'You already have Max — no upgrade needed.',
      };
    }

    try {
      await currentDeps.openBrowser(UPGRADE_URL);
    } catch {
      return {
        type: 'message' as const,
        message: `Could not open browser automatically. Visit: ${UPGRADE_URL}`,
      };
    }

    const loggedIn = await currentDeps.renderLoginComponent();
    if (loggedIn) {
      currentDeps.onChangeAPIKey();
    }

    return { type: 'none' as const };
  },
};
