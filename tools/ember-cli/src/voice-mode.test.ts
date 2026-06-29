import { describe, it, expect, beforeEach } from 'bun:test';
import {
  hasVoiceAuth,
  isVoiceFeatureFlagEnabled,
  isVoiceModeEnabled,
  _setVoiceDeps,
} from './voice-mode.ts';

// Reset to all-disabled state before each test
beforeEach(() => {
  _setVoiceDeps({
    isCloudAuthEnabled: () => false,
    getCachedAccessToken: () => null,
    getVoiceKillSwitch: () => false,
    isFeatureEnabled: () => false,
  });
});

describe('AC1: VOICE_MODE compile flag absent', () => {
  it('isVoiceFeatureFlagEnabled returns false', () => {
    _setVoiceDeps({ isFeatureEnabled: () => false });
    expect(isVoiceFeatureFlagEnabled()).toBe(false);
  });

  it('isVoiceModeEnabled returns false regardless of auth or GrowthBook state', () => {
    _setVoiceDeps({
      isFeatureEnabled: () => false,
      isCloudAuthEnabled: () => true,
      getCachedAccessToken: () => 'valid-token',
      getVoiceKillSwitch: () => false,
    });
    expect(isVoiceModeEnabled()).toBe(false);
  });
});

describe('AC2: VOICE_MODE present, no kill-switch', () => {
  it('isVoiceFeatureFlagEnabled returns true', () => {
    _setVoiceDeps({
      isFeatureEnabled: (n) => n === 'VOICE_MODE',
      getVoiceKillSwitch: () => false,
    });
    expect(isVoiceFeatureFlagEnabled()).toBe(true);
  });

  it('VOICE_MODE check is name-specific', () => {
    _setVoiceDeps({
      isFeatureEnabled: (n) => n === 'VOICE_MODE',
      getVoiceKillSwitch: () => false,
    });
    // Only VOICE_MODE triggers it
    expect(isVoiceFeatureFlagEnabled()).toBe(true);
  });
});

describe('AC3: GrowthBook kill-switch active', () => {
  it('isVoiceFeatureFlagEnabled returns false when kill-switch true', () => {
    _setVoiceDeps({
      isFeatureEnabled: (n) => n === 'VOICE_MODE',
      getVoiceKillSwitch: () => true,
    });
    expect(isVoiceFeatureFlagEnabled()).toBe(false);
  });

  it('kill-switch overrides VOICE_MODE flag', () => {
    _setVoiceDeps({
      isFeatureEnabled: () => true,
      getVoiceKillSwitch: () => true,
    });
    expect(isVoiceFeatureFlagEnabled()).toBe(false);
  });
});

describe('AC4: non-cloud auth → hasVoiceAuth false', () => {
  it('returns false when isCloudAuthEnabled is false regardless of token', () => {
    _setVoiceDeps({
      isCloudAuthEnabled: () => false,
      getCachedAccessToken: () => 'some-token',
    });
    expect(hasVoiceAuth()).toBe(false);
  });

  it('returns false even with multiple tokens when auth disabled', () => {
    _setVoiceDeps({
      isCloudAuthEnabled: () => false,
      getCachedAccessToken: () => 'very-long-valid-token-string',
    });
    expect(hasVoiceAuth()).toBe(false);
  });
});

describe('AC5: cloud auth + access_token presence', () => {
  it('returns true when cloud auth enabled and token is non-empty', () => {
    _setVoiceDeps({
      isCloudAuthEnabled: () => true,
      getCachedAccessToken: () => 'valid-access-token',
    });
    expect(hasVoiceAuth()).toBe(true);
  });

  it('returns false when token is null', () => {
    _setVoiceDeps({
      isCloudAuthEnabled: () => true,
      getCachedAccessToken: () => null,
    });
    expect(hasVoiceAuth()).toBe(false);
  });

  it('returns false when token is undefined', () => {
    _setVoiceDeps({
      isCloudAuthEnabled: () => true,
      getCachedAccessToken: () => undefined,
    });
    expect(hasVoiceAuth()).toBe(false);
  });

  it('returns false when token is empty string', () => {
    _setVoiceDeps({
      isCloudAuthEnabled: () => true,
      getCachedAccessToken: () => '',
    });
    expect(hasVoiceAuth()).toBe(false);
  });
});

describe('AC6: isVoiceModeEnabled — combined check', () => {
  it('returns true only when both auth and GrowthBook conditions hold', () => {
    _setVoiceDeps({
      isCloudAuthEnabled: () => true,
      getCachedAccessToken: () => 'token',
      isFeatureEnabled: (n) => n === 'VOICE_MODE',
      getVoiceKillSwitch: () => false,
    });
    expect(isVoiceModeEnabled()).toBe(true);
  });

  it('returns false when auth fails but GrowthBook ok', () => {
    _setVoiceDeps({
      isCloudAuthEnabled: () => false,
      getCachedAccessToken: () => 'token',
      isFeatureEnabled: (n) => n === 'VOICE_MODE',
      getVoiceKillSwitch: () => false,
    });
    expect(isVoiceModeEnabled()).toBe(false);
  });

  it('returns false when GrowthBook fails but auth ok', () => {
    _setVoiceDeps({
      isCloudAuthEnabled: () => true,
      getCachedAccessToken: () => 'token',
      isFeatureEnabled: () => false,
      getVoiceKillSwitch: () => false,
    });
    expect(isVoiceModeEnabled()).toBe(false);
  });

  it('returns false when kill-switch active even if auth ok', () => {
    _setVoiceDeps({
      isCloudAuthEnabled: () => true,
      getCachedAccessToken: () => 'token',
      isFeatureEnabled: (n) => n === 'VOICE_MODE',
      getVoiceKillSwitch: () => true,
    });
    expect(isVoiceModeEnabled()).toBe(false);
  });

  it('returns false when all conditions fail', () => {
    _setVoiceDeps({
      isCloudAuthEnabled: () => false,
      getCachedAccessToken: () => null,
      isFeatureEnabled: () => false,
      getVoiceKillSwitch: () => true,
    });
    expect(isVoiceModeEnabled()).toBe(false);
  });
});
