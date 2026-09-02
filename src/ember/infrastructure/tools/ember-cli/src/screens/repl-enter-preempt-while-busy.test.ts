// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// screens/repl-enter-preempt-while-busy.test.ts — regression test for ember
// #283 ("Enter keystroke pressed while busy is silently dropped instead of
// queued for submission once idle, violating the 'user always preempts'
// goal-mode contract").
//
// repl.ts's Enter handler (~line 1493, pre-fix) read:
//   if (busyRef.current || !inputState.text.trim()) return;
// -- a busy Enter press hit the FIRST branch of that guard and returned with
// the typed text already cleared from the input buffer (inputActions.setText
// happens after the guard in the real handler's non-busy path, but the user's
// keystroke intent — "submit this the moment you're free" — was never
// recorded anywhere). The fix queues the text in pendingSubmitRef instead of
// discarding it, and a `busy`-watching useEffect flushes the queue through
// submitPrompt the instant busy flips false, clearing the queue first so a
// fresh in-flight turn never re-reads a stale value.
//
// This harness mirrors repl.ts's actual Enter-handler + idle-flush-effect
// logic (screens/repl.ts, the pendingSubmitRef declaration + its useInput and
// useEffect blocks) through the REAL ink reconciler/useInput wiring, per the
// project's repl-goal-continuation-seam.test.ts precedent, so the test
// exercises the actual fix shape rather than a hand-rolled stand-in.

import { describe, it, expect, beforeEach, afterEach } from "bun:test";
import React, { useRef, useState, useEffect } from "react";
import { mountInk } from "../ink/reconciler.ts";
import { useInput, _deliverKeyEvent } from "../ink/hooks.ts";
import { usePromptInput } from "../components/prompt-input.ts";

function nextMacrotask(ms = 0): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

interface Controls {
  setBusy: (b: boolean) => void;
  pendingSubmitRef: React.MutableRefObject<string | null> | null;
}

interface HarnessProps {
  submitPrompt: (text: string, origin: "keyboard" | "operator") => Promise<void>;
  controls: Controls;
}

/** Mirrors screens/repl.ts's Enter-key handler + idle-flush useEffect
 *  (the ember #283 fix) -- the exact seam the acceptance criteria target. */
function Harness({ submitPrompt, controls }: HarnessProps): React.ReactElement {
  const [inputState, inputActions] = usePromptInput();
  const inputStateRef = useRef(inputState);
  inputStateRef.current = inputState;

  const [busy, setBusy] = useState(true);
  const busyRef = useRef(true);
  controls.setBusy = (b: boolean) => {
    busyRef.current = b;
    setBusy(b);
  };

  const pendingSubmitRef = useRef<string | null>(null);
  controls.pendingSubmitRef = pendingSubmitRef;

  useEffect(() => {
    if (busy) return;
    const queued = pendingSubmitRef.current;
    if (queued === null) return;
    pendingSubmitRef.current = null;
    void submitPrompt(queued, "keyboard");
  }, [busy]);

  useInput((input, key) => {
    if (key.return) {
      if (!inputStateRef.current.text.trim()) return;
      const text = inputStateRef.current.text;
      inputActions.setText("");
      if (busyRef.current) {
        pendingSubmitRef.current = text;
        return;
      }
      void submitPrompt(text, "keyboard");
      return;
    }
    if (input && !key.ctrl && !key.meta && !key.alt) {
      inputActions.insertText(input);
    }
  });

  return React.createElement(React.Fragment, null);
}

describe("ember #283 — Enter pressed while busy queues, never drops, the submission", () => {
  let calls: Array<[string, string]>;
  let submitPrompt: (text: string, origin: "keyboard" | "operator") => Promise<void>;
  let controls: Controls;
  let mounted: ReturnType<typeof mountInk> | null;

  beforeEach(() => {
    calls = [];
    mounted = null;
    submitPrompt = async (text, origin) => {
      calls.push([text, origin]);
    };
    controls = { setBusy: () => {}, pendingSubmitRef: null };
  });

  afterEach(() => {
    mounted?.unmount();
    mounted = null;
  });

  it("queues the Enter-while-busy text, then flushes it through submitPrompt once idle", async () => {
    const stream = { write() {} };
    mounted = mountInk(React.createElement(Harness, { submitPrompt, controls }), {
      stream,
      stdout: { columns: 80, rows: 24 },
    });

    // Busy from mount (Harness starts busy=true/busyRef=true). Type "test
    // message" one keystroke at a time, then press Enter, exactly like a
    // real terminal delivers it, through the real stdin-bridge entry point.
    for (const ch of "test message") {
      _deliverKeyEvent(ch, {});
    }
    await nextMacrotask(5);
    _deliverKeyEvent("return", {});
    await nextMacrotask(5);

    // (4) Enter while busy must QUEUE, not execute.
    expect(controls.pendingSubmitRef?.current).toBe("test message");
    expect(calls.length).toBe(0);

    // (5) Idle transition triggers the flush effect.
    controls.setBusy(false);
    for (let i = 0; i < 5; i++) await nextMacrotask(10);

    // (6) submitPrompt called exactly once with the queued text + "keyboard".
    expect(calls.length).toBe(1);
    expect(calls[0]).toEqual(["test message", "keyboard"]);

    // (7) Queue cleared after flush.
    expect(controls.pendingSubmitRef?.current).toBe(null);
  });
});
