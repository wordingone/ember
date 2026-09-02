# Spec — Surface #6: inline fireball cognitive-mode indicator + `/observatory`

Status: OPEN (0 implementation in src as of 2026-06-29). GOAL.md surface #6 ("Signature
surfaces"): *inline fireball cognitive-mode indicator live in the running binary; then
`/observatory` mode.* This is the **cockpit** surface (operator SEES the loop's cognitive
state) — distinct from C-OBS (totality board, surface #4).

Lead-#1 tie: every surface depends on the operator seeing the loop; this makes the loop's
current cognitive mode legible at a glance, inline, during a live turn.

Implementation discipline: build from THIS spec + the listed existing modules only. Never read any predecessor
CLI. No founder/user names, and no predecessor-stack lineage (vendor names, prior-tool
identifiers, or agent dotfile directories) in code or comments.

---

## Module 1 — `cognitive-mode.ts` (pure, L2 leaf, no intra-ember deps)

A cognitive mode is derived from observable loop phase, NOT invented per-token. The agent loop
already transitions through observable phases; this maps them to the operator-facing mode set.

```ts
export type CognitiveMode =
  | "observe"      // idle / awaiting operator input (ready state)
  | "orient"       // model streaming reasoning text, no tool yet
  | "act"          // a tool call is executing (Bash/Edit/etc.)
  | "verify"       // processing a tool result
  | "consolidate"  // compaction / summary in progress
  | "ask"          // awaiting an operator decision mid-turn
  | "report"       // final assistant response being emitted
  | "rollback";    // an error/abort is being recovered

/** Observable loop phase the cockpit can witness without model introspection. */
export type LoopPhase =
  | "idle" | "streaming_text" | "tool_call" | "tool_result"
  | "compacting" | "awaiting_input" | "final_response" | "error";

/** Pure mapping. Total over LoopPhase (no default-throw); unknown → "observe". */
export function deriveCognitiveMode(phase: LoopPhase): CognitiveMode;

/** Glyph + label + ANSI color hint for a mode. The "fireball" is the glyph for active modes. */
export interface ModeGlyph { glyph: string; label: string; color: "red"|"yellow"|"green"|"cyan"|"magenta"|"gray"; }
export function modeGlyph(mode: CognitiveMode): ModeGlyph;
```

**Mapping (AC1):** idle→observe, streaming_text→orient, tool_call→act, tool_result→verify,
compacting→consolidate, awaiting_input→ask, final_response→report, error→rollback.

**Glyphs (AC2):** active "thinking/working" modes (orient, act, verify, consolidate) use the
fireball glyph `🔥` (fallback `*` when `EMBER_ASCII=1`); observe→`○` gray, ask→`?` magenta,
report→`✓` green, rollback→`⚠` red. Each `modeGlyph` returns a non-empty glyph+label; color per
the table. `EMBER_ASCII=1` forces ASCII-only glyphs (AC3) for non-unicode terminals.

## Module 2 — status-bar integration (`components/status-bar.ts`)

The status bar renders the current fireball + mode label inline (e.g. `🔥 act` / `○ observe`).
- **AC4:** a `renderModeIndicator(mode: CognitiveMode, ascii: boolean): string` helper returns
  `"<glyph> <label>"`; under `ascii=true` contains no codepoint > 0x7F.
- **AC5:** status-bar accepts a `cognitiveMode` prop and shows the indicator; absent prop →
  defaults to `observe` (never blank, never crash).

## Module 3 — `/observatory` slash command (`commands/observatory.ts` + registry)

A slash command that shows the loop's recent cognitive-mode timeline and current state.
- **AC6:** registered in `command-registry.ts` under name `observatory` (alias `obs`).
- **AC7:** `runObservatory(history: CognitiveMode[]): string` returns a multi-line view:
  a header line, the current mode (last entry), and a compact timeline of the last N (≤20)
  modes as glyphs; empty history → a "no activity yet" line (never crash).
- **AC8:** output contains the current mode label and is deterministic for a given history
  (no time/random — testable).

## Wiring (Module 4 — loop → indicator, non-GPU testable)

- **AC9:** the loop publishes its `LoopPhase` to app-state on each transition via a setter
  `setLoopPhase(phase)`; a getter `getCognitiveMode()` returns `deriveCognitiveMode` of the
  latest phase. State lives in `state/app-state.ts` (already tracked). No model call required to
  test — drive `setLoopPhase` directly.
- **AC10:** `/observatory` reads the mode history accumulated by `setLoopPhase` (bounded ring,
  ≤100 entries; eviction keeps newest, mirroring telemetry's eviction rule).

## Tests (test=spec; all CPU-only, no model/GPU)

`cognitive-mode.test.ts`, `status-bar` indicator tests, `observatory.test.ts`, and an
app-state phase/history test. Every AC above gets ≥1 assertion. The suite must stay green
(current baseline 1887 pass / 1 fail = process-entry AC1/#37) and tsc=0.

## Live receipt (separate, GPU-gated — NOT part of this build)

"live in the running binary" = the fireball visibly changes mode across a real qwen3.6-27b turn.
That confirmation rides the next GPU window (after keystone #60), via the surface-#1 live cockpit
harness. This spec delivers the unit+render-green implementation; the live receipt is logged
against surface #6 when GPU frees.
