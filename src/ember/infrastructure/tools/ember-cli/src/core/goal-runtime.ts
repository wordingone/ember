// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// core/goal-runtime.ts — production singleton wiring for the goal organ
// (ember issue #211). Composes the pure core/goal-store.ts state machine with
// file persistence (services/goal-persistence.ts) and the receipt writer
// (services/goal-receipts.ts) so the rest of the app (the /goal command,
// tools/goal-tools.ts, the continuation engine) shares ONE goal per session
// instead of each constructing a competing store — the same "shared singleton,
// injected provider" shape commands/goal.ts's setGoalEngineProvider already
// used for the QueryEngine.

import { createGoalStore, type GoalStore } from "./goal-store.ts";
import { createFileGoalPersistence } from "../services/goal-persistence.ts";
import { createGoalReceiptWriter, receiptGoalTransition, type GoalReceiptWriter } from "../services/goal-receipts.ts";
import { getSessionId } from "../session-state.ts";

let _store: GoalStore | null = null;
let _receiptWriter: GoalReceiptWriter | null = null;
let _storeOverride: GoalStore | null = null;

/**
 * Returns the process-wide goal store, constructing it lazily on first use so
 * production startup never pays for file I/O it might not need. Test override
 * (setGoalStoreForTests) always wins when set.
 */
export function getGoalStore(): GoalStore {
  if (_storeOverride) return _storeOverride;
  if (_store) return _store;

  const sessionId = getSessionId();
  const persistence = createFileGoalPersistence({ sessionId });
  const receiptWriter = createGoalReceiptWriter({ sessionId });
  _receiptWriter = receiptWriter;

  _store = createGoalStore({
    persistence,
    onTransition: (event) => receiptGoalTransition(receiptWriter, event),
  });
  return _store;
}

/**
 * The current "Selection and persistence" section: "Goals require a
 * persistent session; ephemeral sessions refuse with
 * a clear message." ember-cli does not yet have a real persistent/ephemeral
 * session concept distinct from ToolUseContext.isNonInteractiveSession itself
 * -- and that flag is NEVER set by query-engine.ts's _buildToolUseContext, so
 * it is always `undefined` (not `true`) on every real call today.
 *
 * Deliberately NOT falling back to session-state.ts's getIsNonInteractiveSession():
 * that getter derives from `isInteractiveFlag`, which defaults to `false` and is
 * never flipped to `true` anywhere in production -- so it unconditionally
 * reports "non-interactive" for every session that exists today, INCLUDING the
 * live interactive REPL. Using it as a fallback here would make the only real
 * entry point permanently refuse goal creation. Until ember-cli grows a real
 * ephemeral-session signal and threads it into ToolUseContext.isNonInteractiveSession,
 * the only trustworthy signal is an EXPLICIT `true` on that field -- absence
 * defaults to "persistent" (the safe default: a false positive here silently
 * breaks the whole organ, a false negative merely admits a goal to a session
 * that in practice is always the persistent REPL anyway).
 */
export function isCurrentSessionEphemeral(context?: { isNonInteractiveSession?: boolean }): boolean {
  return context?.isNonInteractiveSession === true;
}

/** Test-only override — points every getGoalStore() caller at a fake store
 *  (in-memory persistence, no fs) for the duration of a test. */
export function setGoalStoreForTests(store: GoalStore | null): void {
  _storeOverride = store;
}

/** Test-only reset — clears both the lazily-built production store and any override. */
export function resetGoalRuntimeForTests(): void {
  _store = null;
  _receiptWriter = null;
  _storeOverride = null;
}

/** The receipt writer bound to the live production store, if one has been
 *  constructed yet. Exposed for the continuation engine, which receipts its
 *  own fire/skip events (the current "Artifact binding" section) through the
 *  SAME session file the store's
 *  transitions go to. */
export function getGoalReceiptWriter(): GoalReceiptWriter | null {
  if (_storeOverride) return null;
  getGoalStore(); // ensures _receiptWriter is constructed
  return _receiptWriter;
}
