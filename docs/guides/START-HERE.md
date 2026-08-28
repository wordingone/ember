# Start here

On Windows, launch the operator body from the repository root by running `Ember.cmd`. For a
versioned per-user installation with Desktop and Start Menu shortcuts, see
[`docs/operations/windows-desktop-install.md`](../operations/windows-desktop-install.md).

This page exists so a first-time reader — someone with no prior context on this repo — can
verify one claim end-to-end without reverse-engineering the vocabulary first. It does not repeat
`README.md` or `GOAL.md`; it maps the terms and structure those pages assume you already have.

Read in this order: (1) the A/B/C loop below, (2) the glossary, (3) the one worked receipt, then
go verify something yourself with the recipe at the bottom.

## 1. The A/B/C loop (the primary frame)

Almost everything in this repo — the board conditions, the receipt schema, the anti-fraud
protocol — is checking one of three moves. `README.md`'s opening paragraph states this loop in
prose ("ember improves by verified experience only"); this table names the three moves and maps
the board's condition codes onto them.

| Stage | What happens | Board conditions that live here |
|---|---|---|
| **A — act / propose** | ember takes an action in a world it can inspect: grows a checkpoint, produces a candidate | `C-BASE` (owned growable seed exists, exposing the grow-operator interface from step 0), `C-GROW` (a receipted growth event) |
| **B — verify (held-out + matched control)** | what the candidate will be judged against is sourced and frozen, then the candidate is scored on data it never trained on, against an equal-budget control, before/after, with a positive delta required | `C1` (source-backed benchmark/dataset discovery — what will be verified against) `C2` (held-out task) `C3` (equal budget) `C4` (before/after) `C5` (positive delta) `C-E2B` (paired measured-distance vs. a frozen reference) `C8` (field-level: cites the closest prior + ablates) `C-SCALE` (the capability point is scale-credible, not a toy) |
| **C — burn in (D-gate / P-gate)** | only a verified gain is written into weights; the standing test is that it **disappears when the artifact is deleted** (D-gate) and **persists across a process restart** (P-gate) | `C6` (the recipe reproduces or names its mismatch) `C7` (the self-growing operator is load-bearing, not decorative) `C-ORGANISM` (ingestion + growth + portability wired into one inspectable graph) `C-AUTO` (autonomy-ladder claims are honest about which rung is actually earned) |

This is a frame for reading the board, not a literal execution pipeline every condition passes
through in order — some conditions (e.g. `C-CUSTODY`, `C-INV`, `C-ENF`) are infrastructure
integrity checks that sit outside the loop entirely (they check that the loop's own evidence
trail is trustworthy, not that a specific gain cleared A/B/C). See `docs/spec/conditions-v1.md`
for the full registry.

## 2. Glossary (in the order you meet these terms)

**Receipts.** A receipt is one JSON file under `receipts/`, produced by an executed local job,
that a checker script can validate. Claims are gated exclusively by receipts — prose never
carries a claim (`README.md`, `docs/archive/pre-restart/index.md` "Evidence model"). Schema floor:
`scripts/receipt_check.py`.

**D-gate / P-gate.** Two standing tests every claimed gain must pass to count as burned into
weights: **D-gate** — the gain disappears when the artifact (the adapter, the checkpoint delta)
is deleted, proving the gain actually lives in that artifact and isn't a fluke of the harness;
**P-gate** — the gain persists across a process restart, proving it isn't an in-memory illusion.
(`README.md` opening; `docs/archive/pre-restart/index.md` "Standing audits".)

