// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// operator-input.test.ts — pure queue/injection semantics, no ink/React/IPC.

import { describe, test, expect } from "bun:test";
import { OperatorInjector } from "./operator-input.ts";

function makeHarness(initialBufferEmpty: boolean) {
  const submitted: Array<{ text: string; origin: string }> = [];
  const setTextCalls: string[] = [];
  let bufferEmpty = initialBufferEmpty;
  let busy = false;

  const injector = new OperatorInjector({
    canInjectNow: () => bufferEmpty && !busy,
    setText: (t) => setTextCalls.push(t),
    submit: (text, origin) => submitted.push({ text, origin }),
  });

  return {
    injector,
    submitted,
    setTextCalls,
    setBufferEmpty: (v: boolean) => { bufferEmpty = v; },
    setBusy: (v: boolean) => { busy = v; },
  };
}

describe("OperatorInjector", () => {
  test("buffer empty -> line is injected into the input state and submitted immediately", () => {
    const h = makeHarness(true);
    const result = h.injector.handleLine("hello from the operator");

    expect(result).toBe("injected");
    expect(h.setTextCalls).toEqual(["hello from the operator"]);
    expect(h.submitted).toEqual([{ text: "hello from the operator", origin: "operator" }]);
    expect(h.injector.queueLength).toBe(0);
  });

  test("injected submission carries the operator origin tag", () => {
    const h = makeHarness(true);
    h.injector.handleLine("tagged line");
    expect(h.submitted[0]!.origin).toBe("operator");
  });

  test("blank / whitespace-only lines are ignored, never injected or queued", () => {
    const h = makeHarness(true);
    expect(h.injector.handleLine("   ")).toBe("ignored");
    expect(h.injector.handleLine("")).toBe("ignored");
    expect(h.submitted.length).toBe(0);
    expect(h.injector.queueLength).toBe(0);
  });

  test("keyboard/pipe interleave: nonempty input buffer delays pipe injection until it empties", () => {
    const h = makeHarness(false); // user is mid-keystroke — buffer nonempty

    const result = h.injector.handleLine("queued while typing");
    expect(result).toBe("queued");
    expect(h.submitted.length).toBe(0);
    expect(h.injector.queueLength).toBe(1);

    // Still typing — flush() must not inject while the gate stays closed.
    h.injector.flush();
    expect(h.submitted.length).toBe(0);
    expect(h.injector.queueLength).toBe(1);

    // Buffer empties (user finished / cleared their line) — flush injects it.
    h.setBufferEmpty(true);
    h.injector.flush();
    expect(h.submitted).toEqual([{ text: "queued while typing", origin: "operator" }]);
    expect(h.injector.queueLength).toBe(0);
  });

  test("a turn in flight (busy) also delays injection even with an empty buffer", () => {
    const h = makeHarness(true);
    h.setBusy(true);

    const result = h.injector.handleLine("wait for the turn to finish");
    expect(result).toBe("queued");

    h.injector.flush();
    expect(h.submitted.length).toBe(0);

    h.setBusy(false);
    h.injector.flush();
    expect(h.submitted).toEqual([{ text: "wait for the turn to finish", origin: "operator" }]);
  });

  test("multiple queued lines drain one at a time, in arrival order", () => {
    const h = makeHarness(false);
    h.injector.handleLine("first");
    h.injector.handleLine("second");
    h.injector.handleLine("third");
    expect(h.injector.queueLength).toBe(3);

    h.setBufferEmpty(true);
    h.injector.flush();
    expect(h.submitted.map((s) => s.text)).toEqual(["first"]);
    expect(h.injector.queueLength).toBe(2);

    // Simulate the buffer clearing again after the first submit's echo settles.
    h.injector.flush();
    expect(h.submitted.map((s) => s.text)).toEqual(["first", "second"]);
    expect(h.injector.queueLength).toBe(1);

    h.injector.flush();
    expect(h.submitted.map((s) => s.text)).toEqual(["first", "second", "third"]);
    expect(h.injector.queueLength).toBe(0);
  });

  test("flush() on an empty queue is a no-op", () => {
    const h = makeHarness(true);
    h.injector.flush();
    expect(h.submitted.length).toBe(0);
  });
});
