// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// utils/cost-telemetry.ts
// Per-session cost accumulation, OTel emission, and filesystem persistence.
// Contract: src/utils/config-persistence.test.ts (AC1-AC9).

import { readFile, writeFile, mkdir } from 'fs/promises';
import { join } from 'path';
import { getCostStorageDir } from './config-persistence.ts';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface PerModelUsage {
  inputTokens: number;
  outputTokens: number;
  cacheReadInputTokens: number;
  cacheCreationInputTokens: number;
  webSearchRequests: number;
  costUSD: number;
}

export interface UsageRecord {
  input_tokens: number;
  output_tokens: number;
  cache_read_input_tokens?: number;
  cache_creation_input_tokens?: number;
}

/** Module-internal; not exported. */
interface AdvisorRecord {
  model: string;
  usage: UsageRecord;
  cost: number;
}

export interface SessionCostState {
  addToTotalCostState(cost: number, usage: UsageRecord, model: string): void;
  getTotalCostUSD(): number;
  getTotalAPIDurationMs(): number;
  getTotalNetDurationMs(): number;
  getTotalLinesAdded(): number;
  getTotalLinesRemoved(): number;
  getPerModelUsage(): Record<string, PerModelUsage>;
  getCurrentSessionId(): string;
  resetCostState(): void;
  emitCostCounter(amount: number): void;
  emitTokenCounter(type: string, count: number, model: string): void;
}

// ---------------------------------------------------------------------------
// Test injection hook
// ---------------------------------------------------------------------------

let _defaultState: SessionCostState | null = null;

/** TEST-ONLY: inject or clear the module-level default state. */
export function _setDefaultStateForTest(state: SessionCostState | null): void {
  _defaultState = state;
}

// ---------------------------------------------------------------------------
// canonicalModelName — identity (ember model names are already canonical)
// ---------------------------------------------------------------------------

export function canonicalModelName(model: string): string {
  return model;
}

// ---------------------------------------------------------------------------
// formatCost — AC7 + AC8
// ---------------------------------------------------------------------------

/**
 * Formats a cost amount as a USD string.
 * - amount < $0.50 → full string precision, at least 4 decimal places.
 * - amount >= $0.50 → toFixed(maxDecimalPlaces), defaulting to 2.
 */
export function formatCost(amount: number, maxDecimalPlaces = 2): string {
  if (amount < 0.5) {
    const raw = amount.toString();
    const dotIdx = raw.indexOf('.');
    if (dotIdx === -1) {
      return `$${raw}.0000`;
    }
    const decimals = raw.length - dotIdx - 1;
    if (decimals < 4) {
      return `$${raw}${'0'.repeat(4 - decimals)}`;
    }
    return `$${raw}`;
  }
  return `$${amount.toFixed(maxDecimalPlaces)}`;
}

// ---------------------------------------------------------------------------
// formatTotalCost — AC9
// ---------------------------------------------------------------------------

/** Produces a multi-line summary with per-model breakdown. */
export function formatTotalCost(state: SessionCostState): string {
  const totalCost = state.getTotalCostUSD();
  const apiMs = state.getTotalAPIDurationMs();
  const linesAdded = state.getTotalLinesAdded();
  const linesRemoved = state.getTotalLinesRemoved();
  const perModel = state.getPerModelUsage();

  const lines: string[] = [
    `Total cost: ${formatCost(totalCost)}`,
    `API duration: ${apiMs}ms`,
    `Code changes: +${linesAdded} -${linesRemoved} lines`,
  ];

  for (const [model, usage] of Object.entries(perModel)) {
    lines.push(
      `  ${model}: ${formatCost(usage.costUSD)} (${usage.inputTokens}in, ${usage.outputTokens}out)`,
    );
  }

  return lines.join('\n');
}

// ---------------------------------------------------------------------------
// addToTotalSessionCost — AC5 + AC6
// ---------------------------------------------------------------------------

