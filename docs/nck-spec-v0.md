# NC-K kernel rung — spec v0 (#34)

Trigger condition satisfied: the GOAL annex opens NC-K detail-design when
the NC0 verdict lands; the round-1 record completed 2026-06-10 (G1 paired
verdict + t5; GRPO arm completing under #24). v0 scope: single machine,
single kernel process, design only — implementation issues are minted from
this spec, it launches nothing.

## What NC-K is

The harness organ: a RESIDENT event-driven loop (not a request-response
REPL) that thinks continuously over its event stream and recruits bounded
deep bursts (GPU sampling/training/eval through the train-daemon). The
capability claim of the goal lives in the model × harness PAIR; NC-K is
the harness half, version-controlled and self-editable behind the
invariant gate. Seed = avir-cli compressed to its invariants, not adopted
wholesale.

## Process shape (v0)

- **Kernel process**: single long-lived process, event loop over sources:
  (1) mailbox watcher, (2) filesystem events on registered paths, (3)
  train-daemon job terminals (poll :8787; receipts are the payload), (4)
  schedule ticks, (5) user chat as ONE source among the five — the user
  talks to a thing already mid-thought.
- **Emission is selective**: most events update state silently; tool
  calls/messages fire on judgment, not per event (constant thinking,
  episodic depth — the annex's allocation principle).
- **Deep bursts are delegated, never in-process**: the kernel holds no
  CUDA context; all GPU work goes through the train-daemon API, which
  applies governor preflight server-side. This is enforcement by
  CHOKEPOINT, not by convention (invariant 2 below).

## Write surface and promotion

- Ember's editable tree: `kernel/` (its own code), `state/` (its working
  memory), `ledger/` (append-only episodes). Everything else is outside
  the write surface.
- **Harness edit = artifact, same gate as a weight delta**: branch →
  harness test suite (deterministic selftests + replay of recorded event
  traces) → invariant checks → promotion receipt → fast-forward of the
  serving branch. Precedent: Darwin Gödel Machine (self-rewriting agent
  code, empirically gated, FIXED outer evaluation loop — the outer loop is
  exactly what the invariant layer keeps fixed here).
- **Deletion test on harness edits**: re-run the suite + the motivating
  workload with the edit reverted; the claimed gain must disappear.
  Promotion receipts without a deletion-test entry are invalid (schema).

## The five un-removable invariants — each with its enforcement MECHANISM

| # | Invariant | Mechanism (named, not prose) |
|---|---|---|
| 1 | Three-test gain gate (held-out transfer, matched control, deletion) | Gate scripts live OUTSIDE the write surface (`infra/ember-invariants/`); kernel invokes via subprocess; the promote script — the only path that can fast-forward the serving branch (git pre-push hook rejects all other pushers) — requires a gate receipt path and validates its schema + checksum before promoting |
| 2 | Resource governor + headroom | Chokepoint: kernel has no process-spawn primitive except the train-daemon client; the daemon applies `governor.preflight()` server-side on every job (VRAM fraction cap, margin assert, pacer); kernel process itself runs at below-normal OS priority with no CUDA libs importable (absent from its venv) |
| 3 | GOAL.md + only-the-user-retires | `GOAL.md` in the protected-paths manifest: filesystem ACL write-denied to the kernel user; boot-time sha256 check against the user-held manifest copy; mismatch = refuse to boot (fail-closed) |
| 4 | Receipts-only truth | Structural: the state-transition function (in the protected manifest) REQUIRES a receipt file reference per transition and schema-validates it; transitions without receipts throw — there is no prose-only path to a state change |
| 5 | The enforcement layer itself | Self-referential manifest: the checksum manifest, the boot checker, and the promote script are LISTED IN the manifest; the reference copy lives outside the write surface in a user-owned directory; the boot checker verifies itself first from that copy |

## Timescales (interface only; mechanism spec = #35)

KV/context (continuous, free) → consolidation events (periodic, the #35
spec decides triggers and what burns) → durable merges (rare, full
three-test gate + t5-class harm gate). The kernel emits CANDIDATE
consolidation events; whether anything burns is #35's gate chain.

## avir-cli compression list (the seed, extract-not-adopt)

Process supervision (job spawn/track/kill), hook dispatch (pre/post tool
gates — the pattern the stop-gate and forbid-exit-ramp hooks already
prove), state persistence (resume-from-disk), tool dispatch registry.
Excluded: the chat REPL as interface (becomes one event source), all
cloud-model dependencies (scaffolding by goal definition).

## v0 acceptance + named follow-ons

This spec's AC (every invariant mechanism-named) is met above. Follow-on
issues to mint when NC-K implementation opens: kernel event-loop skeleton
(eng), protected-paths manifest + boot checker (eng+logic — first `logic`
customer: a correctness argument that the checker's self-verification is
not circular given the user-held copy), harness test suite + trace replay
(eng), promote script + pre-push hook (eng). Implementation does NOT
preempt the accumulation track (annex rule) — wait-window work.
