// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// scripts/quarantine-list.ts — files allowed to hit a Bun-internal teardown panic (clean summary,
// nonzero exit) without failing the gate. MUST stay empty right now.
//
// screens/repl-slash-dropdown.test.ts + screens/repl-suggestion-boundary-real-scheduling-error.test.ts
// were the minimal reproducing pair for that panic (bun.report hash:
// 1700fc11iDsgogC+1tmG+nvB62/xhBq92rhB__u40kyCA0eNrzzCtJLcpLzFFILC5OLSrJzM9TSEvMzCktSgUAiSkKPg,
// bun 1.3.12; full bisection in BUNPANIC_TRIAGE.md). Root cause: the dropdown file mounted a real
// reconciler root at module top level and never unmounted it, so it stayed alive for the rest of
// the `bun test` process; combined with the other file mounting+unmounting its own real root in
// the same process, the interaction tripped Bun's internal assertion at exit. That teardown gap
// is now fixed (afterAll(() => handle.unmount())) -- the pair, the full screens/ dir, and the
// full 209-file suite all run clean with zero panics.
//
// Reviewer correction (P1-1): keeping the two files listed here after the cure INVERTS the
// backstop. verdict()'s quarantine branch only fires for a clean-summary-then-nonzero-exit run;
// if this list still named them, a FUTURE regression that reintroduces the exact same panic in
// either file would be silently reclassified QUARANTINE-PASS instead of failing the gate -- the
// opposite of a regression backstop. The list stays empty so ANY file hitting that panic shape,
// including these two, is RED by default; see gate-classifier.test.ts's recurrence-regression
// case, which asserts exactly this for an unlisted file.
export const QUARANTINE: readonly string[] = [];
