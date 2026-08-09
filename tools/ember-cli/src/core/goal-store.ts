// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// core/goal-store.ts — persisted goal state machine (ember issue #211, spec:
// docs/goal-mode-mechanism.md "Selection and persistence"). Data model:
// goal_id, objective (max 4000
// chars, immutable to the model), status machine, optional token_budget,
// system-tallied usage. Objective immutability is enforced AT THE API LAYER
// here (updateStatus's signature never accepts an objective field at all) --
// only editObjective() can change it, and that method is never exposed as a
// model-side tool (see tools/goal-tools.ts: update_goal wires to updateStatus
// only). This module is pure: no fs, no session-state import, no React --
// production wiring (file persistence, receipts, session id) lives in
// core/goal-runtime.ts so this file stays fully unit-testable with an
// in-memory GoalStorePersistence.

// ---------------------------------------------------------------------------
// Data model
// ---------------------------------------------------------------------------

export type GoalStatus =
  | "Active"
  | "Paused"
  | "Blocked"
  | "UsageLimited"
  | "BudgetLimited"
  | "Complete";

export const OBJECTIVE_MAX_CHARS = 4000;

/** Consecutive same-blocker goal-turns required before Active -> Blocked is legitimate
 *  (the current "Continuation loop" section: "never blocked merely because
 *  the work is hard, slow, uncertain, incomplete"). */
export const BLOCKED_TURNS_THRESHOLD = 3;

export interface GoalUsage {
  tokensUsed: number;
  elapsedMs: number;
}

/** Requirement-by-requirement evidence required to prove a Complete transition. */
export interface CompletionAuditItem {
  id: string;
  evidence: string;
}

export interface CompletionAudit {
  requirements: CompletionAuditItem[];
}

export interface GoalRecord {
  goalId: string;
  /** Immutable to the model. Only editObjective() (never exposed as a model tool) may change this. */
  objective: string;
  status: GoalStatus;
  tokenBudget?: number;
  usage: GoalUsage;
  createdAt: string;
  updatedAt: string;
  /** Consecutive goal-turns the CURRENT blocking condition has repeated; reset on any transition to Active. */
  consecutiveBlockedTurns: number;
  lastBlockReason?: string;
  /** Exact evidence supplied for the terminal Complete transition, when present. */
  completionAudit?: CompletionAudit;
}

// ---------------------------------------------------------------------------
// Status machine — the legal-transition table
// ---------------------------------------------------------------------------

const LEGAL_TRANSITIONS: Record<GoalStatus, ReadonlyArray<GoalStatus>> = {
  Active: ["Paused", "Blocked", "UsageLimited", "BudgetLimited", "Complete"],
  // Every limited/paused/blocked state's only way out is a resume back to Active
  // ("resume resets the audit" -- the current "Continuation loop" section);
  // BudgetLimited additionally allows a
  // direct Complete when the wrap-up steer's completion audit finds the objective
  // genuinely already met (the current "Continuation loop" section: "never
  // mark complete unless actually complete" --
  // the store only enforces the transition is STRUCTURALLY legal; that the completion
  // is genuine is a doctrine-level guarantee, not something a state machine can verify).
  Paused: ["Active"],
  Blocked: ["Active"],
  UsageLimited: ["Active"],
  BudgetLimited: ["Active", "Complete"],
  Complete: [],
};

/** True iff `from -> to` is a legal transition. Self-transitions are always illegal --
 *  a transition must be a REAL state change, not a no-op receipted as one. */
export function isLegalTransition(from: GoalStatus, to: GoalStatus): boolean {
  if (from === to) return false;
  return LEGAL_TRANSITIONS[from].includes(to);
}

// ---------------------------------------------------------------------------
// Objective validation
// ---------------------------------------------------------------------------

export type ValidationOutcome = { ok: true } | { ok: false; message: string };

export function validateCompletionAudit(value: unknown): ValidationOutcome {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return { ok: false, message: "Complete requires a completionAudit object" };
  }
  const audit = value as Record<string, unknown>;
  if (Object.keys(audit).length !== 1 || !Object.prototype.hasOwnProperty.call(audit, "requirements")) {
    return { ok: false, message: "completionAudit must contain only requirements" };
  }
  if (!Array.isArray(audit.requirements) || audit.requirements.length === 0) {
    return { ok: false, message: "completionAudit.requirements must contain at least one item" };
  }
  const seen = new Set<string>();
  for (const item of audit.requirements) {
    if (!item || typeof item !== "object" || Array.isArray(item)) {
      return { ok: false, message: "completionAudit requirements must be objects" };
    }
    const record = item as Record<string, unknown>;
    if (Object.keys(record).length !== 2 || typeof record.id !== "string" || typeof record.evidence !== "string") {
      return { ok: false, message: "completionAudit items require only non-empty id and evidence" };
    }
    const id = record.id.trim();
    const evidence = record.evidence.trim();
    if (!id || !evidence) {
      return { ok: false, message: "completionAudit items require non-empty id and evidence" };
    }
    if (seen.has(id)) {
      return { ok: false, message: `completionAudit repeats requirement ${id}` };
    }
    seen.add(id);
  }
  return { ok: true };
}

