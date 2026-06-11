# fp-29 — kill-rule curriculum-synthesis precondition (#200)

Owner: Leo. Status: **RECONCILED** (tighten-only; no frozen file mutated).
Artifact: `scripts/fp29_kill_synthesis_gate.py` (`--selftest` / `--emit`).
Receipt: `receipts/fp29-kill-gate-20260611T125510Z.json` (RECONCILED,
`kill_requires_synthesis_receipt: true`, receipt_check clean).

## The gap

Two frozen artifacts disagreed about what must happen before the rung-kill
fires:

| Artifact | What it says |
|---|---|
| NC2-own pre-registration (STATE ladder) → fp-26 kill rule (sha `5ef7cc20…`) | kill fires only if the core misses the floor "**even with curriculum synthesis**" |
| fp-23 frozen `decide()` | KILL = 2B fail + 4B fail; the RETRY-AT-4B leg is **passive** (more tokens, no mandated intervention) |

Unreconciled, the kill — a user-escalation + fallback-demotion event — could
fire without its own named precondition ever being exercised or receipted.
That is escalation-as-exit-ramp in mechanical form: the protocol would permit
handing the work back before the wall-breaking step was attempted.

## Resolution (composition, not mutation)

`validate_kill(verdict_receipt, synthesis_receipt)` wraps fp-24's output:

- **Non-KILL verdicts → PASS-THROUGH** untouched (PASS / RETRY-AT-4B / INFO /
  PROTOCOL-VIOLATION / INVALID-RECEIPT / INCOMPUTABLE all demonstrated).
- **KILL + no synthesis receipt → KILL-REFUSED-SYNTHESIS-UNRECEIPTED.** The
  rung-kill cannot escalate. Precision (fp-22 forbids a third retry): the
  refusal does NOT authorize a third probe — it surfaces an
  execution-discipline violation to the user (the mandated lever was skipped
  in its window). fp-27 makes the synthesis MANDATORY-IN-WINDOW on a 2B
  RETRY, so this state is unreachable under correct execution.
- **KILL + malformed receipt → KILL-REFUSED-SYNTHESIS-MALFORMED** (findings
  named, fail-closed).
- **KILL + well-formed receipt → KILL-VALID** — only now may fp-24's
  escalation framing surface to the user.

**"Curriculum synthesis" pinned:** L1/L2-grammar-shaped episodes (fp-23 ops,
TRAIN buckets 10–99 only) mixed into the continued pretrain **inside the
2B→4B retry window**; probe buckets 0–9 untouched (leakage guard). Receipt
shape frozen in `SYNTHESIS_REQUIRED_FIELDS` (window literal `2B->4B`,
`episodes_generated` int>0, three literal-true asserts, ingestion-manifest
sha). The EMITTER is the continued-pretrain harness (eng track); the shape is
frozen here so the emitter binds to it, not the reverse. Synthesis credit
outside the retry window is malformed by construction.

## Why tighten-only

- Bar value (1.0), mandatory 2B leg, single retry: **unchanged** — selftest
  re-asserts the frozen constants and the live `decide()` branches.
- No new PASS path exists; only the KILL path gains a validity precondition.
  Killing gets HARDER. The floor never relaxes.
- Pins fail-closed: fp-26 decision sha + fp-23 frozen constants checked on
  every public mode; drift refuses.

## Bindings

- **fp-27 (#198, unblocked by this):** the round-1 prereg references this
  gate + receipt shape in its kill wiring.
- **fp-24 (#139 executor):** unchanged; this gate consumes its verdict
  receipts downstream.
- **eng:** the synthesis-receipt emitter rides the continued-pretrain harness
  when (and only when) a 2B RETRY actually fires.
