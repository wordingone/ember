# Native Fixed-Viewport TUI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the production Ember cockpit own its terminal session, accept real pointer input, keep a fixed viewport with two bounded scroll regions, render one-column contained graphs, animate a spatially stable flame, and launch as one correctly placed Windows window.

**Architecture:** Add one idempotent terminal-session controller at the real frontend root. Extend the existing SGR decoder and reconciler with typed motion/release/wheel events, then use those primitives in the cockpit rather than test-only injection. Preserve the existing renderer and control channel; change only their terminal ownership, viewport behavior, and presentation contracts.

**Tech Stack:** TypeScript, Bun, React 19, custom Ink-compatible reconciler, Windows Terminal/ConPTY, PowerShell launcher.

## Global Constraints

- Exact base: `1886adca492523e679cb0bbc7db263f6c80a8eb5`.
- Work is governed by issue #1251 and must append, not erase, corrections to #894, #54, and #565.
- No model, training, benchmark, or capability completion claim.
- Every production change follows witnessed RED then GREEN.
- Synthetic SGR injection alone is insufficient final click acceptance.
- The graph pane is one column at every supported width.
- The hardware cursor is hidden only while the TUI owns the session and restored on every exit path.

---

### Task 1: Production terminal-session ownership

**Files:**
- Create: `tools/ember-cli/src/ink/terminal-session.ts`
- Create: `tools/ember-cli/src/ink/terminal-session.test.ts`
- Modify: `tools/ember-cli/src/ink/termio.ts`
- Modify: `tools/ember-cli/src/core/frontend-shell.ts`
- Modify: `tools/ember-cli/src/core/frontend-shell.test.ts`

**Interfaces:**
- Produces: `TerminalSessionController` with idempotent `enter()` and `exit()`; `wrapTerminalSession(node)` mounted by every production render/root path.
- Emits: alternate-screen enter, native-cursor hide, SGR button/motion/wheel enable before first render; exact reverse order at cleanup.

- [ ] Add failing lifecycle tests for negotiation ordering, production-root mounting, normal cleanup, thrown cleanup, and double cleanup.
- [ ] Run the focused tests and record the expected absence/mismatch failures.
- [ ] Implement the controller and mount it once in `frontend-shell`.
- [ ] Run lifecycle and frontend-shell tests to green.
- [ ] Commit the independently reviewable terminal lifecycle increment.

### Task 2: Pointer event protocol, hover, and scoped wheel dispatch

**Files:**
- Modify: `tools/ember-cli/src/ink/termio.ts`
- Modify: `tools/ember-cli/src/ink/stdin-bridge.ts`
- Modify: `tools/ember-cli/src/ink/hooks.ts`
- Modify: `tools/ember-cli/src/ink/reconciler.ts`
- Modify: `tools/ember-cli/src/ink/mouse-input.test.ts`
- Modify: `tools/ember-cli/src/components/operator-surface-pane.ts`
- Modify: `tools/ember-cli/src/screens/repl.ts`
- Modify: `tools/ember-cli/src/screens/repl-operator-control-wiring.test.ts`

**Interfaces:**
- Produces: discriminated `SgrMouseEvent` press/release/move/wheel events with zero-based coordinates.
- Reconciler dispatches `onMouseEnter`, `onMouseMove`, `onMouseLeave`, `onWheel`, and existing `onClick` against current layout boxes.

- [ ] Add failing decoder tests for motion, release, wheel-up/down, fragmented sequences, and malformed input.
- [ ] Add failing mounted-tree tests for exact hover transitions, disabled controls, and wheel routing by hit region.
- [ ] Implement the typed event decoder, bridge, and reconciler dispatch.
- [ ] Add hovered control state/style and preserve the real control-channel action.
- [ ] Run focused pointer and control tests to green.
- [ ] Commit the pointer protocol increment.

### Task 3: Fixed viewport and two bounded scroll regions

**Files:**
- Modify: `tools/ember-cli/src/ink/components.ts`
- Modify: `src/ember/infrastructure/tools/ember-cli/src/components/app-shell.ts`
- Modify: `tools/ember-cli/src/components/operator-surface-pane.ts`
- Modify: `tools/ember-cli/src/screens/repl.ts`
- Create: `tools/ember-cli/src/screens/repl-scroll-containment.test.ts`

**Interfaces:**
- Conversation history and activity feed expose independent bounded offsets and `onWheel` handlers.
- Root chrome stays fixed and overflow-hidden; neither region delegates wheel input to terminal scrollback.

- [ ] Add failing tests with long conversation/activity histories proving independent offsets and fixed prompt/hero/charts.
- [ ] Add a failing repaint test proving no whole-frame history is appended while the alternate buffer is active.
- [ ] Implement bounded windows for conversation and activity data and attach region wheel handlers.
- [ ] Run containment and render-integrity tests to green.
- [ ] Commit the viewport increment.

### Task 4: One-column graph cards and stable flame

**Files:**
- Modify: `tools/ember-cli/src/components/operator-surface-pane.ts`
- Modify: `src/ember/infrastructure/tools/ember-cli/src/components/operator-surface-pane-responsive-cards.test.ts`
- Modify: `src/ember/infrastructure/tools/ember-cli/src/components/fireball.ts`
- Modify: `src/ember/infrastructure/tools/ember-cli/src/components/fireball.test.ts`

**Interfaces:**
- `operatorGraphColumnCount()` returns `1` for all valid widths.
- Every graph card retains continuous top/side/bottom boundaries and stable metric color.
- Every flame frame shares exact tip, base, centerline, and outer bounds while internal brightness/cells may change.

- [ ] Replace two-column and drifting-tip assertions with failing one-column/border/spatial-invariant tests.
- [ ] Run the focused tests and record the expected current-behavior failures.
- [ ] Implement minimal graph and flame changes.
- [ ] Run graph/flame tests to green across the width and frame matrix.
- [ ] Commit the presentation-contract increment.

### Task 5: Canonical Windows launcher and production verification

**Files:**
- Create or modify the canonical current Ember launcher under `scripts/` after confirming the existing launch entrypoint.
- Add a focused PowerShell contract test under `scripts/tests/` or the repository's established launcher-test surface.
- Update issue-bound documentation only if required by the executable contract.

**Interfaces:**
- Launcher enforces one Ember-owned window and verifies a left-half/full-work-area rectangle from the current monitor work area.
- Launcher never leaves a dead shell beneath the live cockpit.

- [ ] Add failing launcher-contract tests for singleton enforcement, sizing (not `SWP_NOSIZE`), postlaunch geometry readback, and stale-owned-window retirement.
- [ ] Implement the minimal canonical launcher/geometry authority.
- [ ] Run launcher tests to green.
- [ ] Run the complete focused TUI suite, typecheck, production build, diff-check, and repository guards.
- [ ] Perform a bounded ConPTY/Windows Terminal negotiation smoke and capture exact-head evidence without relaunch churn.
- [ ] Commit, push with the safe wrapper, and open the PR with issue #1251 acceptance mapping and rollback instructions.
