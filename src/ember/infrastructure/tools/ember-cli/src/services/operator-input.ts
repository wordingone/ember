// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// operator-input.ts — keyboard-priority queueing for operator-originated prompt lines.
// Transport-agnostic (no net/IPC/focus APIs here — see operator-pipe.ts for the
// Windows named-pipe transport this composes with). Pure logic so it is testable
// without ink/React or a live pipe.
//
// Semantics (ember issue #165 / #154): the keyboard always retains priority. A line
// arriving while the caller reports "cannot inject now" (nonempty input buffer, or a
// turn already in flight) is queued in arrival order; the next call to flush() after
// the gate opens injects exactly one queued line.

export type OperatorLineOrigin = "operator";

export interface OperatorInjectorDeps {
  /** Returns true when it is safe to inject + submit right now (buffer empty, not busy). */
  canInjectNow: () => boolean;
  /** Sets the visible input-line text — mirrors what a keystroke would have produced. */
  setText: (text: string) => void;
  /** Submits the given text exactly as Enter would, tagged with its origin. */
  submit: (text: string, origin: OperatorLineOrigin) => void;
}

export type OperatorLineResult = "injected" | "queued" | "ignored";

/**
 * Queues operator-originated lines while the keyboard has priority, and injects
 * them into the input buffer + submits exactly as typed text once the buffer is
 * clear. One line in flight at a time — never interleaves characters with the
 * keyboard.
 */
export class OperatorInjector {
  private readonly deps: OperatorInjectorDeps;
  private readonly _queue: string[] = [];

  constructor(deps: OperatorInjectorDeps) {
    this.deps = deps;
  }

  /** Number of operator lines currently queued (not yet injected). */
  get queueLength(): number {
    return this._queue.length;
  }

  /**
   * Called for each line arriving on the operator transport. Empty/whitespace-only
   * lines are ignored (mirrors the keyboard-submit guard against blank prompts).
   */
  handleLine(line: string): OperatorLineResult {
    if (line.trim().length === 0) return "ignored";

    if (this.deps.canInjectNow()) {
      this._inject(line);
      return "injected";
    }

    this._queue.push(line);
    return "queued";
  }

  /**
   * Called whenever the gate might have opened (buffer emptied, turn completed).
   * Injects at most one queued line per call — the resulting submit will itself
   * clear the buffer and trigger the next flush.
   */
  flush(): void {
    if (this._queue.length === 0) return;
    if (!this.deps.canInjectNow()) return;

    const line = this._queue.shift()!;
    this._inject(line);
  }

  private _inject(line: string): void {
    this.deps.setText(line);
    this.deps.submit(line, "operator");
  }
}
