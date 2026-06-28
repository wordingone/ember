# v0 multimodal pilot — token-budget derivation (pre-smoke, frozen framework)

**Status:** authored 2026-06-16 (the lead, seat). Companion to
`pretrain-launch-authorization-brief-multimodal.md` (the authorization) and
`ember-multimodal-v0-config-spec.md` (the architecture). This is the **budget
half** of the launch — the analogue of `c04-token-budget-v1.md` for the
post-pivot multimodal config. It freezes the *method* now so the moment the
real-data smoke lands, N resolves with zero improvisation (anti-goalpost: the
derivation is written before the run exists).

It does **not** freeze a single N pre-smoke — and that is deliberate, not a
deferral. Two inputs N depends on are unmeasured until the smoke: (1) the
**real-data** tok/s (the synthetic bench overstates it — see §2), and (2) the
first read on whether bulk image-text data clears the floor at an affordable
budget (§4). The framework below is what gets *applied*, not re-decided, at
smoke-pass.

## 1. Method (carried from c04 §3, unchanged)

Budget is a **derived** quantity, not a free parameter:

    budget_tokens ÷ tok/s_paced ≤ N × 24 governed hours

The Chinchilla-class **demand** for a 0.368B dense model is 20·P = **7.36B
tokens** (compute-optimal estimate, no local receipt — same status as c04's
20·P column). One governed day **affords** `tok/s_paced × 86400`. The ratio
demand÷afford = the **required density multiplier** the corpus must deliver for
the affordable run to be Chinchilla-equivalent. The multiplier is an
**obligation on the data**, not an optimization (c04 §F-4).

## 2. tok/s basis — REAL-DATA, never the synthetic bench (correction)

The brief's "1 governed day ≈ 1.72B tokens" is the **synthetic-batch** number
(19,935.6 tok/s paced, `make_synthetic_batch`). It is a **ceiling**, not the
launch basis. Precedent — c04 recalibration caveat: the bench-path F ran
**~2× optimistic** vs the production path (fp37-l7-v2 reconciliation). Real
multimodal batches add: manifest/image I/O, variable caption length, patch
encode if not precomputed. **N is computed from the smoke's measured real-data
tok/s_paced**, not 19,935.6:

    N_days = budget_tokens ÷ (real_tokps_paced × 86400)

Expect real_tokps_paced < 19,935.6; the gap scales every N row equally (c04
caveat: "direction survives"). The smoke receipt MUST report real_tokps_paced.

## 3. Token MIX — the multimodal-specific gate the text budget never had

Patch tokens dominate the stream (B-MULTI-1 sample: ~33,534 patch : ~500
caption over 500 pairs). A token budget counted naively is **~98% image
patches** → two failure modes:

- **Text-modality starvation → catastrophic forgetting** (kill-criterion #4,
  the Mono-InternVL mode config-spec §VI names explicitly). A budget that
  trains mostly on patches lets the text modality drift.
- **Verify-floor blindness:** the floor is "image-grounded verify-rate >
  text-only control" — the *control* needs the text modality intact to be a
  control at all.

**Requirement (seat direction, the engineer implements):** the budget specifies a
**text-token floor** (or equivalently a patch:text ratio cap) so both
modalities are trained, not just the dominant one. The smoke receipt MUST
report the realized patch-token / text-token split so the mix is verified, not
assumed. Exact floor set at N-fill once the real split is known.

## 4. The open risk the brief glosses — bulk density vs the floor

c04's only local density datapoint is **negative**: ~3B bulk-weighted tokens on
a 0.37B-class run produced floor-marginal rates. The multimodal corpus is
**bulk web image-text (CC3M-class), not a curated-dense stream** — so the c04
lever "curated density closes the multiplier gap" may **not** apply here. Bulk
multimodal data at the affordable 1-day budget may not clear the
image-grounded floor.

This is not a blocker — it is what the pilot **measures**. The first reads:
the smoke's loss curve (descending on real data = mechanism works, §precond-1)
and the **checkpoint-1 floor-probe** (kill-criterion #6: floor-probe FAILS →
halt before spending the remaining budget). The budget framework must make this
read cheap and early, not bury it at the end of a multi-day run.

## 5. Resolution at smoke-pass (what gets applied, not re-decided)

When the real-data smoke receipt lands (real_tokps_paced + patch:text split):

1. **Budget target** = the c04-style affordable run carrying the density
   obligation: default **one governed day's affordable tokens at real tok/s**
   (the smallest-core-pilot-first envelope, non-toy by modality+architecture
   not by token count), with **7.36B (Chinchilla-optimal) as the ceiling** and
   the **verify-floor as the success bar** (clear the floor = the pilot
   succeeded, regardless of where in the budget that happens).
2. **N_days** = budget_target ÷ (real_tokps_paced × 86400).
3. **Text-token floor** set from the realized split (§3) to protect the
   control + against forgetting.
4. **Revision trigger (escalates to the maintainer, not silent):** if checkpoint-1's
   floor-probe shows the floor is *approached but not cleared* at one governed
   day, extending toward the 7.36B ceiling is a **new N** = a changed authorized
   envelope = the maintainer's call. The pilot does not silently extend (never-reduce-scope
   in reverse — never silently-grow-spend either).

## 6. Non-toy defense (pre-answering the maintainer's bar)

the maintainer ruled out "a half-assed readiness that plans to train a toy text-only
model." The non-toy-ness of this pilot is **structural, not token-count**: full
**both-modalities** training (the thing he ruled out was text-only), the
**four architecture locks + QK-norm**, a real **multi-day-class governed
burst**, a real **image-grounded verify-floor**. An under-Chinchilla token
count is a defensible *pilot-economics* choice (prove train+transfer, then grow
on the E2B-surpass trajectory — config-spec §IV), not a toy.

