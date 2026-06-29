import { describe, expect, test } from 'bun:test';
import {
  modelSupportsISP,
  modelSupportsContextManagement,
  modelSupportsStructuredOutputs,
  getAllModelBetas,
  LOCAL_MODEL_ID,
} from './model-config';

describe('modelSupportsISP', () => {
  test('AC1: local model (qwen3.6) does not support ISP (cloud-only feature)', () => {
    expect(modelSupportsISP(LOCAL_MODEL_ID)).toBe(false);
  });

  test('AC2: unknown model returns false for ISP', () => {
    expect(modelSupportsISP('totally-unknown-model')).toBe(false);
  });

  test('short registry key "local" resolves correctly', () => {
    expect(modelSupportsISP('local')).toBe(false);
  });
});

describe('modelSupportsContextManagement', () => {
  test('local model does not support context management (cloud-only feature)', () => {
    expect(modelSupportsContextManagement(LOCAL_MODEL_ID)).toBe(false);
  });

  test('unknown model returns false', () => {
    expect(modelSupportsContextManagement('some-unknown')).toBe(false);
  });
});

describe('modelSupportsStructuredOutputs', () => {
  test('local model (qwen3.6) supports structured outputs via llama-server grammar', () => {
    expect(modelSupportsStructuredOutputs(LOCAL_MODEL_ID)).toBe(true);
  });

  test('unknown model returns false', () => {
    expect(modelSupportsStructuredOutputs('some-unknown')).toBe(false);
  });
});

describe('getAllModelBetas', () => {
  test('AC3: local model returns no betas (local server has no provider beta headers)', () => {
    const betas = getAllModelBetas(LOCAL_MODEL_ID, { ispEnabled: true });
    expect(betas).toEqual([]);
  });

  test('AC4: unknown model → empty array without throwing', () => {
    expect(getAllModelBetas('totally-unknown-model-xyz', {})).toEqual([]);
  });

  test('AC5: beta list is always empty for local model (deduplicated)', () => {
    const betas = getAllModelBetas(LOCAL_MODEL_ID, {
      ispEnabled: true,
      tokenEfficientTools: true,
      extendedContext: true,
    });
    expect(betas).toEqual([]);
    expect(betas.length).toBe(new Set(betas).size);
  });

  test('result is sorted lexicographically (deterministic order)', () => {
    const betas = getAllModelBetas(LOCAL_MODEL_ID, {
      ispEnabled: true,
      tokenEfficientTools: true,
      extendedContext: true,
    });
    const sorted = [...betas].sort();
    expect(betas).toEqual(sorted);
  });

  test('[1m] suffix is stripped before lookup', () => {
    const withSuffix = getAllModelBetas(`${LOCAL_MODEL_ID}[1m]`, { ispEnabled: true });
    const without = getAllModelBetas(LOCAL_MODEL_ID, { ispEnabled: true });
    expect(withSuffix).toEqual(without);
  });
});
