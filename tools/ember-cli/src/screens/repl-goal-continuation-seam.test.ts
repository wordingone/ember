// screens/repl-goal-continuation-seam.test.ts — integration-level regression
// test for ember #276 ("goal-mode continuation never fires on the compiled
// binary"). Live acceptance leg (b) found: /goal <objective> persists a goal
// (status Active) and then NOTHING fires for a 30-minute wall cap -- zero
// /slots activity, continuationTurnsObserved: 0 -- even though the wiring
// unit tests (core/goal-continuation-wiring.test.ts) are green. This is
// exactly the "unit-green != functional on the real binary" class the live
// leg exists to catch: that file only drives the pure wiring function with a
// synthetic getEligibilitySignals; it never touches the REAL turn loop's
// timing.
//
// This harness mirrors screens/repl.ts's actual turn-exit sequence for the
// slash-command path (submitPrompt's `if (slashResult !== null) {...}` early
// return, repl.ts lines ~866-884) using the REAL production modules: real
// usePromptInput, real useInput/_deliverKeyEvent through the real ink
// reconciler (so the REAL scheduling behavior applies -- see
// ink/app-resize.test.ts's finding that this custom host config needs a real
// event-loop turn, not just promise microtask ticks, to flush a pending
// setState), the real command registry's real /goal command, the real
// slash-dispatch service, and the real goal-continuation engine + wiring.
// Only the model turn itself (startTurn) is a recorder instead of a real
// QueryEngine call, per the team lead's brief -- mounting the full
// ReplScreen would additionally require faking config/session/telemetry
// concerns unrelated to this seam.
//
// clearInputRefForSubmit is imported directly from screens/repl.ts (not
// reimplemented here) so this test exercises the ACTUAL fix, not a
// hand-rolled stand-in for it.

import { describe, it, expect, beforeEach, afterEach } from "bun:test";
import React, { useRef, useEffect } from "react";
import { mountInk } from "../ink/reconciler.ts";
import { useInput, _deliverKeyEvent } from "../ink/hooks.ts";
import { usePromptInput } from "../components/prompt-input.ts";
import { tryDispatchSlashCommand } from "../services/slash-dispatch.ts";
import { createGoalContinuationEngine } from "../core/goal-continuation.ts";
import {
  createGoalContinuationPoke,
  isGoalContinuationFeatureEnabled,
} from "../core/goal-continuation-wiring.ts";
import {
  setGoalContinuationTrigger,
  resetGoalContinuationTriggerForTests,
} from "../commands/goal.ts";
import {
  getGoalStore,
  setGoalStoreForTests,
  resetGoalRuntimeForTests,
} from "../core/goal-runtime.ts";
import { createGoalStore, createInMemoryGoalPersistence } from "../core/goal-store.ts";
import { clearInputRefForSubmit } from "./repl.ts";

function nextMacrotask(ms = 0): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

interface HarnessProps {
  onStartTurn: (prompt: string) => Promise<void>;
}

/** Mirrors screens/repl.ts's submitPrompt slash-command branch + Enter-key
 *  handler (lines ~827-884, ~1044-1061, ~1096-1104) -- the exact seam ember
 *  #276's live acceptance leg found broken. */
function Harness({ onStartTurn }: HarnessProps): React.ReactElement {
  const [inputState, inputActions] = usePromptInput();
  const inputStateRef = useRef(inputState);
  inputStateRef.current = inputState;

  const busyRef = useRef(false);

  const engineRef = useRef(createGoalContinuationEngine());
  const pokeRef = useRef<(() => void) | null>(null);
  if (!pokeRef.current) {
    pokeRef.current = createGoalContinuationPoke({
      engine: engineRef.current,
      getStore: getGoalStore,
      getEligibilitySignals: () => ({
        featureEnabled: isGoalContinuationFeatureEnabled(),
        planMode: false,
        turnActive: busyRef.current,
        queuedUserInput: inputStateRef.current.text.length > 0,
      }),
      startTurn: onStartTurn,
    });
  }

  useEffect(() => {
    setGoalContinuationTrigger(() => pokeRef.current?.());
    return () => setGoalContinuationTrigger(null);
  }, []);

  async function submitPrompt(text: string): Promise<void> {
    busyRef.current = true;
    const slashResult = await tryDispatchSlashCommand(text, {
      sessionId: "test-session",
      mode: "bypass",
      cwd: process.cwd(),
    });
    if (slashResult !== null) {
      busyRef.current = false;
      pokeRef.current?.();
      return;
    }
    busyRef.current = false;
    pokeRef.current?.();
  }

  // Real keyboard wiring: mirrors repl.ts's main useInput handler -- plain
  // characters insert (line ~1160-1163), Enter submits (line ~1128-1136),
  // including the ember #276 fix call at the exact same point repl.ts makes
  // it (right after inputActions.setText("") clears the buffer for submit).
  useInput((input, key) => {
    if (key.return) {
      if (busyRef.current || !inputStateRef.current.text.trim()) return;
      const text = inputStateRef.current.text;
      inputActions.setText("");
      clearInputRefForSubmit(inputStateRef);
      void submitPrompt(text);
      return;
    }
    if (input && !key.ctrl && !key.meta && !key.alt) {
      inputActions.insertText(input);
    }
  });

  return React.createElement(React.Fragment, null);
}

describe("ember #276 — /goal continuation dispatch through the real turn loop", () => {
  beforeEach(() => {
    resetGoalRuntimeForTests();
    resetGoalContinuationTriggerForTests();
    setGoalStoreForTests(createGoalStore({ persistence: createInMemoryGoalPersistence() }));
  });

  afterEach(() => {
    resetGoalRuntimeForTests();
    resetGoalContinuationTriggerForTests();
  });

  it("fires a continuation turn shortly after /goal <objective> is submitted via the real keyboard path", async () => {
    const startedTurns: string[] = [];
    const onStartTurn = async (prompt: string): Promise<void> => {
      startedTurns.push(prompt);
      // /goal accepts no token-budget argument, so the created goal is
      // unbounded -- core/goal-continuation-wiring.ts's poke() self-chains
      // (re-invokes itself) after every fired turn by design (ember #211),
      // which would otherwise spin forever since this fake startTurn never
      // advances any budget. Clearing the goal here bounds the chain to
      // exactly the one turn this test needs to prove fired.
      getGoalStore().clear();
    };

    const stream = { write() {} };
    mountInk(React.createElement(Harness, { onStartTurn }), {
      stream,
      stdout: { columns: 80, rows: 24 },
    });

    // Type "/goal reach the summit" one keystroke at a time, exactly like a
    // real terminal delivers it, then press Enter -- both routed through the
    // REAL stdin-bridge entry point (_deliverKeyEvent), never a direct
    // function call into repl logic.
    for (const ch of "/goal reach the summit") {
      _deliverKeyEvent(ch, {});
    }
    await nextMacrotask(5);
    _deliverKeyEvent("return", {});

    // Give the real reconciler several real event-loop turns to settle --
    // far more than the 1-2 promise-microtask ticks submitPrompt's own
    // slash-dispatch takes, and far more than a compiled binary would need
    // in practice. Live acceptance leg (b) waited a 30-minute wall cap and
    // observed zero; this only needs to prove the fix closes the race, not
    // reproduce the full wall-clock bound.
    for (let i = 0; i < 10; i++) await nextMacrotask(10);

    expect(startedTurns.length).toBeGreaterThanOrEqual(1);
    expect(startedTurns[0]).toEqual(expect.any(String));
  });
});
