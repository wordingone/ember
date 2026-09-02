// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// screens/repl-input-burst-race.test.ts — regression test for ember #251 ("Input race: full
// line + Enter in one synchronous write burst is silently dropped").
//
// Root cause (docs/domains/governance/verification/receipts-20260706/chat-input-race-repro.md isolated the repro;
// this test isolates the mechanism): a real terminal write() carrying a full line plus its
// trailing Enter decodes, via readline's keypress parser in ink/stdin-bridge.ts, into several
// `_deliverKeyEvent` calls -- one per character, then one for Enter -- that all fire
// SYNCHRONOUSLY, in order, within the same JS turn. React never gets a chance to re-render
// between them. repl.ts's Enter handler (pre-fix) read `inputState.text` -- a plain variable
// destructured from `usePromptInput()`'s React-state return value, current only as of the last
// completed render -- so an Enter delivered in the same burst as the characters before it saw
// the buffer exactly as it was BEFORE any of them landed: empty. The `!inputState.text.trim()`
// guard then silently no-opped the entire submission. Splitting the write (characters, then
// Enter as a separate write()) gives React a render in between and masks the bug, which is why
// it read as length/word-count-related rather than a batching race.
//
// The fix (components/prompt-input.ts) adds `getSnapshot()`, backed by a ref that every mutation
// updates SYNCHRONOUSLY (before scheduling the matching `setTc`), so a same-tick reader always
// sees the fully caught-up buffer. repl.ts's Enter handler now calls `inputActions.getSnapshot()`
// instead of reading `inputState.text`.
//
// This harness mirrors repl.ts's actual Enter-handler shape (the getSnapshot() read + submit)
// through the REAL ink reconciler/useInput wiring and the REAL usePromptInput hook, per the
// project's repl-enter-preempt-while-busy.test.ts precedent -- exercising the actual production
// hook and event-delivery path, not a hand-rolled stand-in for either.

import { describe, it, expect, beforeEach, afterEach } from "bun:test";
import React, { useRef } from "react";
import { mountInk, type MountHandle } from "../ink/reconciler.ts";
import { useInput, _deliverKeyEvent } from "../ink/hooks.ts";
import { usePromptInput } from "../components/prompt-input.ts";

function nextMacrotask(ms = 0): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

interface HarnessProps {
  submitPrompt: (text: string, origin: "keyboard" | "operator") => Promise<void>;
}

/** Mirrors screens/repl.ts's post-#251-fix Enter-key handler exactly: reads the live snapshot,
 *  not the React-state-derived `inputState.text`. */
function Harness({ submitPrompt }: HarnessProps): React.ReactElement {
  const [inputState, inputActions] = usePromptInput();
  void inputState; // present only because usePromptInput returns a tuple; unused here on purpose

  const busyRef = useRef(false);

  useInput((input, key) => {
    if (key.return) {
      const live = inputActions.getSnapshot();
      if (!live.text.trim()) return;
      const text = live.text;
      inputActions.setText("");
      if (busyRef.current) return;
      void submitPrompt(text, "keyboard");
      return;
    }
    if (input && !key.ctrl && !key.meta && !key.alt) {
      inputActions.insertText(input);
    }
  });

  return React.createElement(React.Fragment, null);
}

/** Mirrors repl.ts's PRE-#251-fix Enter-key handler: reads `inputState.text` (React-state-
 *  derived, current only as of the last completed render) instead of a live snapshot. Kept as a
 *  fossil-of-the-bug control -- it must still fail the burst case below, proving the harness
 *  genuinely discriminates the two shapes rather than passing regardless of which one is used. */
function PreFixHarness({ submitPrompt }: HarnessProps): React.ReactElement {
  const [inputState, inputActions] = usePromptInput();
  const busyRef = useRef(false);

  useInput((input, key) => {
    if (key.return) {
      if (!inputState.text.trim()) return;
      const text = inputState.text;
      inputActions.setText("");
      if (busyRef.current) return;
      void submitPrompt(text, "keyboard");
      return;
    }
    if (input && !key.ctrl && !key.meta && !key.alt) {
      inputActions.insertText(input);
    }
  });

  return React.createElement(React.Fragment, null);
}

