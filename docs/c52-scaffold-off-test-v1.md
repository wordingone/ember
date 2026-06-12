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
  DONE 2026-06-12: receipts/c52-adversarial-pass-20260612T175700Z.json
  (9 findings) — resolved by Amendments v1.1 below.
- sp3 audit: on first PASS receipt, row-13 candidate (C52 binding) enters
  the pre-06-20 tightening lane if within window.

## Amendments v1.1 — 2026-06-12, pre-first-run (sanctioned by the
## successor clause above; each row cites its finding id; where v1.1
## conflicts with v1 text, v1.1 governs)

- **F2 (A2, HIGH):** A2 is runtime-attested, not config-only: the resident
  process runs the window under a deny-by-default egress posture recorded
  in the receipt — connection log (per-process network audit for the
  resident pid, e.g. firewall/ETW capture armed by the orchestrator) shows
  zero non-loopback endpoints for the window. Config manifest remains as
  corroboration, never the primary.
- **F3 (A3, HIGH):** A3 mechanism = `git log --since <start> --until <end>`
  author/committer audit (zero commits not authored by the resident
  identity) PLUS working-tree mutation check via pre/post
  `git status --porcelain` diff restricted to paths outside ember's own
  output dirs (receipts/, state-test/, status log).
- **F4 (injector id, HIGH):** injector identity is NAMED: `injector`
  (dedicated mailbox identity; rig refuses to arm if it does not exist).
  Injector NEVER sends as a founder identity; any window mail whose sender
  is a founder = A1 FAIL.
- **F6 (gain leg, HIGH):** the held-out bucket is FROZEN pre-round: bucket
  ids + content sha256 written into the receipt's `gain_holdout` block
  BEFORE the micro-round starts (orchestrator timestamps the freeze line
  in the status log); post-hoc bucket choice = run void.
- **F1 (A1, MED):** the two A1 sub-checks are time-coupled: process
  snapshots at start AND end; sqlite outbound count window = exactly
  [start, end]; any founder-sender mail with sent_at inside the window
  fails A1 regardless of snapshot timing.
- **F5 (A1, MED):** ember's own outbound (including replies TO the
  injector) is excluded from the FOUNDER-outbound count by sender
  identity: A1 counts senders in the founder set only; ember and
  `injector` are not in that set.
- **F7 (gain leg, MED):** ground truth for the micro-round's verify step
  must be locally cached BEFORE the window starts (path + sha256 recorded
  in `gain_holdout`); any verify-time fetch is an A2 violation by the F2
  runtime audit.
- **F9 (attestation, MED):** timestamps are not solely self-attested: the
  orchestrator commits the start-attestation snapshot to the repo at
  window start and the receipt at window end — git commit timestamps (and
  the mailbox sqlite sent_at rows for window events) provide the
  independent clock cross-check; >2min disagreement = run void.
- **F8 (gain leg, LOW):** micro-round budget bound: must complete within
  90 min of window start (status-log line marks round start/end); a round
  still running at window end = gain-leg FAIL (not void — the residency
  event leg still scores).
