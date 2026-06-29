// session-state.ts — session singleton: identity, cost, tokens, latches, and caches.

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let sessionId: string = crypto.randomUUID();
let parentSessionId: string | null = null;
let sessionProjectDir: string | null = null;
let isInteractiveFlag: boolean = false;
let clientTypeValue: string = 'cli';
let bypassPermissions: boolean = false;

let totalCostUSD: number = 0;
let totalAPIDuration: number = 0;
let totalWallDuration: number = 0;
let totalLinesAdded: number = 0;
let totalLinesRemoved: number = 0;

let afkLatch: boolean | null = null;
let fastLatch: boolean | null = null;
let cacheEditingLatch: boolean | null = null;
let thinkingClearLatch: boolean | null = null;

let inMemoryErrorLog: Array<{ error: string; timestamp: number }> = [];
let systemPromptCache: Map<string, string> = new Map();

interface ModelRecord {
  inputTokens: number;
  outputTokens: number;
  cacheReadInputTokens: number;
  cacheCreationInputTokens: number;
  cost: number;
}
let modelUsageMap: Map<string, ModelRecord> = new Map();

interface CronTask {
  id: string;
  cron: string;
  prompt: string;
  createdAt: number;
  agentId?: string;
  recurring: boolean;
}
let cronTasks: CronTask[] = [];

let promptCache1h: boolean | null = null;
let outputTokensSnapshot: number = 0;
let currentBudget: number = 0;
let budgetContinuationCnt: number = 0;
let postCompactionFlag: boolean = false;
let postCompactionElapsedSecs: number = 0;
let promptIdValue: string | null = null;

const sessionSwitchListeners: Array<(newId: string) => void> = [];

function notifySessionSwitch(newId: string): void {
  for (const cb of sessionSwitchListeners) cb(newId);
}

// ---------------------------------------------------------------------------
// Test guard
// ---------------------------------------------------------------------------

export function resetStateForTests(): void {
  if (process.env['NODE_ENV'] !== 'test') {
    throw new Error('resetStateForTests() may only be called in test environments');
  }
  sessionId = crypto.randomUUID();
  parentSessionId = null;
  sessionProjectDir = null;
  isInteractiveFlag = false;
  clientTypeValue = 'cli';
  bypassPermissions = false;
  totalCostUSD = 0;
  totalAPIDuration = 0;
  totalWallDuration = 0;
  totalLinesAdded = 0;
  totalLinesRemoved = 0;
  afkLatch = null;
  fastLatch = null;
  cacheEditingLatch = null;
  thinkingClearLatch = null;
  inMemoryErrorLog = [];
  systemPromptCache = new Map();
  modelUsageMap = new Map();
  cronTasks = [];
  promptCache1h = null;
  outputTokensSnapshot = 0;
  currentBudget = 0;
  budgetContinuationCnt = 0;
  postCompactionFlag = false;
  postCompactionElapsedSecs = 0;
  promptIdValue = null;
  sessionSwitchListeners.length = 0;
}

// ---------------------------------------------------------------------------
// Session identity
// ---------------------------------------------------------------------------

export function getSessionId(): string { return sessionId; }
export function setSessionId(id: string): void { sessionId = id; }

export function switchSession(id: string, dir: string | null): void {
  sessionId = id;
  sessionProjectDir = dir;
  notifySessionSwitch(id);
}

export function regenerateSessionId(opts?: { setCurrentAsParent?: boolean; oldSessionId?: string }): string {
  const newId = crypto.randomUUID();
  if (opts?.setCurrentAsParent) {
    parentSessionId = sessionId;
  }
  sessionId = newId;
  notifySessionSwitch(newId);
  return newId;
}

export function getParentSessionId(): string | null { return parentSessionId; }
export function getSessionProjectDir(): string | null { return sessionProjectDir; }

