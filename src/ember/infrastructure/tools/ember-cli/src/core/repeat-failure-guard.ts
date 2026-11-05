// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// core/repeat-failure-guard.ts -- stops a model from looping on one failing tool call.
//
// Small local models often re-issue the exact call that just failed (observed: a
// 4B model repeated one failing Write seven times). The guard counts failures per
// (tool name, exact input). After the 2nd identical failure it appends a nudge to
// the error so the model changes course; from the 4th it refuses to run the call
// again and says so, so the turn ends with an explanation instead of burning the
// whole turn budget.

export const NUDGE_AFTER = 2;
export const BLOCK_AFTER = 4;

function signature(name: string, input: unknown): string {
  let s: string;
  try {
    s = JSON.stringify(input);
  } catch {
    s = String(input);
  }
  return `${name}\u0000${s}`;
}

export class RepeatFailureGuard {
  private failures = new Map<string, number>();

  /** A blocking message when this exact call has already failed too often, else null. */
  shouldBlock(name: string, input: unknown): string | null {
    const n = this.failures.get(signature(name, input)) ?? 0;
    if (n < BLOCK_AFTER - 1) return null;
    return (
      `[ember] Not running ${name} again: this exact call has already failed ${n} times with the same input. ` +
      `Use different input or a different tool, or tell the user what is blocking you.`
    );
  }

  /** Record the outcome; returns the (possibly annotated) result content. */
  record(name: string, input: unknown, isError: boolean, content: string): string {
    const key = signature(name, input);
    if (!isError) {
      this.failures.delete(key);
      return content;
    }
    const n = (this.failures.get(key) ?? 0) + 1;
    this.failures.set(key, n);
    if (n < NUDGE_AFTER) return content;
    return (
      `${content}\n\n[ember] This exact ${name} call has now failed ${n} times with the same input. ` +
      `Repeating it will fail again: change the input, try another approach, or explain the blocker.`
    );
  }
}
