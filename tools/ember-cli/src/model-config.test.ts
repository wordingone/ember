// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { describe, expect, test } from 'bun:test';
import {
  modelSupportsISP,
  modelSupportsContextManagement,
  modelSupportsStructuredOutputs,
  getAllModelBetas,
} from './model-config';

// Neutral test identifier -- no hardcoded fallback model-id literal
// (Fix #51 P1 repair (4): the old local-model constant was removed entirely).
const TEST_MODEL_ID = 'test-model-a';

describe('modelSupportsISP', () => {
  test('AC1: any given model id does not support ISP (cloud-only feature)', () => {
    expect(modelSupportsISP(TEST_MODEL_ID)).toBe(false);
  });

  test('AC2: unknown model returns false for ISP', () => {
    expect(modelSupportsISP('totally-unknown-model')).toBe(false);
  });

  test('short registry key "local" resolves correctly', () => {
    expect(modelSupportsISP('local')).toBe(false);
  });
});

describe('modelSupportsContextManagement', () => {
  test('any given model id does not support context management (cloud-only feature)', () => {
    expect(modelSupportsContextManagement(TEST_MODEL_ID)).toBe(false);
  });

  test('unknown model returns false', () => {
    expect(modelSupportsContextManagement('some-unknown')).toBe(false);
  });
});

describe('modelSupportsStructuredOutputs', () => {
  const SERVED = 'd'.repeat(64);

  test('no declaration defaults to false', () => {
    expect(modelSupportsStructuredOutputs(null, SERVED)).toBe(false);
    expect(modelSupportsStructuredOutputs(undefined, SERVED)).toBe(false);
  });

  test('a declaration without a bound modelConfigSha256 defaults to false', () => {
    expect(
      modelSupportsStructuredOutputs(
        { modelConfigSha256: null, structuredOutputs: true },
        SERVED,
      ),
    ).toBe(false);
  });

  test('a declaration matching the exact served modelConfigSha256 is honored', () => {
    expect(
      modelSupportsStructuredOutputs(
        { modelConfigSha256: SERVED, structuredOutputs: true },
        SERVED,
      ),
    ).toBe(true);
  });

  test('NEGATIVE: a fabricated/mismatched hash is denied even with structuredOutputs=true', () => {
    expect(
      modelSupportsStructuredOutputs(
        { modelConfigSha256: 'e'.repeat(64), structuredOutputs: true },
        SERVED,
      ),
    ).toBe(false);
  });

  test('NEGATIVE: a missing served hash denies capability regardless of declaration', () => {
    expect(
      modelSupportsStructuredOutputs(
        { modelConfigSha256: SERVED, structuredOutputs: true },
        null,
      ),
    ).toBe(false);
    expect(
      modelSupportsStructuredOutputs(
        { modelConfigSha256: SERVED, structuredOutputs: true },
        '',
      ),
    ).toBe(false);
  });

  test('a bound declaration with structuredOutputs=false stays false', () => {
    expect(
      modelSupportsStructuredOutputs(
        { modelConfigSha256: SERVED, structuredOutputs: false },
        SERVED,
      ),
    ).toBe(false);
  });
});

describe('getAllModelBetas', () => {
  test('AC3: any given model id returns no betas (local server has no provider beta headers)', () => {
    const betas = getAllModelBetas(TEST_MODEL_ID, { ispEnabled: true });
    expect(betas).toEqual([]);
  });

  test('AC4: unknown model → empty array without throwing', () => {
    expect(getAllModelBetas('totally-unknown-model-xyz', {})).toEqual([]);
  });

  test('AC5: beta list is always empty for any given model id (deduplicated)', () => {
    const betas = getAllModelBetas(TEST_MODEL_ID, {
      ispEnabled: true,
      tokenEfficientTools: true,
      extendedContext: true,
    });
    expect(betas).toEqual([]);
    expect(betas.length).toBe(new Set(betas).size);
  });

  test('result is sorted lexicographically (deterministic order)', () => {
    const betas = getAllModelBetas(TEST_MODEL_ID, {
      ispEnabled: true,
      tokenEfficientTools: true,
      extendedContext: true,
    });
    const sorted = [...betas].sort();
    expect(betas).toEqual(sorted);
  });

  test('[1m] suffix is stripped before lookup', () => {
    const withSuffix = getAllModelBetas(`${TEST_MODEL_ID}[1m]`, { ispEnabled: true });
    const without = getAllModelBetas(TEST_MODEL_ID, { ispEnabled: true });
    expect(withSuffix).toEqual(without);
  });
});