export function validateObjective(objective: string): ValidationOutcome {
  const trimmed = objective.trim();
  if (trimmed.length === 0) {
    return { ok: false, message: "objective cannot be empty" };
  }
  if (objective.length > OBJECTIVE_MAX_CHARS) {
    return {
      ok: false,
      message: `objective exceeds ${OBJECTIVE_MAX_CHARS} chars (got ${objective.length})`,
    };
  }
  return { ok: true };
}

// ---------------------------------------------------------------------------
// Persistence seam
// ---------------------------------------------------------------------------

export interface GoalStorePersistence {
  read(): GoalRecord | null;
  write(record: GoalRecord | null): void;
}

/** In-memory persistence — the default when no production backend is supplied
 *  (tests; also a safe fallback if file persistence fails to initialize). */
export function createInMemoryGoalPersistence(
  initial: GoalRecord | null = null,
): GoalStorePersistence {
  let current = initial;
  return {
    read: () => current,
    write: (record) => {
      current = record;
    },
  };
}

// ---------------------------------------------------------------------------
// Transition events — emitted for the receipt store (goal-runtime.ts wires
// these to services/goal-receipts.ts; the current "Continuation loop" and
// "Artifact binding" sections go through this single seam so nothing can
// transition without a receipt).
// ---------------------------------------------------------------------------

export type GoalTransitionEvent =
  | { kind: "created"; goal: GoalRecord }
  | { kind: "status_changed"; goal: GoalRecord; from: GoalStatus; to: GoalStatus; reason?: string; completionAudit?: CompletionAudit }
  | { kind: "objective_edited"; goal: GoalRecord; previousObjective: string }
  | { kind: "usage_recorded"; goal: GoalRecord }
  | { kind: "cleared"; goalId: string };

// ---------------------------------------------------------------------------
// GoalStore
// ---------------------------------------------------------------------------

export type GoalResult = { ok: true; goal: GoalRecord } | { ok: false; message: string };

export interface CreateGoalOptions {
  tokenBudget?: number;
  /** The current "Selection and persistence" section: "Goals require a
   * persistent session; ephemeral sessions refuse with a
   *  clear message." Caller (goal-runtime.ts) resolves this from the real session. */
  isEphemeralSession?: boolean;
}

export interface NoteBlockedResult {
  consecutiveBlockedTurns: number;
  /** True once the SAME blocker has repeated BLOCKED_TURNS_THRESHOLD consecutive turns --
   *  the caller (continuation engine) is the one that actually fires updateStatus("Blocked"). */
  readyToBlock: boolean;
}

export interface GoalStore {
  getGoal(): GoalRecord | null;
  /** Fails if a goal record already exists (of any status) -- "only when explicitly
   *  requested -- never inferred from ordinary tasks" (the current "Selection
   *  and persistence" section). /goal clear removes
   *  the existing record first if the caller wants to start over. */
  createGoal(objective: string, opts?: CreateGoalOptions): GoalResult;
  /** The ONLY way the objective can change. Never called from a model-side tool --
   *  tools/goal-tools.ts's update_goal wires to updateStatus exclusively. */
  editObjective(newObjective: string): GoalResult;
  /** Status-only transition, gated by isLegalTransition. This is what update_goal calls --
   *  its input schema has no objective field, so there is no code path from the model
   *  into this method that could smuggle an objective change through. */
  updateStatus(status: GoalStatus, opts?: { reason?: string; completionAudit?: CompletionAudit }): GoalResult;
  recordUsage(tokensDelta: number, elapsedMsDelta?: number): GoalResult;
  noteBlocked(reason: string): NoteBlockedResult;
  /** Called on any transition to Active (resume) -- "resume resets the audit". */
  resetBlockedAudit(): void;
  clear(): void;
}

export interface GoalStoreDeps {
  persistence?: GoalStorePersistence;
  now?: () => Date;
  generateId?: () => string;
  onTransition?: (event: GoalTransitionEvent) => void;
}

