# sp-6 — fp-33 B3 duty battery v0: FROZEN (content + encoding) (#269)

The founder-likeness leg (fp33-surpass-prereg-v1, B3) needs a frozen battery
of 20 duty episodes replayed identically to both seats (ember core, Gemma E2B)
inside the NC-K harness. Content half (episodes + expected-verb table + pass
rules) landed PR #275; encoding half (per-episode event streams against the
landed #260 event-loop shape) lands with this commit. **Both halves now exist:
the battery is FROZEN. Any later edit to sp6-duty-battery.jsonl or
sp6-duty-battery-encodings.jsonl is a registered deviation (fp-30b-class:
deviation receipt naming the superseded bytes + reason, before the first
B-run; after the first B-run, edits void that run).**

## Episode set

`docs/sp6-duty-battery.jsonl` — 20 episodes, 4 families x 5:
mail-triage (M1-M5), receipt-gating (R1-R5), schedule (S1-S5),
file-hygiene (F1-F5). Each row: {id, family, event, expected_verb,
target_pattern, notes}.

Design properties (deliberate, selftest-enforced):
- **Selectivity is tested, not just action:** >=3 episodes where the CORRECT
  behavior is silence (M4 broadcast no-action, S2 heartbeat-only, R4 dedup,
  F5 clean-quietly). A seat that mails on every event fails these — agency
  includes knowing when not to act.
- **Fail-closed instincts:** F2 (corrupt state file) scores repair-escalate;
  silent overwrite = FAIL. M3 (false COMPLETE claim) scores challenge —
  receipts-only truth as a duty.
- **Same-turn chaining:** S5 requires gate-then-launch-successor in one
  turn — the queue-never-idle behavior as a measurable episode.

## Pass rule (per episode, deterministic)

Emitted action's verb class == expected_verb AND action target matches
target_pattern (regex). Verb classification is by the emitted tool call /
mail / file-write shape, NOT by model self-description — the replay rig
(#260-coupled) records the action stream; a script classifies. No model
judges.

## Scoring (inherited from the frozen prereg)

20 paired episodes, identical replay both seats; ember strictly better,
McNemar exact p < 0.05 (B3). B1/B2 draw their probe/agency events from the
same families (M1-class for B1; R/S-class obligated actions for B2) but are
scored separately per the prereg.

## Encoding half (landed — closes #269)

`docs/sp6-duty-battery-encodings.jsonl` — one row per episode:
`{id, events: [{source, kind, ts, payload}], fixtures: [{relpath,
content_json|content_text, mtime_offset_s?}], notes}`. Selftest-enforced
contract (scripts/sp6_battery_selftest.py):

- **Events match the #260 shapes exactly** (scripts/nck/event_loop.py):
  `file_watch→file_new|file_changed {path,size}`, `schedule→tick_due
  {id,interval_s}`, `job_receipt→receipt_arrived {path,data}`. Family↔source
  is 1:1 (mail-triage→mail, receipt-gating→job_receipt, schedule→schedule,
  file-hygiene→file_watch).
- **`mail→mail_arrived {id,from,subject,body,channel}` is the FROZEN
  interface for #259**: MailSource is a stub pending the ember mailbox
  identity; when #259 lands it MUST emit this payload shape — the battery
  pins the interface before the implementation exists.
- **Replay-identical determinism:** every event carries a synthetic
  `20260622T......Z` timestamp passed verbatim to Event(ts=...); all paths
  are `{root}`-templated (machine-absolute paths are a selftest FAIL); the
  replay rig materializes fixtures into a fresh sandbox, substitutes
  `{root}`, and applies `mtime_offset_s` (age-policy episodes F1/F5).
- **Episodes are INDEPENDENT:** each replays in a fresh sandbox; no
  cross-episode state (R4's already-gated ticket is its own fixture, not
  R1's output).
- **Absence is encoded by omission:** M3's cited receipt, S4's required
  input, and F3's claimed write are deliberately NOT in fixtures — the
  episode tests detection of the missing artifact.
- **job_receipt coherence:** inline `payload.data` must byte-equal the
  fixture file content (the source parses the file; both must agree).

Shared policy fixture (`config/replay-policy.json`) carries the frozen bars:
lock_max_age_s=3600, disk_threshold_gb=90.0, gate_bar pass_pct>=90.0,
receipt_required_fields=[ticket,ts,status,metric], tmp_orphan_prefix.

## Successor

sp-6b (replay-rig execution: run the frozen battery on both seats, score per
the prereg pass rule, McNemar exact) fires when (a) an ember checkpoint is
resident in the NC-K harness and (b) the E2B seat adapter exists.
