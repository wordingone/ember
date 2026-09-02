<!-- EMBER_ARTIFACT_CLASS=historical_only -->

# fp-44 ≤1-day-bar / optimizer decision — multimodal v0 launch

**Status:** decision-record, authored 2026-06-14 (the lead). Resolves #21 (the fp-44
≤1-governed-day / optimizer pick for the multimodal-unified v0 launch). Companion
to `docs/domains/governance/archive/pre-restart/pretrain-launch-authorization-brief-multimodal.md` — fills its
`optimizer: [#414 pick]` slot with a **default + revision trigger**, so the launch
is not blocked on the pick and the maintainer is not asked to choose. Made inside the goal
(the maintainer overrides); not escalated.

**Queue context (eng-gate audit, 2026-06-14):** every open the lead-class GH issue
(#205 round-1 verdicts, #273 fp-35 band→allocation, #282 sp-6b replay-rig) is
**trigger-gated on a post-launch event** (round-1 dispatch / band-prediction-fire
/ ember-checkpoint), each requiring readiness 3/3 (currently 1/3). Their
pre-stageable halves are **frozen** (fp-27 prereg ×3 "zero decisions at fire
time"; sp-6b + fp-35 preregs discharged). So the advanceable the lead-class frontier is
the multimodal readiness chain (ledger MR-rows), not those issues. THIS doc is
MR-4 of that chain.

## What fp-44 measured (and why it does not transfer)

fp-44 (#19, CLOSED) measured **Muon ns5 vs full-fused-AdamW @2000 steps on 0.37B
TEXT**: Muon lower loss, `delta_T = −0.746` nats — but **thin and an agent-flagged**
(0.141 nats over the 0.605 noise floor; collapses to within-noise by step ~1500).
These are **0.37B-text numbers**. The multimodal config (different width path,
embedder params, bidirectional image spans, 2D-RoPE) is a different optimization
surface — **#414 re-measures Muon-vs-AdamW on the realized multimodal config**;
the text deltas do not carry (config-spec §II).

## Decision (default — ships at readiness, no escalation)

The multimodal v0 launch uses the **carry-envelope optimizer: Muon (hidden 2D
params) + AdamW (embeddings / norms / head)** — config-spec §II, identical to
v0-text. Rationale: Muon was the measured-lower optimizer at the text scale and is
the directed C-3 design optimizer; absent contrary multimodal evidence, it is
carried, not replaced.

The **≤1-governed-day bar** is arithmetic on the realized tok/s, not a promise:
the **B-MULTI-4 runner selftest tok/s is the lever receipt** (the multimodal
analogue of c04's §3 bench). If Muon-batched clears the bar at the realized
throughput, the launch authorization is *informational* (no tradeoff). If it does
not, the only maintainer-facing branch is the env-bump-vs-AdamW tradeoff below.

## Revision trigger (finalizes the pick — the only thing that can flip the default)

`#414` Muon-vs-AdamW re-measurement **on the multimodal config**:
- If #414 shows AdamW clears the ≤1-day bar free **AND** the multimodal quality
  gap is within-noise (the text gap already collapsed by step 1500) → switch
  default to **AdamW** (avoids the torch≥2.7 env-bump risk; un-batched Muon was
  1.325 d, over the bar — the env-bump is the only Muon-preserving lever).
- If #414 shows Muon stays measured-lower at acceptable throughput → **keep Muon**.
- The pick **finalizes at #414's multimodal receipt**; until then the default is
  Muon (text-scale winner + directed optimizer). AdamW is never auto-picked to
  dodge an env-bump — the measured multimodal delta + the bar decide.

## Envelope boundary (the only escalation, per the launch-auth brief)

The torch≥2.7 compile env-bump (shared-env major-version change) is a **risk-envelope
decision = the maintainer's**, and only materializes if #414 lands in Profile-B territory
(Muon over the bar un-batched, batched short). It is surfaced by the launch-auth
brief, not pre-decided here.

## Constitutional / honesty

Carries Muon as the **default, not a final pick**; #414 is the multimodal
measurement that finalizes it. No directed component dropped. QAT tail stays on
AdamW not Muon (survey component 1: Muon×QAT published null/negative — config-spec
§II). Precision/objective/schedule unchanged from the carry envelope.

Per user direction.