export function onSessionSwitch(cb: (newId: string) => void): () => void {
  sessionSwitchListeners.push(cb);
  return () => {
    const idx = sessionSwitchListeners.indexOf(cb);
    if (idx >= 0) sessionSwitchListeners.splice(idx, 1);
  };
}

// ---------------------------------------------------------------------------
// Interactive / client type
// ---------------------------------------------------------------------------

export function getIsInteractive(): boolean { return isInteractiveFlag; }
export function setIsInteractive(b: boolean): void { isInteractiveFlag = b; }
export function getIsNonInteractiveSession(): boolean { return !isInteractiveFlag; }

export function getClientType(): string { return clientTypeValue; }
export function setClientType(type: string): void { clientTypeValue = type; }

export function preferThirdPartyAuthentication(): boolean {
  return isInteractiveFlag && clientTypeValue !== 'ember-vscode';
}

// ---------------------------------------------------------------------------
// Cost / duration / lines
// ---------------------------------------------------------------------------

interface TokenCounts {
  input_tokens: number;
  output_tokens: number;
  cache_read_input_tokens: number;
  cache_creation_input_tokens: number;
}

export function addToTotalCostState(cost: number, tokens: TokenCounts, modelId: string): void {
  totalCostUSD += cost;
  const existing = modelUsageMap.get(modelId) ?? {
    inputTokens: 0, outputTokens: 0, cacheReadInputTokens: 0, cacheCreationInputTokens: 0, cost: 0,
  };
  modelUsageMap.set(modelId, {
    inputTokens: existing.inputTokens + tokens.input_tokens,
    outputTokens: existing.outputTokens + tokens.output_tokens,
    cacheReadInputTokens: existing.cacheReadInputTokens + tokens.cache_read_input_tokens,
    cacheCreationInputTokens: existing.cacheCreationInputTokens + tokens.cache_creation_input_tokens,
    cost: existing.cost + cost,
  });
}

export function getTotalCostUSD(): number { return totalCostUSD; }

export function resetCostState(): void {
  totalCostUSD = 0;
  totalAPIDuration = 0;
  totalWallDuration = 0;
  totalLinesAdded = 0;
  totalLinesRemoved = 0;
  modelUsageMap = new Map();
  promptIdValue = null;
}

export function addToTotalDurationState(apiMs: number, wallMs: number): void {
  totalWallDuration += wallMs;
  totalAPIDuration += apiMs;
}

export function getTotalAPIDuration(): number { return totalAPIDuration; }

export function addToTotalLinesChanged(added: number, removed: number): void {
  totalLinesAdded += added;
  totalLinesRemoved += removed;
}

export function getTotalLinesAdded(): number { return totalLinesAdded; }
export function getTotalLinesRemoved(): number { return totalLinesRemoved; }

// ---------------------------------------------------------------------------
// Token aggregates
// ---------------------------------------------------------------------------

export function getTotalCacheReadInputTokens(): number {
  let total = 0;
  for (const r of modelUsageMap.values()) total += r.cacheReadInputTokens;
  return total;
}

export function getTotalInputTokens(): number {
  let total = 0;
  for (const r of modelUsageMap.values()) total += r.inputTokens;
  return total;
}

export function getTotalOutputTokens(): number {
  let total = 0;
  for (const r of modelUsageMap.values()) total += r.outputTokens;
  return total;
}

export function getModelUsage(): Map<string, { inputTokens: number; outputTokens: number; cacheReadInputTokens: number; cacheCreationInputTokens: number; cost: number }> {
  return new Map(modelUsageMap);
}

// ---------------------------------------------------------------------------
// Bypass permissions
// ---------------------------------------------------------------------------

export function setSessionBypassPermissionsMode(b: boolean): void { bypassPermissions = b; }
export function getSessionBypassPermissionsMode(): boolean { return bypassPermissions; }

// ---------------------------------------------------------------------------
// Beta header latches
// ---------------------------------------------------------------------------

