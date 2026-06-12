# sp-6 — fp-33 B3 duty battery v0: episode content half (#269)

The founder-likeness leg (fp33-surpass-prereg-v1, B3) needs a frozen battery
of 20 duty episodes replayed identically to both seats (ember core, Gemma E2B)
inside the NC-K harness. This lands the CONTENT half: episodes + expected-verb
table + pass rules. The ENCODING half (how each episode serializes into the
harness event stream) binds to the #260 event-loop skeleton and stays open on
#269 — the battery FREEZES only when both halves exist, before the first B-run.

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

## Open half (stays on #269)

Event-stream encoding per episode (the serialized mail/file/receipt/schedule
fixtures the harness ingests) — authored against #260's event-loop shape when
it lands; then the battery freezes whole (content + encoding) and any later
edit is a registered deviation.
