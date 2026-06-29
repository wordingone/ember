# Spec — model load/unload toggle: free the GPU without closing the cockpit (task #58)

Status: OPEN. Enables the GPU-gated live receipts for surfaces #1/#2 (and the C-GROW/#60
co-residency): the operator must be able to UNLOAD the local model from the running cockpit to
free VRAM for a training run, then RELOAD it — without killing the cockpit. Memory basis:
"cockpit always-visible; toggle frees GPU; never mono-focus".

Implementation discipline: build from THIS spec + the listed existing modules only. Never read any predecessor
CLI. No founder/user names, and no predecessor-stack lineage (vendor names, prior-tool
identifiers, or agent dotfile directories) in code, comments, or strings.

## Existing surface (read first, do not rewrite)
- `entrypoints/process-entry.ts` — the boot path; spawns the local model binary via
  `child_process.spawn` (3 sites). External-client mode: when `EMBER_MODEL_URL` is set the managed
  spawn is SKIPPED (lines ~541-578) — the cockpit talks to a server it does not own.
- `services/runtime-bootstrap.ts` — `waitForServerReady(port, timeoutMs)` polls `/health` until
  `{status:"ok"}`; `LLAMA_SERVER_DEFAULT_PORT = 8081`.
- `model-config.ts` — `LOCAL_MODEL_ID = "qwen-3.6"`, capability queries.
- `command-registry.ts` + `commands/*.ts` — slash-command registration pattern (observatory/watch/
  finetune already registered in `defaultDeps.getBuiltinCommands`; ADD alongside, never replace).
- Kill discipline (repo rule): killing a process writes a receipt FIRST and kills only a verified
  PID this session spawned — never by name/pattern.

> **Coordination:** touches `command-registry.ts`. Do not run concurrently with another build that
> edits the registry; dispatch when the registry is free.

---

## Module 1 — `services/model-lifecycle.ts` (managed-process manager, CPU-testable via injection)

The boot path currently spawns the model and forgets the handle. This module OWNS the handle so it
can be unloaded/reloaded later. All process effects are injected so the module is fully testable
without a real process or GPU.

```ts
export type ModelState = "unloaded" | "loading" | "loaded" | "external";

export interface ManagedModelHandle { pid: number; }           // minimal; what we must track to kill

export interface ModelLifecycleDeps {
  spawnModel: () => ManagedModelHandle;        // injected; real impl wraps the process-entry spawn
  killPid: (pid: number) => void;              // injected; real impl = process.kill(pid)
  waitReady: (port?: number) => Promise<void>; // injected; real impl = waitForServerReady
  writeKillReceipt: (rec: { pid: number; match_rule: string }) => void; // injected; appends JSONL
  isExternal: () => boolean;                    // true when EMBER_MODEL_URL is set
  now: () => string;                            // injected ISO clock (no Date.now() inside)
}

export function getModelState(): ModelState;
/** Wire the boot-spawned handle in so it can be unloaded later. No-op in external mode. */
export function registerManagedModel(handle: ManagedModelHandle): void;
/** Kill the tracked PID (receipt FIRST), set state "unloaded". Returns a one-line status. */
export async function unloadModel(deps: ModelLifecycleDeps): Promise<string>;
/** Spawn + waitReady, set state "loaded". Returns a one-line status. */
export async function loadModel(deps: ModelLifecycleDeps): Promise<string>;
export function resetModelLifecycleForTests(): void;
```

- **AC1:** initial `getModelState()` is `"unloaded"` (or `"external"` when `isExternal()` true).
- **AC2:** `registerManagedModel({pid})` sets state `"loaded"` and stores the pid; in external mode
  it is a no-op and state stays `"external"`.
- **AC3:** `unloadModel` in `"loaded"` state: calls `writeKillReceipt` with the tracked pid and a
  match_rule naming it as the model child spawned this session, THEN calls `killPid(pid)` (receipt
  strictly before kill — assert call order), sets state `"unloaded"`, returns e.g. `model unloaded (pid <n> freed)`.
- **AC4:** `unloadModel` when already `"unloaded"` is idempotent (no kill, no receipt) and returns a
  clear `model already unloaded` line. In `"external"` state it NEVER kills and returns
  `external model (EMBER_MODEL_URL) — not managed, nothing to unload`.
- **AC5:** `loadModel` in `"unloaded"` state: sets `"loading"`, calls `spawnModel`, registers the
  handle, `await waitReady(port)`, sets `"loaded"`, returns `model loaded (pid <n>)`. If `waitReady`
  rejects, state returns to `"unloaded"` (not stuck in `"loading"`) and the error is surfaced, not swallowed.
- **AC6:** `loadModel` when already `"loaded"` is idempotent (no second spawn). In `"external"` state
  it never spawns and returns the external-not-managed line.
- **AC7:** never kills by name/pattern — only the exact tracked pid; in external mode `killPid` is
  never called (assert).

## Module 2 — `/model` slash command (`commands/model.ts` + registry)

- **AC8:** registered in `command-registry.ts` as `model` (no alias collision with existing
  observatory/watch/finetune). Wired into `defaultDeps.getBuiltinCommands` ALONGSIDE the existing
  entries — do not remove them.
- **AC9:** `/model status` returns the current `ModelState` + pid (if loaded) — never crashes.
- **AC10:** `/model unload` calls `unloadModel`, `/model load` calls `loadModel`, returning their
  one-line status. Unknown subcommand → a clear usage line, no effect. External mode → the
  not-managed line for load/unload; status still reports `"external"`.

## Boot wiring (Module 3 — capture the handle, non-GPU testable)
- **AC11:** the boot path, after its managed spawn, calls `registerManagedModel({pid})` with the
  spawned child's pid so the lifecycle manager can later unload it. In external mode boot does NOT
  register (state stays `"external"`). Test by driving `registerManagedModel` directly with a fake
  pid + an `isExternal` stub — no real spawn required.

## Tests (test=spec; all CPU-only, no model/GPU/training)
`model-lifecycle.test.ts`, `model.test.ts`. Every AC ≥1 assertion. Inject all of `ModelLifecycleDeps`
with fakes: `spawnModel` returns `{pid: 4242}`; `killPid`/`writeKillReceipt`/`waitReady` are spies;
`isExternal` toggled per-case; `now` returns a fixed ISO string. Assert the receipt-before-kill
ORDER (AC3) and the external no-kill invariant (AC7). Suite stays green (baseline = whatever it is at
dispatch; the only allowed pre-existing fail is process-entry AC1/#37) and tsc=0.

## Live receipt (separate, GPU-gated — NOT part of this build)
"frees the GPU" = on `/model unload`, `nvidia-smi` shows the model's VRAM released while the cockpit
stays alive; `/model load` brings it back and a real qwen3.6-27b turn renders. That confirmation
rides the next GPU window (after keystone #60), folded with the surface-#1 cockpit + surface-#2
steerable live receipts (the toggle is the mechanism that lets the cockpit and a training run share
the single GPU). This spec delivers the unit-green managed-lifecycle + command; the live VRAM-free
receipt is logged against #58 when GPU frees.
