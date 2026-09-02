import { describe, expect, test, beforeEach, afterEach } from 'bun:test';
import { join } from 'path';
import { mkdir, rm } from 'fs/promises';
import { tmpdir } from 'os';
import { _resetGlobalConfigCache } from '../utils/config-persistence';
import { _resetConfigHomeMemo } from '../utils/env-detection';
import {
  getStoredSessionCosts,
  restoreCostStateForSession,
  saveCurrentSessionCosts,
  addToTotalSessionCost,
  formatCost,
  formatTotalCost,
  canonicalModelName,
  _setDefaultStateForTest,
  type SessionCostState,
  type PerModelUsage,
  type UsageRecord,
} from './cost-telemetry';

// ---------------------------------------------------------------------------
// Test state factory — injectable SessionCostState
// ---------------------------------------------------------------------------

function makeTestState(sessionId = 'test-session-1'): SessionCostState & {
  otelEvents: Array<{ event: string; value?: number; model?: string }>;
  perModel: Record<string, PerModelUsage>;
} {
  let totalCost = 0;
  const perModel: Record<string, PerModelUsage> = {};
  const otelEvents: Array<{ event: string; value?: number; model?: string }> = [];

  const state: SessionCostState = {
    addToTotalCostState(cost: number, usage: UsageRecord, model: string) {
      totalCost += cost;
      if (!perModel[model]) {
        perModel[model] = {
          inputTokens: 0, outputTokens: 0, cacheReadInputTokens: 0,
          cacheCreationInputTokens: 0, webSearchRequests: 0, costUSD: 0,
        };
      }
      const b = perModel[model]!;
      b.costUSD += cost;
      b.inputTokens += usage.input_tokens;
      b.outputTokens += usage.output_tokens;
      b.cacheReadInputTokens += usage.cache_read_input_tokens ?? 0;
      b.cacheCreationInputTokens += usage.cache_creation_input_tokens ?? 0;
    },
    getTotalCostUSD: () => totalCost,
    getTotalAPIDurationMs: () => 1000,
    getTotalNetDurationMs: () => 800,
    getTotalLinesAdded: () => 10,
    getTotalLinesRemoved: () => 3,
    getPerModelUsage: () => perModel,
    getCurrentSessionId: () => sessionId,
    resetCostState: () => { totalCost = 0; },
    emitCostCounter: (amount: number) => {
      otelEvents.push({ event: 'cost', value: amount });
    },
    emitTokenCounter: (type: string, count: number, model: string) => {
      otelEvents.push({ event: type, value: count, model });
    },
  };

  return Object.assign(state, { otelEvents, perModel });
}

// ---------------------------------------------------------------------------
// Temp directory for EMBER_CONFIG_HOME (AC1–AC4)
// ---------------------------------------------------------------------------

let tempDir = '';

beforeEach(async () => {
  tempDir = join(tmpdir(), `cost-tel-${Date.now()}-${Math.random().toString(36).slice(2)}`);
  await mkdir(tempDir, { recursive: true });
  process.env['EMBER_HOME'] = tempDir;
  _resetConfigHomeMemo();
  _resetGlobalConfigCache();
});

afterEach(async () => {
  _setDefaultStateForTest(null);
  delete process.env['EMBER_HOME'];
  _resetConfigHomeMemo();
  _resetGlobalConfigCache();
  if (tempDir) {
    await rm(tempDir, { recursive: true, force: true }).catch(() => {});
    tempDir = '';
  }
});

// ---------------------------------------------------------------------------
// canonicalModelName
// ---------------------------------------------------------------------------

describe('canonicalModelName', () => {
  test('maps opus variants to themselves (no short-name mapping)', () => {
    expect(canonicalModelName('qwen-3.6')).toBe('qwen-3.6');
    expect(canonicalModelName('qwen-3.5')).toBe('qwen-3.5');
  });

  test('maps sonnet variants to themselves', () => {
    expect(canonicalModelName('qwen-3.6-fast')).toBe('qwen-3.6-fast');
    expect(canonicalModelName('qwen-3.5-fast')).toBe('qwen-3.5-fast');
  });

  test('maps haiku variants to themselves', () => {
    expect(canonicalModelName('qwen-3.6-haiku')).toBe('qwen-3.6-haiku');
  });

  test('unknown model is returned as-is', () => {
    expect(canonicalModelName('gpt-4')).toBe('gpt-4');
    expect(canonicalModelName('mistral-7b')).toBe('mistral-7b');
  });
});