export function createGoalStore(deps: GoalStoreDeps = {}): GoalStore {
  const persistence = deps.persistence ?? createInMemoryGoalPersistence();
  const now = deps.now ?? (() => new Date());
  const generateId = deps.generateId ?? (() => crypto.randomUUID());
  const emit = deps.onTransition ?? ((): void => {});

  function getGoal(): GoalRecord | null {
    return persistence.read();
  }

  function createGoal(objective: string, opts: CreateGoalOptions = {}): GoalResult {
    if (opts.isEphemeralSession) {
      return {
        ok: false,
        message: "goals require a persistent session; this session is ephemeral",
      };
    }
    const existing = persistence.read();
    if (existing) {
      return {
        ok: false,
        message: `a goal already exists (${existing.goalId}, status ${existing.status}) -- /goal clear it first`,
      };
    }
    const validated = validateObjective(objective);
    if (!validated.ok) return validated;

    const nowIso = now().toISOString();
    const goal: GoalRecord = {
      goalId: generateId(),
      objective: objective.trim(),
      status: "Active",
      ...(opts.tokenBudget !== undefined ? { tokenBudget: opts.tokenBudget } : {}),
      usage: { tokensUsed: 0, elapsedMs: 0 },
      createdAt: nowIso,
      updatedAt: nowIso,
      consecutiveBlockedTurns: 0,
    };
    persistence.write(goal);
    emit({ kind: "created", goal });
    return { ok: true, goal };
  }

  function editObjective(newObjective: string): GoalResult {
    const existing = persistence.read();
    if (!existing) return { ok: false, message: "no active goal to edit" };
    const validated = validateObjective(newObjective);
    if (!validated.ok) return validated;

    const previousObjective = existing.objective;
    const updated: GoalRecord = {
      ...existing,
      objective: newObjective.trim(),
      updatedAt: now().toISOString(),
    };
    persistence.write(updated);
    emit({ kind: "objective_edited", goal: updated, previousObjective });
    return { ok: true, goal: updated };
  }

  function updateStatus(status: GoalStatus, opts: { reason?: string; completionAudit?: CompletionAudit } = {}): GoalResult {
    const existing = persistence.read();
    if (!existing) return { ok: false, message: "no active goal" };
    if (!isLegalTransition(existing.status, status)) {
      return {
        ok: false,
        message: `illegal transition ${existing.status} -> ${status}`,
      };
    }
    if (opts.completionAudit !== undefined && status !== "Complete") {
      return { ok: false, message: "completionAudit is valid only for Complete transitions" };
    }
    if (status === "Complete") {
      const completionAudit = validateCompletionAudit(opts.completionAudit);
      if (!completionAudit.ok) return completionAudit;
    }
    const resetsAudit = status === "Active";
    const updated: GoalRecord = {
      ...existing,
      status,
      updatedAt: now().toISOString(),
      consecutiveBlockedTurns: resetsAudit ? 0 : existing.consecutiveBlockedTurns,
      ...(resetsAudit ? { lastBlockReason: undefined } : {}),
      ...(status === "Complete" && opts.completionAudit !== undefined
        ? { completionAudit: opts.completionAudit }
        : {}),
    };
    persistence.write(updated);
    emit({
      kind: "status_changed",
      goal: updated,
      from: existing.status,
      to: status,
      ...(opts.reason !== undefined ? { reason: opts.reason } : {}),
      ...(status === "Complete" && opts.completionAudit !== undefined
        ? { completionAudit: opts.completionAudit }
        : {}),
    });
    return { ok: true, goal: updated };
  }

  function recordUsage(tokensDelta: number, elapsedMsDelta: number = 0): GoalResult {
    const existing = persistence.read();
    if (!existing) return { ok: false, message: "no active goal" };
    const updated: GoalRecord = {
      ...existing,
      usage: {
        tokensUsed: existing.usage.tokensUsed + tokensDelta,
        elapsedMs: existing.usage.elapsedMs + elapsedMsDelta,
      },
      updatedAt: now().toISOString(),
    };
    persistence.write(updated);
    emit({ kind: "usage_recorded", goal: updated });
    return { ok: true, goal: updated };
  }

  function noteBlocked(reason: string): NoteBlockedResult {
    const existing = persistence.read();
    if (!existing) return { consecutiveBlockedTurns: 0, readyToBlock: false };
    const sameReason = existing.lastBlockReason === reason;
    const count = sameReason ? existing.consecutiveBlockedTurns + 1 : 1;
    const updated: GoalRecord = {
      ...existing,
      consecutiveBlockedTurns: count,
      lastBlockReason: reason,
      updatedAt: now().toISOString(),
    };
    persistence.write(updated);
    return { consecutiveBlockedTurns: count, readyToBlock: count >= BLOCKED_TURNS_THRESHOLD };
  }

  function resetBlockedAudit(): void {
    const existing = persistence.read();
    if (!existing) return;
    persistence.write({ ...existing, consecutiveBlockedTurns: 0, lastBlockReason: undefined });
  }

  function clear(): void {
    const existing = persistence.read();
    persistence.write(null);
    if (existing) emit({ kind: "cleared", goalId: existing.goalId });
  }

  return {
    getGoal,
    createGoal,
    editObjective,
    updateStatus,
    recordUsage,
    noteBlocked,
    resetBlockedAudit,
    clear,
  };
}
