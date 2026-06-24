# Heartbeat runner — deterministic round-lifecycle machine (spec seed v0)

Per user direction 2026-06-12: ember's round behavior should be enforced by an
ember-NATIVE mechanism with workflow-file semantics — deterministic control flow,
schema-validated phase transitions, heartbeat receipts — not by coordinator
sessions driving each step by hand. The session layer becomes an exception
handler; the runner is the breathing.

## Framing (why this is the project, not plumbing)

The runner is the fixed interpreter; round configs + the preregistered decide()
are encoded state it executes. Control flow never lives in a model; models only
fill schema-shaped holes (probe outputs, eval artifacts) that the runner
validates fail-closed. This is the same enforcement insight as the agent-workflow
.js layer (deterministic phases + schema-validated outputs), applied to the
bounded training run itself.

## Phase machine (one round)

IDLE -> DISPATCH -> RUN -> TERMINAL -> PROBE -> GATES -> DECIDE -> {NEXT | HALT}

- **DISPATCH**: governed launch only — VRAM fraction cap, margin assert, pacing
  params injected from the frozen config; refuse to dispatch if governor params
  absent. B-bound from the authorized envelope is a hard constant, not a config.
- **RUN**: emit heartbeat tick (jsonl: ts, phase, round, job id, rss, vram,
  last_receipt_sha) every N minutes. Ticks are consumed by the monitor session
  and the absence-detection sweep — a missing heartbeat IS the alarm.
- **TERMINAL**: the job's terminal receipt is validated against a frozen JSON
  schema (field-exact, like the existing gate field-exactness leg). Missing or
  schema-invalid receipt => HALT, never proceed.
- **PROBE**: run the preregistered probe/eval scripts; artifacts schema-validated.
- **GATES**: execute the existing prereg gate scripts (D/P instances per the
  multi-day cadence spec). The runner RUNS them; it never reinterprets them.
- **DECIDE**: execute the preregistered decide() exactly as frozen. The runner
  encodes no judgment — accumulate/rollback/halt comes out of decide(), or HALT
  on any error.
- **NEXT / HALT**: NEXT re-enters DISPATCH for the next authorized round inside
  the frozen sequence. HALT writes a halt receipt + flag file and mails the
  coordinator; no self-recovery beyond idempotent retry of pure reads.

## Hard rails (non-negotiable)

1. **Scope-frozen:** the runner executes the authorized sequence only. Any state
   outside the frozen envelope (round count, B-bound, config hash mismatch) =>
   HALT. Extending the envelope requires explicit user GO — the runner has no
   verb for it.
2. **Fail-closed everywhere:** absent receipt, schema mismatch, governor
   violation, heartbeat write failure => HALT. No fix-forward.
3. **Receipts-only:** every transition appends a receipt; the chain must be
   reconstructable from receipts alone (portable-chain bar).
4. **Native process** (daemon-adjacent launch pattern); no bash-fork chains.
5. **Verdict boundary:** gate verdicts remain the prereg scripts' outputs +
   coordinator signoff; the runner is transport and enforcement, never judgment.

## AC (implementation issue)

- Simulated full round on mock receipts traverses all phases, receipts complete.
- Fault injection: (a) corrupt terminal receipt, (b) missing probe artifact,
  (c) governor param stripped, (d) heartbeat write blocked — each => HALT +
  halt receipt + mail, within one tick period.
- Soak: first real post-GO round runs under the runner with zero manual phase
  pushes; coordinator touches it only at signoff points.

## Sequencing

Implementation = eng item AFTER the held v0 launch action (the held chain is
frozen; this wraps the multi-day phase that follows it). Spec ownership:
coordinator. Monitor integration: the existing run-tick consumes heartbeat ticks
unchanged (same jsonl shape).
