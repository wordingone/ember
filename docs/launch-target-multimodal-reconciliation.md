# Launch-target reconciliation — the pre-auth autonomous launch fires on MULTIMODAL only

**Status:** authored 2026-06-14 (the lead), gating amendment. Binds the pretrain
readiness gate. Triggered by a fork found during the backlog pull: the pre-staged
launch machinery targets a run the current goal has superseded.

## The fork (both sides are authoritative artifacts, not assumption)

- **Pre-staged machinery** (`pretrain-launch-authorization-brief.md`,
  `trigger-readiness.md`, the 8 open the lead issues #205/#210/#223/#273/#282/#328):
  all describe the **C04 2.2B-token owned-core accumulation** run. The brief
  mentions **no modality** and frames the launch as **the maintainer-gated**
  ("Why it reaches you (not auto-launched)").
- **Current goal** (.agent config focus, hook-injected; tasks #22/#23): the first real
  long training is the **non-toy multimodal-unified** pretrain, and the maintainer's 06-14
  pre-auth makes the launch **autonomous-on-readiness** ("if i dont respond …
  you should eventually run it"), with the explicit floor **"not a half assed
  readiness that plans to train a toy text only model."**

These do not match. The C04-text brief is pre-pivot; #414/#415 (re-measure the
optimizer + density on the **multimodal** config) are the only artifacts that
have moved to the new target.

## The risk this closes

The pre-auth + autonomous-launch + asleep-the maintainer combination means: if the readiness
gate is read as "green" against the **C04-text** machinery (whose scorers are all
frozen + selftest-PASS), the autonomous launch could fire **the text run** — the
exact forbidden outcome. A frozen, selftest-green scorer chain pointed at the
wrong target is *more* dangerous, not less: it will authorize confidently.

## Binding rule (adds a THIRD readiness precondition)

The pre-authorized autonomous launch **fires only on the non-toy multimodal-unified
config**, never the C04-text brief. Until the conditions below hold, readiness is
**UNMET** regardless of the C04-text scorer chain's state, and **no autonomous
launch fires** (the pre-auth does not license launching the wrong run):

1. **Multimodal floor (hard, the lead-gated).** The launched config trains **≥2
   modalities in the unified objective** — not a text run with a stubbed/identity
   vision path, not a vision tower frozen to zero gradient. "Multimodal" = both
   modalities contribute loss and receive updates, verified on the config, not the
   prose. (The architecture is the engineer's; the modality-presence floor is the gate.)
2. **Multimodal optimizer re-measure (#414).** The optimizer pick (`c04_optimizer_pick`)
   is re-run on the **multimodal** config — the C04-text fp-44 numbers (Muon 1.325d
   / AdamW 0.919d at 0.37B text) do **not** transfer to a multimodal budget; the
   ≤1-day bar must be re-evaluated on the real config.
3. **Density axis NOT consumed as D-CONF (#415, an agent flag #14).** The density verdict
   was a single-seed-mean artifact (rejected); the multimodal config must not route
   on density (c04 D-CONF/2.2B routing is VOID pending the powered #415 re-test).

## Relationship to the other two readiness preconditions

All THREE must be green before the pre-auth autonomous launch fires:
- **This (multimodal target floor)** — launch the right run.
- **DT-6 signal-economics** (`dt6-loop-economics-gate-amendment.md`) — the readiness
  probe reports verified-signal-per-GPU-hour above the equal-wall-clock band, not
  "the smoke ran clean."
- **Crash-survival** (`readiness-gate-crash-survival.md`, #25) — the work-system
  survives a founder crash + auto-recovers ≤10min (an agent drill), so the multi-day
  run does not orphan.

## Carried forward unchanged from the C04 brief (config-independent envelope)

Governor rails (VRAM_FRACTION=0.80, MARGIN_GIB=1.5, decode pacer 0.05s;
margin-violation auto-kill; **fix-forward BANNED**) and the kill-criteria set
(margin / D-P gate / NaN-divergence / throughput-regression / checkpoint-1 floor
fail-before-continue) apply identically to the multimodal run.

## Current repo state (grounding — read 2026-06-14)

The only pretrain config in the committed repo is `configs/v0-pretrain-config.json`
= **ember-v0, text-only**: hidden 1024 / 20 layers / vocab 32000 / seq 1024 /
next-token CE + 2 independent MTP auxiliary heads / 368,354,304 base parameters
excluding MTP + 65,536,000 MTP parameters = 433,890,304 declared realized parameters.
This is not DeepSeek sequential MTP or a speculative drafter. No vision encoder, patch-embed, image-token, or modality-fusion file
exists (grep + glob, 2026-06-14). The **one** piece of multimodal groundwork is the
tokenizer's **reserved multimodal band** (v0 config line 70 — design intent, no
model behind it). So the goalpost moved from "launch v0-text (nearly ready —
frozen config, optimizer decided, governor wired, runner-extension the main gap)"
to "launch multimodal (green-field)". This is the maintainer's directed scope, not a flag —
the green-field state is the honest reality of executing it.

CAVEAT (claim-scope): "green-field" = absent from the COMMITTED repo. the engineer had
uncommitted WIP in the tree (scripts/t5_harm.py, w1_humaneval.py) and a crashed
session — he may have multimodal work in flight; confirm on his return before
treating the build as fully from-scratch.

## Prerequisite eng task (sequences BEFORE #414/#415)

#414/#415 re-measure optimizer/density on "the multimodal config" — which does not
yet exist. The prerequisite is **build the multimodal-unified pretrain config +
architecture + multimodal data pipeline** (the engineer eng, green-field). AC = the
multimodal floor above (≥2 modalities in the unified objective, both contributing
loss + receiving updates; uses the tokenizer's reserved multimodal band). This is
the #1 eng item on the engineer's return; #414/#415 run against it once it exists.

## Eng inputs (already in the engineer's loaded queue; not re-dispatched here)

#414 (multimodal optimizer re-measure), #415 (powered density re-test + verdict
seed-agreement fix), and the multimodal training config itself are the engineer's — queued,
deliver on his watcher re-arm. This doc is the **gate**, not the build.

Per user direction.
