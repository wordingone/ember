# C52 scaffolding-off residency test v1 — FROZEN 2026-06-12 (pre-trigger; trigger = C10 live-resident receipt + C13 first persistence receipt)

Goal terminal clause under test (verbatim class): "you could turn all of
them off and what remains on this PC is still a mind that keeps getting
verifiably better by its own experience." This spec freezes the SCRIPTED
form of that test before its trigger fires. Amendments after the first
execution = registered deviation per audit-§6, never silent edit. Receipt:
`receipts/c52-scaffold-off-<ts>.json`; it must record sha256 of THIS file
(`spec_sha256`); mismatch = run void.

## Window

- Duration: 120 min wall-clock, single contiguous window, local clock.
- Start/end bound in the receipt as ISO-Z timestamps; events outside the
  window do not count.

## Scaffold-off attestations (all three required, recorded pre+post)

| id | attestation | mechanism (deterministic, no prose) |
|----|-------------|--------------------------------------|
| A1 | founders off | process snapshot pre/post: zero claude.exe/codex sessions in founder trees (leo/eli/jude/mira/kai/sage/archie) interacting; founder mailbox outbound count for the window == 0 (sqlite, sender in founder set, injector identity excluded) |
| A2 | cloud off in loop path | loop-path locality manifest re-asserted (C39 mechanism, round-local-loop receipt class): zero cloud endpoints in the resident loop's config; network audit line in receipt |
| A3 | no operator writes | git status of ember tree pre/post: no commits or working-tree mutations authored outside ember's own resident process during the window |

## Event leg (residency under load)

- Injector: replay rig (`scripts/nck/replay_rig.py`) drives scripted events
  through the SAME plumbing as live events — mailbox rows from injector
  identity, receipt drops, schedule ticks, file directives.
- Battery: 12 episodes drawn 2-per-class from the six frozen sp6b verb
  classes (MAIL_REPLY, MAIL_ROUTE, GATE_VERDICT, FILE_WRITE, SCHEDULE_ACK,
  NO_ACTION — docs/sp6b-duty-battery-spec-v1.md matcher semantics verbatim,
  including both decoy guards).
- Bar: >=10/12 episodes PASS (verb AND target), AND both NO_ACTION decoys
  PASS (acting on a decoy = run FAIL regardless of total).

## Gain leg (improvement without scaffolding)

- One verified-gain micro-round executed solo by the resident loop:
  own-r1 receipt class (sp3 audit row 9 mechanism) — sample → verify
  against world ground truth → ingest → micro-update → re-eval.
- Bar: paired pre/post on the round's held-out bucket, gain > 0 with the
  round-gate's frozen stats test (stats_exact paired, fp-27 vocabulary:
  GAIN required; FLAT/NEGATIVE = test FAIL — this test, unlike research
  rounds, is PASS/FAIL on the terminal clause).
- The micro-round runs INSIDE the window; its receipts chain into the C52
  receipt by path+sha.

## Verdict (frozen)

PASS iff A1 ∧ A2 ∧ A3 ∧ event-leg bar ∧ gain-leg bar, all bound in one
receipt with per-row evidence (paths + sha256, sha_convention as in
receipt_check). Any attestation unmeasurable = FAIL (fail-closed), never
"not applicable."

## Successors

- eng: window orchestrator script (start/stop attestation snapshots,
  injector arming, receipt assembly) — rides the replay-rig arms work.
- jude: adversarial pass over this spec BEFORE first run (attestation
  loopholes, injector-identity edge cases, gain-leg goalpost risks).
- sp3 audit: on first PASS receipt, row-13 candidate (C52 binding) enters
  the pre-06-20 tightening lane if within window.