/**
 * Records cost + usage for a model turn (and optional advisors) into the
 * session state, emits OTel counters, and returns the new running total.
 */
export function addToTotalSessionCost(
  cost: number,
  usage: UsageRecord,
  model: string,
  advisors: AdvisorRecord[],
  state: SessionCostState,
): number {
  // Main model
  state.addToTotalCostState(cost, usage, model);
  state.emitCostCounter(cost);
  state.emitTokenCounter('input', usage.input_tokens, model);
  state.emitTokenCounter('output', usage.output_tokens, model);

  const cacheRead = usage.cache_read_input_tokens ?? 0;
  if (cacheRead > 0) {
    state.emitTokenCounter('cacheRead', cacheRead, model);
  }
  const cacheCreate = usage.cache_creation_input_tokens ?? 0;
  if (cacheCreate > 0) {
    state.emitTokenCounter('cacheCreate', cacheCreate, model);
  }

  // Advisor models
  for (const advisor of advisors) {
    state.addToTotalCostState(advisor.cost, advisor.usage, advisor.model);
    state.emitCostCounter(advisor.cost);
    state.emitTokenCounter('input', advisor.usage.input_tokens, advisor.model);
    state.emitTokenCounter('output', advisor.usage.output_tokens, advisor.model);
  }

  return state.getTotalCostUSD();
}

// ---------------------------------------------------------------------------
// Persistence types
// ---------------------------------------------------------------------------

interface StoredSessionRecord {
  sessionId: string;
  totalCostUSD: number;
  perModelUsage: Record<string, PerModelUsage>;
  fpsMetrics?: { fps: number; frameCount: number; durationMs: number };
}

// ---------------------------------------------------------------------------
// getStoredSessionCosts — AC1
// ---------------------------------------------------------------------------

/** Reads the persisted cost record for the given sessionId, or null if absent. */
export async function getStoredSessionCosts(sessionId: string): Promise<StoredSessionRecord | null> {
  try {
    const dir = getCostStorageDir();
    const filePath = join(dir, `${sessionId}.json`);
    const raw = await readFile(filePath, 'utf-8');
    const data = JSON.parse(raw) as StoredSessionRecord;
    if (data.sessionId !== sessionId) return null;
    return data;
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// saveCurrentSessionCosts
// ---------------------------------------------------------------------------

/** Writes the current session costs to disk. */
export async function saveCurrentSessionCosts(
  state: SessionCostState,
  fpsMetrics?: { fps: number; frameCount: number; durationMs: number },
): Promise<void> {
  const sessionId = state.getCurrentSessionId();
  const dir = getCostStorageDir();
  await mkdir(dir, { recursive: true });

  const record: StoredSessionRecord = {
    sessionId,
    totalCostUSD: state.getTotalCostUSD(),
    perModelUsage: state.getPerModelUsage(),
    ...(fpsMetrics !== undefined ? { fpsMetrics } : {}),
  };

  await writeFile(join(dir, `${sessionId}.json`), JSON.stringify(record, null, 2), 'utf-8');
}

// ---------------------------------------------------------------------------
// restoreCostStateForSession — AC2-AC4
// ---------------------------------------------------------------------------

/**
 * Loads a stored cost record into `state` by replaying each model's usage.
 * Returns true on success, false when no matching record exists.
 */
export async function restoreCostStateForSession(
  sessionId: string,
  state: SessionCostState,
): Promise<boolean> {
  const record = await getStoredSessionCosts(sessionId);
  if (record === null) return false;

  for (const [model, usage] of Object.entries(record.perModelUsage)) {
    const usageRecord: UsageRecord = {
      input_tokens: usage.inputTokens,
      output_tokens: usage.outputTokens,
      cache_read_input_tokens: usage.cacheReadInputTokens,
      cache_creation_input_tokens: usage.cacheCreationInputTokens,
    };
    state.addToTotalCostState(usage.costUSD, usageRecord, model);
  }

  return true;
}