describe("ember #251 — a full line + Enter delivered as one synchronous burst is not dropped", () => {
  let calls: Array<[string, string]>;
  let submitPrompt: (text: string, origin: "keyboard" | "operator") => Promise<void>;
  // Every mounted tree registers its `useInput` handler in ink/hooks.ts's MODULE-LEVEL
  // `_inputHandlers` array (see hooks.ts's `_deliverKeyEvent`) -- without an explicit unmount
  // between tests, a prior test's handler stays registered and double/triple-delivers every
  // subsequent test's `_deliverKeyEvent` calls to it too, corrupting `calls` across tests.
  let handle: MountHandle | null;

  beforeEach(() => {
    calls = [];
    handle = null;
    submitPrompt = async (text, origin) => {
      calls.push([text, origin]);
    };
  });

  afterEach(async () => {
    // unmount()'s effect cleanups (which remove this test's handler from ink/hooks.ts's
    // module-level `_inputHandlers`) run as passive effects, not synchronously -- a macrotask
    // boundary is needed before the NEXT test's `_deliverKeyEvent` calls stop reaching this
    // test's now-unmounted handler too (observed: without this, the next test received 2x the
    // expected submissions from both the old and new mounted trees' handlers).
    handle?.unmount();
    handle = null;
    await nextMacrotask(5);
  });

  it("negative control: the PRE-fix shape (reads inputState.text) silently drops the same burst", async () => {
    const stream = { write() {} };
    handle = mountInk(React.createElement(PreFixHarness, { submitPrompt }), {
      stream,
      stdout: { columns: 80, rows: 24 },
    });

    const message = "Reply with exactly the single word: PONG";
    for (const ch of message) {
      _deliverKeyEvent(ch, {});
    }
    _deliverKeyEvent("return", {});
    await nextMacrotask(5);

    // This is the #251 defect, reproduced: zero submissions, the line is silently gone.
    expect(calls.length).toBe(0);
  });

  it("submits the full line when every character AND Enter fire in the same synchronous tick", async () => {
    const stream = { write() {} };
    handle = mountInk(React.createElement(Harness, { submitPrompt }), {
      stream,
      stdout: { columns: 80, rows: 24 },
    });

    // The exact repro shape from docs/domains/governance/verification/receipts-20260706/chat-input-race-repro.md
    // Test 2: a full line's characters plus the trailing Enter, all delivered with NO await
    // (no macrotask boundary, no React render) between any of them -- the same synchronous burst
    // a real ptyProcess.write("...text...\r") call produces via readline's keypress decoder.
    const message = "Reply with exactly the single word: PONG";
    for (const ch of message) {
      _deliverKeyEvent(ch, {});
    }
    _deliverKeyEvent("return", {});

    // Only now does control return to the event loop and React gets to render.
    await nextMacrotask(5);

    expect(calls.length).toBe(1);
    expect(calls[0]).toEqual([message, "keyboard"]);
  });

  it("control: the same message split into characters-then-Enter (a render boundary between them) also submits correctly", async () => {
    const stream = { write() {} };
    handle = mountInk(React.createElement(Harness, { submitPrompt }), {
      stream,
      stdout: { columns: 80, rows: 24 },
    });

    const message = "hi";
    for (const ch of message) {
      _deliverKeyEvent(ch, {});
    }
    await nextMacrotask(5); // render boundary -- this is the split-write case that always worked
    _deliverKeyEvent("return", {});
    await nextMacrotask(5);

    expect(calls.length).toBe(1);
    expect(calls[0]).toEqual([message, "keyboard"]);
  });

  it("a bare Enter with no preceding text is still correctly a no-op", async () => {
    const stream = { write() {} };
    handle = mountInk(React.createElement(Harness, { submitPrompt }), {
      stream,
      stdout: { columns: 80, rows: 24 },
    });

    _deliverKeyEvent("return", {});
    await nextMacrotask(5);

    expect(calls.length).toBe(0);
  });
});
