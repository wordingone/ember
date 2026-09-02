// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// voice-mode.ts — Voice-mode availability checks.
// Voice mode requires: (a) cloud auth with a valid access token, and
// (b) the VOICE_MODE feature flag enabled without the kill-switch active.

// ---------------------------------------------------------------------------
// Deps (injectable for testing)
// ---------------------------------------------------------------------------

interface VoiceDeps {
  isCloudAuthEnabled: () => boolean;
  getCachedAccessToken: () => string | null | undefined;
  getVoiceKillSwitch: () => boolean;
  isFeatureEnabled: (name: string) => boolean;
}

let voiceDeps: VoiceDeps = {
  isCloudAuthEnabled: () => false,
  getCachedAccessToken: () => null,
  getVoiceKillSwitch: () => false,
  isFeatureEnabled: () => false,
};

export function _setVoiceDeps(overrides: Partial<VoiceDeps>): void {
  voiceDeps = { ...voiceDeps, ...overrides };
}

// ---------------------------------------------------------------------------
// Checks (exported for use by UI and tests)
// ---------------------------------------------------------------------------

/** Returns true when the VOICE_MODE feature flag is enabled and the kill-switch is off. */
export function isVoiceFeatureFlagEnabled(): boolean {
  if (voiceDeps.getVoiceKillSwitch()) return false;
  return voiceDeps.isFeatureEnabled('VOICE_MODE');
}

/** Returns true when cloud auth is active and a non-empty access token is cached. */
export function hasVoiceAuth(): boolean {
  if (!voiceDeps.isCloudAuthEnabled()) return false;
  const token = voiceDeps.getCachedAccessToken();
  return typeof token === 'string' && token.length > 0;
}

/** Returns true only when BOTH the auth check and the feature-flag check pass. */
export function isVoiceModeEnabled(): boolean {
  return hasVoiceAuth() && isVoiceFeatureFlagEnabled();
}