## 7. N RESOLVED — FINAL (ER-2d, 2026-06-16; source-verified PR #441)

**FINAL N (supersedes the provisional below).** ER-2d measured tok/s on the actual launch
loader — `MatchedPackedCorpusLoader`, packed AND correspondence-preserving (K=8 matched
image-caption pairs/seq, each image bound to its own caption; Lock-4 multi-image RoPE fixed).
Receipt `ember437-er2d-20260616T072423Z.json`: **`tok_s_paced=8,627.0`** / raw 9,661.3,
`tokens_per_step=4096`, `binding_preserved=true`, `er2d_pass=true`, loss →1.22.

- **1 governed day affords** = `8,627.0 × 86,400 ≈ 745M tokens`.
- **Chinchilla-optimal** 20·P = 7.37B → ceiling `≈ 9.9 governed days`.
- **Default pilot (§5.1):** one governed day = **745M tokens**; verify-floor = success bar;
  7.37B (9.9 days) = ceiling; extension toward ceiling escalates to the maintainer (§5.4).
- **Launch MIX (real, sets §3's floor):** 35.5% patch / 65.45% text — both modalities present,
  no starvation either way. §3's text-floor concern is resolved by the matched loader's natural
  balance; the grounding floor is the checkpoint-1 image-grounded verify-probe (kill-#6), to be
  frozen as a spec before launch.
- **Why FINAL ≈ 2× lower than provisional:** the matched loader packs 8 images/seq (~5.5× more
  patch tokens than ER-2c's single-replicated-image shortcut), so it is genuinely ~2× slower.
  The ER-2c provisional would have under-provisioned governed-days ~2× — vindicating the
  measure-on-the-real-loader discipline.

Disk at this scale unchanged (<100GB); the open scaling item is **ER-3** (scale the corpus to
carry ≥745M tokens of MATCHED pairs, bounded <100GB, escalate if more).

---

### 7-prov. N — provisional (ER-2c, superseded by §7 above)

The framework above is now applied, not re-decided. ER-2c measured real-data tok/s on the
**§IV launch model** (EmberTransformerLayer 368M, n_layers=20) at the **launch batch/seq**
(batch=4 × seq=1024, PACKED, `tokens_per_step=4096` asserted), ≥200 steps under governor
rails. Receipt `ember437-er2c-20260616T064826Z.json`: **`tok_s_paced=18,122.9`**,
`tok_s_raw=22,260.8`, `er2c_pass=true`, loss 10.56→2.0.

Applying §1/§2 (`N_days = budget_tokens ÷ (real_tokps_paced × 86400)`):

- **1 governed day affords** = `18,122.9 × 86,400 ≈ 1.566B tokens`.
- **Chinchilla-optimal demand** 20·P (P=368,409,600) = **7.37B tokens** → ceiling
  `7.37B / 1.566B ≈ 4.7 governed days`.
- **Budget target (§5.1 default):** one governed day = **1.566B tokens**, verify-floor as
  the success bar, **7.37B (4.7 days) as the ceiling**. Silent extension toward the ceiling
  escalates to the maintainer (§5.4) — never auto-grows spend.
- **Disk:** 368M fp32 ckpt ~1.47GB + AdamW state (~2×) ≈ 4.4GB/full ckpt; b-multi-1 corpus
  tiny; keep-last-N → well under the 100GB escalation line. Not a blocker at this scale.

**Why PROVISIONAL, not final.** The valid-N receipt came from **PackedCorpusLoader**, which
is a **throughput-only** loader: it replicates one anchor image across the batch and fills
with unrelated captions (source-verified, lines 282–372) — correct for measuring tok/s,
but it breaks image↔caption correspondence and so cannot train the grounding the floor
measures. The **launch loader (ER-2d)** must be packed AND correspondence-preserving (handle
the Lock-4 multi-image RoPE constraint). Because **model compute dominates** ER-2c's step
time (~180ms/step model vs 50ms pacer — governor not binding per the receipt), the launch
loader's throughput will be **close to 18,122.9**; the provisional N above is a small-margin
estimate, and the **final N re-confirms on ER-2d's at-launch-loader receipt**.

**Token-MIX floor — DEFERRED to ER-2d's realized split (not the ER-2c 6.4%).** §3 anticipated
~98% patches → text starvation. The ER-2c packed split came back **inverted** (0.064 patch /
0.936 text) — but that is an artifact of the single-image-replicated throughput loader, NOT
the launch mix. The launch loader packs *matched* pairs, so its patch:text will differ
(more images per sequence). The floor (now likely a **minimum patch / minimum matched-pairs**
floor protecting the grounding signal, not the text-starvation floor §3 assumed) is set from
ER-2d's realized split. This is recognition that 6.4% is measured on the wrong loader for
mix purposes — not a goalpost move.

## Cross-refs / staleness flagged

- Method: `c04-token-budget-v1.md` (§3 criterion, density multiplier, ~2×
  bench caveat). Verify-floor: `ember-floor-contract.md` multimodal row
  ("image-grounded verify-rate > text-only control") + config-spec §VI.
- **STALENESS for the maintainer's wake:** `ember-floor-contract.md` still frames "v0
  corpus is text" with encoder-free multimodal TRAINING as a *deferred /
  RE-STAGED* row. the maintainer's 2026-06-14 reactivation promoted multimodal to the v0
  **launch target**. That is a the maintainer-made scope promotion the binding ledger has
  not recorded; the ledger's invariant requires the user by name to amend rows,
  so the seat **flags** it rather than rewriting it. Reconcile on the maintainer's wake.

Per user direction.