**GATE-0 / GATE-1 (/ GATE-2 / ASSEMBLY).** A local sequencing convention used inside individual
protocols to order CPU-only steps before the one GPU job. For the C-E2B paired-run protocol
(issue #48, "Sequencing (frozen)"): **GATE-0** = CPU-only — the paired-run script lands and a
CPU dry-run of the full assembly runs against a stub arm, maintainer-gated; **GATE-1** = the one
GPU job — the E2B `ember_work` arm actually runs, under the resource governor; **GATE-2** = the
`founder_likeness` sessions (owned arm, then E2B arm), sequential; **ASSEMBLY** = the one receipt
under `receipts/` that ties both legs together. This numbering is local to whichever protocol
defines it — it is not a single global gate list, and it is unrelated to the board's `GATE-001`
.. `GATE-006` rows in `docs/ledgers/ember-debt-ledger.md`, which are a separate, differently-scoped
trigger list.

**The bottleneck-ledger walls (B1–B5) — and the unrelated W1/W2.** The standing dispatch
authority for what blocks full local FM creation is issue #207, "BOTTLENECK LEDGER", and its rows
are named **B1 DATA WALL**, **B2 TRAINING-STATE MEMORY WALL**, **B3 COMPUTE/WALL-CLOCK WALL**,
**B4 INFERENCE→TRAINING TRANSFER**, **B5 THE QUALITY BAR**. Separately, and confusingly similar
in shape, `docs/spec/w2-scale-preregistration-v1.md` and `docs/archive/pre-restart/c-scale-execution-graph.md` use
**W1** and **W2** as names for two C-SCALE experiment *windows* (W1 = pretrain-scale token-bill
collapse test; W2 = native finetune-scale adaptation test) — these are not walls, there is no W3
or W4, and W1/W2 do not correspond one-to-one to any B-numbered wall. Do not conflate the two;
if you see "the walls" named with a W-prefix anywhere, that is this same collision recurring,
not a fourth C-style namespace.

**L1–L10 (the constitutional laws).** `GOAL.md` §3, permanent, violating any voids the
violating claim: **L1** hardware identity (one consumer GPU, forever) · **L2** receipts-only ·
**L3** anti-distillation, absolute · **L4** provenance (every training token's lineage is
receipted) · **L5** zero-cost proof (no paid service may gate/verify/clear anything) · **L6**
earned compute (GPU-hours escalate only on receipts that earn them) · **L7** kill-protection (no
row dies by self-verdict; only the operator kills) · **L8** scope (only the operator reduces
scope) · **L9** anti-fraud core (equal budget, before/after, deletion-ablation, external
held-out, reproducible recipe, hardest-core-first) · **L10** publication (pseudonymous workbench,
but the paper carries the author's name).

**P-A / P-B / P-C (the pillars).** `GOAL.md` §4, co-equal — starving any one is the failure
state: **P-A THE RESEARCH** (the bottleneck-ledger walls; an open field, no favorite lever) ·
**P-B THE ORGANISM** (identity lives in the running system — loop + ledger + methods; physics:
P1, P2 below) · **P-C THE BODY** (`ember-cli`, the operator's audit channel on every other claim;
the observatory must be animated by real internal state, never a keyframed fabrication).

**P1 / P2 (the two physics laws).** Named inside pillar P-B (`GOAL.md` §4): **P1**, the energy
law — the capability achieved per unit of local compute/energy spent, at a pinned hardware/data/
model config (an "ADM"); C3 FRONTIER BEND is the claim that this frontier bends an order of
magnitude past the standard stack at matched budget. **P2**, the growth/assimilation law — a
growth event (widening a checkpoint) only counts if it is *receipted as earned*: the admission
gate verifies function-preservation and budget accounting simultaneously as the license for the
capacity change (`docs/spec/c8-preregistration-v1.md` §2). Both laws are also invoked as
mechanical checks: `scripts/check_energy_law_theory.py` enforces P1's receipt-shape contract; its
prose spec (`docs/spec/energy-law-theory-v1.md`) is cited across the repo but is not present on
disk in this snapshot — a genuine gap, not a broken link you're missing something for.

**Board C-codes vs. GOAL C1–C5 vs. protocol C1–C5.** Three unrelated schemes share the letter C.
This is the single worst legibility finding in the stranger audit that produced this page — see
the disambiguation note at the top of `docs/spec/conditions-v1.md` for the full three-way split
(GOAL.md's own completion set C1–C5; this registry's anti-fraud protocol, also C1–C5, which the
board runs as plain-numbered rows; and the board's separately-named `C-<NAME>` rows).

**cbase.** The owned, from-scratch, growable seed checkpoint — `C-BASE` in the registry: an
identity of `{arch, token count, weight hashes, own-component manifest}` that is not a frozen or
borrowed base, exposes the growth-operator interface from step 0, and whose grow-operator
dry-run produces a valid larger-shape checkpoint that replays (`docs/spec/conditions-v1.md` §4.1).
On disk: `models/cbase-grow-rung/...`.

**rung-1 / rung-2.** Successive growth ("widen") events applied to `cbase`. Each rung doubles a
dimension (rung-2: FF width 16384 → 32768, net2net strict doubling, all 20 layers —
`docs/spec/rung2-grow-spec-v1.md`). rung-1's measured commutation alignment (c ≈ +0.356) carried
a reconstruction-artifact caveat; rung-2's b3 measurement (walked in full below) is the first
genuine, non-reconstructed measurement of the same quantity.

**RESET / TRANSPLANT arms.** Two ways to initialize a grown checkpoint's optimizer momentum at
the moment of a growth event. **RESET** — momentum explicitly zeroed (asserted, never a silent
fallback); this is band-(i)'s primary, binding comparison arm, because rung-1's own measurement
was de facto zero-momentum (a stale optimizer-state lookup silently fell back to zero — issue
#449). **TRANSPLANT** — the pre-grow momentum buffer is pushed forward through the same
row-duplication widen the weights receive; captured as a second, disclosed measurement that does
not gate the primary decision. (issue #449, tick-20 measurement-protocol addendum.)

**u_pre / u_post.** The optimizer-level parameter update computed immediately before a growth
event (`u_pre`) and immediately after (`u_post`), each accumulated over the full microstep window.
The question the whole rung-2 measurement protocol exists to answer: does the widen operator
*commute* with the optimizer step — i.e. does pushing `u_pre` forward through the widen map land
close to the real `u_post`? (issue #449.)

**d_comm.** The measured commutator distance between the pushed-forward `u_pre` and the real
`u_post`, read directly off a receipt as `numerator_rms / denominator_rms` (e.g. the b3 receipt:
`5.8062e-05 / 3.7198e-04 = 0.15609`). Small `d_comm` means the update and the growth operator
commute well; `d_comm` combined with the magnitude ratio `r` gives the alignment angle `c` via
the law of cosines, `c = (r² + 1 − d_comm²) / (2r)` (issue #449 board-adjudication comment).

**Bands (i) / (ii) / (iii).** The three interpretation zones the rung-2 prereg (issue #449)
freezes for the alignment `c` *before* any measurement, so the verdict can't be steered after
the fact: **band (i)** `c ∈ [0.25, 0.45]` — replicates rung-1's reported alignment; **band (ii)**
`|c| < 0.05` — near-orthogonal, the growth step and the optimizer step barely interact; **band
(iii)** — anything outside both, a genuinely new regime that neither predecessor number predicted
(this is where the real b3 measurement landed: `c = 0.988060`).

**eps_sigma.** The registered noise parameter of the growth (widen) operator: how much random
per-column perturbation is mixed into the row-duplication that grows a weight matrix.
`eps_sigma = 0` is the exact-duplication null (deterministic, used for dry-runs); real growth
events use `eps_sigma > 0` (rung-2's B2 measurement step hard-refuses a null operator — issue
#449/#452). It is a registered value in every growth receipt, not a tunable left to prose.

**Muon vs. AdamW routing.** Which optimizer updates which parameter class. **Muon**-routed:
the FF tensors (`gate_proj` / `up_proj` / `down_proj`) — Newton-Schulz-orthogonalized updates,
with an aspect-ratio LR scale (`scale = max(1, fan_out/fan_in) ** 0.5`) in the production loop
(issue #449, "OPEN INPUT #1 RESOLVED", citing `timeshare_pretrain.py`). **AdamW**-routed:
embeddings, norms, the head, and `mtp_heads` — shape-invariant across a growth event, so they
need no pushforward rule at all. Only Muon-routed FF tensors are touched by net2net widening.

**MFU (Model FLOPs Utilization).** Measured throughput as a fraction of theoretical peak GPU
FLOPs: `MFU = (FLOPs/token × tokens/s_raw) / peak_FLOPs` (`docs/domains/governance/archive/pre-restart/compute-ceiling-program-v1.md`).
It is one of the three required fields (alongside measured throughput and a required-tokens
projection) in the `C-EFF` efficiency-closure receipt (`docs/spec/conditions-v1.md` §4.1).

## 3. One receipt, walked field by field

The receipt: `receipts/cbase-grow-rung2-event-grow-rung2-20260708-real-b3.json` — the "b3"
measurement referenced throughout the glossary above (issue #466, refs #449/#448/#327/#452).

| Field | What it holds |
|---|---|
| `ticket`, `issue`, `refs` | Which tracked work this receipt belongs to (`CBASE-GROW-RUNG2-EVENT-B3`, issue #466) and which issues its protocol/corrections trace to (#449 prereg, #448 field spec, #327, #452 operator respec). |
| `run_id`, `scope` | Names the specific run (`grow-rung2-20260708-real`) and states in prose exactly what this receipt measures: the first post-grow update, forked so production is never touched. |
| `batch_pin_check` | Proves the same pinned batch was used to derive the pre-grow (`b1m`) and post-grow (`b3`) updates — `b1m_sha256 == b3_recomputed_sha256`, `match: true`. Without this, `u_pre` and `u_post` would not be comparable at all. |
| `arms.reset` / `arms.transplant` | The two arm measurements (glossary above), each carrying its own `d_comm_fields` block: `d_comm`, `numerator_rms`, `denominator_rms`, `step_rms_post`, `pushforward_step_rms`, `cos_alignment`. |
| `momentum_pushforward_rule_declared_in_writing` | States the exact per-parameter-class rule (Muon FF tensors get row-duplication or half-split pushforward; AdamW-routed params need none) *before* the numbers are read, so the rule can't be reverse-fitted to a convenient result. |
| `band_adjudication` | The frozen band boundaries from the glossary above (`band_i_range: [0.25, 0.45]`, `band_ii_abs_max: 0.05`) applied to this run's `cos_alignment`, landing on `"band": "iii"`. |
| `d448_fields_present` | A boolean confirming the fields issue #448 requires for provenance are all populated — a structural check, not a result. |
| `api_spend_usd`, `paid_api_surface_used` | `0` / `false` — L5 zero-cost-proof compliance, declared on every decisive receipt. |
| `invalid_tokens_present` | Empty here — no falsifier fired. |
| `verdict` | `"B3_CAPTURED"` — the measurement completed and is admissible; it is *not* itself a pass/fail verdict on the growth ladder. |

**Why the verdict follows:** `d_comm = 0.156090` combined with the magnitude ratio (`r ≈
1.0131`) gives `cos_alignment = 0.988060` via the law of cosines. Checked against the frozen
bands, `0.988060` falls outside both `(i)` and `(ii)` — so `band = "iii"` is the only answer the
prereg's own arithmetic supports, not a judgment call made after seeing the number.

**Known corrected caveat — read this, it is the point.** A later integration test (PR #486,
referenced in issue #449's "ADJUDICATION AMENDMENT" comment) proved that the b3 receipt's own
provenance claim — that `u_pre` came from a genuine pre-grow momentum snapshot — was **false**:
a string-vs-numeric param-ID key mismatch silently zeroed the looked-up momentum buffer, so
`u_pre` was actually computed with zero momentum, not the real (RMS 3.6e-4, 99.999% nonzero)
buffer that had genuinely been captured. The `d_comm = 0.156090` / `c = 0.988060` numbers still
stand as a valid, internally-matched measurement (zero-momentum vs. zero-momentum) — they now
answer a narrower question than the one pre-registered: the gradient/orthogonalization map
commutes; the momentum-laden optimizer step is still unmeasured. **The lesson for a stranger
reading any receipt in this repo: a receipt's own provenance field can be wrong, and finding that
out is itself part of the receipted record (the amendment lives in the issue, not a silent
edit) — never trust a receipt's self-description of its own inputs over an independent
re-derivation.**

## 4. Where state lives

`CONTINUITY.md` is the single actively-maintained position ledger - read it for the current cursor and the migrated artifact-state resolver. `STATE.md` is a one-line compatibility pointer to that resolver; it carries no independent authority and does not replace receipt evidence. `GOAL.md` is the standing goal. Receipts remain independent evidence under `receipts/` and are never upgraded by prose.

## 5. Verify one claim yourself (no GPU required)

**Start with the battery, not the board.** `docs/spec/credibility-battery-v1.md` is the 15
questions any external reviewer should ask about a project like this one, each graded
ABSENT/WEAK/STRONG with the repo-relative receipt paths a stranger can open to check the grade
themselves — it is deliberately the centerpiece of "verify a claim yourself," not a side document.
The fastest way to verify one claim: open the battery, pick any question, open the path(s) it
cites, and check the artifact's fields against the grade given. Where the battery discloses that a
cited artifact is not yet in this repository, that is the honest answer for that row today — not
something to paper over by trusting the prose instead.

Everything below runs with only Python 3.11+, no external packages, no model weights, no
credentials, no GPU (`docs/charter/REPRODUCIBILITY.md`, "Checks that require no model weights and no
GPU"):

```bash
# Validate every receipt in the repo against the schema floor
python scripts/receipt_check.py --all

# Or just prove the checker itself is sound (pure logic, no files needed)
python scripts/receipt_check.py --selftest
```

Both print a `*_SELFTEST_PASS` sentinel or a per-file findings table on success, and exit
non-zero on failure. Beyond the battery, pick any condition in `docs/spec/conditions-v1.md`, find
the receipt path(s) its CHK cites, open that JSON file, and check its fields against the
condition's own "R:" (requirement) and "Does NOT count:" text — the same read this page just
walked through for the b3 receipt above.