// ---------------------------------------------------------------------------
// AC7 + AC8: formatCost
// ---------------------------------------------------------------------------

describe('formatCost', () => {
  test('AC7: amount < $0.50 shows full precision (at least 4 decimal places)', () => {
    const result = formatCost(0.0023);
    expect(result.startsWith('$')).toBe(true);
    const decimalPart = result.split('.')[1] ?? '';
    expect(decimalPart.length).toBeGreaterThanOrEqual(4);
    // Must NOT truncate to $0.00
    expect(result).not.toBe('$0.00');
  });

  test('$0.0001 shows at least 4 decimal places', () => {
    const result = formatCost(0.0001);
    expect(result).toBe('$0.0001');
  });

  test('AC8: amount >= $0.50 uses maxDecimalPlaces', () => {
    const result = formatCost(1.23456, 2);
    expect(result.startsWith('$')).toBe(true);
    const decimalPart = result.split('.')[1] ?? '';
    expect(decimalPart.length).toBeLessThanOrEqual(2);
  });

  test('amount >= $0.50 defaults to 2 decimal places without maxDecimalPlaces', () => {
    expect(formatCost(5.0)).toBe('$5.00');
    expect(formatCost(1.5)).toBe('$1.50');
  });

  test('exactly $0.50 is not small (uses standard formatting)', () => {
    const result = formatCost(0.5, 2);
    expect(result).toBe('$0.50');
  });

  test('always prefixed with $', () => {
    expect(formatCost(0).startsWith('$')).toBe(true);
    expect(formatCost(100).startsWith('$')).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// AC5: addToTotalSessionCost — per-model accumulation
// ---------------------------------------------------------------------------

describe('addToTotalSessionCost', () => {
  test('AC5: adds cost to model bucket keyed by full model ID', () => {
    const state = makeTestState();
    addToTotalSessionCost(0.05, { input_tokens: 100, output_tokens: 50 }, 'qwen-3.6', [], state);
    expect(state.getPerModelUsage()['qwen-3.6']?.costUSD).toBeCloseTo(0.05, 6);
  });

  test('returns accumulated total cost', () => {
    const state = makeTestState();
    addToTotalSessionCost(0.05, { input_tokens: 100, output_tokens: 50 }, 'qwen-3.6', [], state);
    const total = addToTotalSessionCost(0.10, { input_tokens: 200, output_tokens: 100 }, 'qwen-3.6-fast', [], state);
    expect(total).toBeCloseTo(0.15, 6);
  });

  test('accumulates token counts in model bucket', () => {
    const state = makeTestState();
    addToTotalSessionCost(0.02, { input_tokens: 300, output_tokens: 150 }, 'qwen-3.6-haiku', [], state);
    const haiku = state.getPerModelUsage()['qwen-3.6-haiku'];
    expect(haiku?.inputTokens).toBe(300);
    expect(haiku?.outputTokens).toBe(150);
  });

  test('cache tokens are tracked in model bucket', () => {
    const state = makeTestState();
    addToTotalSessionCost(
      0.01,
      { input_tokens: 100, output_tokens: 50, cache_read_input_tokens: 20, cache_creation_input_tokens: 10 },
      'qwen-3.6-fast',
      [],
      state,
    );
    const sonnet = state.getPerModelUsage()['qwen-3.6-fast'];
    expect(sonnet?.cacheReadInputTokens).toBe(20);
    expect(sonnet?.cacheCreationInputTokens).toBe(10);
  });

  test('AC6: advisor usage causes separate OTel emission for each model', () => {
    const state = makeTestState();
    addToTotalSessionCost(
      0.10,
      { input_tokens: 100, output_tokens: 50 },
      'qwen-3.6',
      [{ model: 'qwen-3.6-haiku', usage: { input_tokens: 50, output_tokens: 25 }, cost: 0.01 }],
      state,
    );
    const costEvents = state.otelEvents.filter(e => e.event === 'cost');
    // One cost event for main model, one for advisor
    expect(costEvents.length).toBe(2);
    // Advisor's model bucket is populated
    expect(state.getPerModelUsage()['qwen-3.6-haiku']?.costUSD).toBeCloseTo(0.01, 6);
  });

  test('advisor costs are included in returned total', () => {
    const state = makeTestState();
    const total = addToTotalSessionCost(
      0.10,
      { input_tokens: 100, output_tokens: 50 },
      'qwen-3.6',
      [{ model: 'qwen-3.6-haiku', usage: { input_tokens: 50, output_tokens: 25 }, cost: 0.01 }],
      state,
    );
    expect(total).toBeCloseTo(0.11, 6);
  });

  test('OTel token counters emitted with model attribute', () => {
    const state = makeTestState();
    addToTotalSessionCost(0.05, { input_tokens: 200, output_tokens: 100 }, 'qwen-3.6', [], state);
    const inputEvent = state.otelEvents.find(e => e.event === 'input');
    const outputEvent = state.otelEvents.find(e => e.event === 'output');
    expect(inputEvent?.value).toBe(200);
    expect(inputEvent?.model).toBe('qwen-3.6');
    expect(outputEvent?.value).toBe(100);
    expect(outputEvent?.model).toBe('qwen-3.6');
  });

  test('cache token OTel events are emitted only when tokens > 0', () => {
    const state = makeTestState();
    addToTotalSessionCost(0.01, { input_tokens: 100, output_tokens: 50 }, 'qwen-3.6-haiku', [], state);
    const cacheReadEvent = state.otelEvents.find(e => e.event === 'cacheRead');
    expect(cacheReadEvent).toBeUndefined();
  });
});

// ---------------------------------------------------------------------------
// AC9: formatTotalCost
// ---------------------------------------------------------------------------

describe('formatTotalCost', () => {
  test('AC9: output includes one line per distinct model used', () => {
    const state = makeTestState();
    addToTotalSessionCost(0.05, { input_tokens: 100, output_tokens: 50 }, 'qwen-3.6', [], state);
    addToTotalSessionCost(0.02, { input_tokens: 50, output_tokens: 25 }, 'qwen-3.6-fast', [], state);

    const summary = formatTotalCost(state);
    expect(summary).toContain('qwen-3.6');
    expect(summary).toContain('qwen-3.6-fast');
  });

  test('summary contains total cost line in USD', () => {
    const state = makeTestState();
    addToTotalSessionCost(0.07, { input_tokens: 100, output_tokens: 50 }, 'qwen-3.6', [], state);

    const summary = formatTotalCost(state);
    expect(summary).toContain('$');
    expect(summary).toContain('Total cost');
  });

  test('summary contains API duration line', () => {
    const state = makeTestState();
    const summary = formatTotalCost(state);
    expect(summary).toContain('API duration');
  });

  test('summary contains code changes line', () => {
    const state = makeTestState();
    const summary = formatTotalCost(state);
    expect(summary).toContain('Code changes');
  });
});

// ---------------------------------------------------------------------------
// AC1–AC4: Config persistence roundtrip (real filesystem via temp dir)
// ---------------------------------------------------------------------------

describe('getStoredSessionCosts', () => {
  test('AC1: matching sessionId returns stored record', async () => {
    const state = makeTestState('session-abc');
    addToTotalSessionCost(0.25, { input_tokens: 500, output_tokens: 250 }, 'qwen-3.6', [], state);
    await saveCurrentSessionCosts(state);

    const result = await getStoredSessionCosts('session-abc');
    expect(result).not.toBeNull();
    expect(result!.sessionId).toBe('session-abc');
    expect(result!.totalCostUSD).toBeCloseTo(0.25, 6);
  });

  test('AC1: non-matching sessionId returns null', async () => {
    const state = makeTestState('session-abc');
    addToTotalSessionCost(0.25, { input_tokens: 500, output_tokens: 250 }, 'qwen-3.6', [], state);
    await saveCurrentSessionCosts(state);

    const result = await getStoredSessionCosts('session-xyz');
    expect(result).toBeNull();
  });

  test('returns null when no record has been saved', async () => {
    const result = await getStoredSessionCosts('nonexistent');
    expect(result).toBeNull();
  });

  test('saved record includes per-model usage', async () => {
    const state = makeTestState('session-model-test');
    addToTotalSessionCost(0.10, { input_tokens: 200, output_tokens: 100 }, 'qwen-3.6', [], state);
    await saveCurrentSessionCosts(state);

    const result = await getStoredSessionCosts('session-model-test');
    expect(result).not.toBeNull();
    expect(result!.perModelUsage['qwen-3.6']).toBeDefined();
    expect(result!.perModelUsage['qwen-3.6']!.costUSD).toBeCloseTo(0.10, 6);
  });
});

describe('restoreCostStateForSession', () => {
  test('AC2: returns true and getTotalCostUSD reflects restored cost', async () => {
    const stateA = makeTestState('session-restore');
    addToTotalSessionCost(0.30, { input_tokens: 100, output_tokens: 50 }, 'qwen-3.6', [], stateA);
    await saveCurrentSessionCosts(stateA);

    const stateB = makeTestState('session-restore');
    const restored = await restoreCostStateForSession('session-restore', stateB);

    expect(restored).toBe(true);
    expect(stateB.getTotalCostUSD()).toBeCloseTo(0.30, 6);
  });

  test('AC3: returns false and cost stays at zero when no matching record', async () => {
    const state = makeTestState('fresh-session');
    const restored = await restoreCostStateForSession('nonexistent-session', state);

    expect(restored).toBe(false);
    expect(state.getTotalCostUSD()).toBe(0);
  });

  test('AC4: save → restore roundtrip preserves totals', async () => {
    const stateA = makeTestState('roundtrip-session');
    addToTotalSessionCost(0.12, { input_tokens: 300, output_tokens: 150 }, 'qwen-3.6-haiku', [], stateA);
    addToTotalSessionCost(0.08, { input_tokens: 200, output_tokens: 100 }, 'qwen-3.6-fast', [], stateA);
    await saveCurrentSessionCosts(stateA);

    // Simulate "process restart" — new state, new cache
    _resetGlobalConfigCache();

    const stateB = makeTestState('roundtrip-session');
    await restoreCostStateForSession('roundtrip-session', stateB);

    // Total = 0.12 + 0.08
    expect(stateB.getTotalCostUSD()).toBeCloseTo(0.20, 6);
  });

  test('restore does not contaminate when session IDs differ', async () => {
    const stateA = makeTestState('session-alpha');
    addToTotalSessionCost(0.50, { input_tokens: 500, output_tokens: 500 }, 'qwen-3.6', [], stateA);
    await saveCurrentSessionCosts(stateA);

    const stateB = makeTestState('session-beta');
    const restored = await restoreCostStateForSession('session-beta', stateB);

    expect(restored).toBe(false);
    expect(stateB.getTotalCostUSD()).toBe(0);
  });
});

describe('saveCurrentSessionCosts with fpsMetrics', () => {
  test('fpsMetrics is included when provided', async () => {
    const state = makeTestState('fps-session');
    const fps = { fps: 60.0, frameCount: 1800, durationMs: 30_000 };
    await saveCurrentSessionCosts(state, fps);

    const result = await getStoredSessionCosts('fps-session');
    expect(result?.fpsMetrics).toEqual(fps);
  });

  test('fpsMetrics is absent when not provided', async () => {
    const state = makeTestState('no-fps-session');
    await saveCurrentSessionCosts(state);

    const result = await getStoredSessionCosts('no-fps-session');
    expect(result?.fpsMetrics).toBeUndefined();
  });
});