export function getAfkModeHeaderLatched(): boolean | null { return afkLatch; }
export function setAfkModeHeaderLatched(b: boolean): void { afkLatch = b; }

export function getFastModeHeaderLatched(): boolean | null { return fastLatch; }
export function setFastModeHeaderLatched(b: boolean): void { fastLatch = b; }

export function getCacheEditingHeaderLatched(): boolean | null { return cacheEditingLatch; }
export function setCacheEditingHeaderLatched(b: boolean): void { cacheEditingLatch = b; }

export function getThinkingClearLatched(): boolean | null { return thinkingClearLatch; }
export function setThinkingClearLatched(b: boolean): void { thinkingClearLatch = b; }

export function clearBetaHeaderLatches(): void {
  afkLatch = null;
  fastLatch = null;
  cacheEditingLatch = null;
  thinkingClearLatch = null;
}

// ---------------------------------------------------------------------------
// Error log (bounded at 100)
// ---------------------------------------------------------------------------

export function addToInMemoryErrorLog(entry: { error: string; timestamp: number }): void {
  inMemoryErrorLog.push(entry);
  if (inMemoryErrorLog.length > 100) {
    inMemoryErrorLog = inMemoryErrorLog.slice(-100);
  }
}

// ---------------------------------------------------------------------------
// System prompt section cache
// ---------------------------------------------------------------------------

export function setSystemPromptSectionCacheEntry(key: string, value: string): void {
  systemPromptCache.set(key, value);
}

export function getSystemPromptSectionCacheEntry(key: string): string | null {
  return systemPromptCache.get(key) ?? null;
}

export function clearSystemPromptSectionState(): void {
  systemPromptCache = new Map();
}

// ---------------------------------------------------------------------------
// Cron tasks
// ---------------------------------------------------------------------------

export function addSessionCronTask(task: CronTask): void {
  cronTasks.push(task);
}

export function getSessionCronTasks(): CronTask[] {
  return cronTasks;
}

// ---------------------------------------------------------------------------
// Prompt cache 1h eligibility
// ---------------------------------------------------------------------------

export function getPromptCache1hEligible(): boolean | null { return promptCache1h; }
export function setPromptCache1hEligible(b: boolean): void { promptCache1h = b; }

// ---------------------------------------------------------------------------
// Per-turn output token budget
// ---------------------------------------------------------------------------

export function snapshotOutputTokensForTurn(budget: number): void {
  outputTokensSnapshot = getTotalOutputTokens();
  currentBudget = budget;
  budgetContinuationCnt = 0;
}

export function getTurnOutputTokens(): number {
  return getTotalOutputTokens() - outputTokensSnapshot;
}

export function getCurrentTurnTokenBudget(): number { return currentBudget; }

export function incrementBudgetContinuationCount(): void { budgetContinuationCnt++; }
export function getBudgetContinuationCount(): number { return budgetContinuationCnt; }

// ---------------------------------------------------------------------------
// Post-compaction flag (one-shot)
// ---------------------------------------------------------------------------

export function markPostCompaction(elapsedSecs: number = 0): void {
  postCompactionFlag = true;
  postCompactionElapsedSecs = elapsedSecs;
}

/**
 * One-shot read of the post-compaction signal. Returns the elapsed seconds of
 * the compaction that just ran (>= 0) and resets, or null when no compaction is
 * pending. Number-not-boolean so the REPL can render "Crunched for Xs".
 */
export function consumePostCompaction(): number | null {
  if (postCompactionFlag) {
    postCompactionFlag = false;
    const elapsed = postCompactionElapsedSecs;
    postCompactionElapsedSecs = 0;
    return elapsed;
  }
  return null;
}

// ---------------------------------------------------------------------------
// Prompt ID
// ---------------------------------------------------------------------------

export function getPromptId(): string | null { return promptIdValue; }
export function setPromptId(id: string): void { promptIdValue = id; }
