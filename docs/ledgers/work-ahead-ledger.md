# Work-ahead ledger — pre-stageable work while triggers wait (est. 2026-06-12)

Per user directive 2026-06-12: the fleet never idles while planned work
exists. Every trigger-gated item has a pre-stageable half; this ledger
enumerates it as dispatchable units. The the lead BUILD tick (:41) consumes rows
top-down; each row names artifact + AC + owner. A row is removed when its
artifact merges (or its parent trigger fires and supersedes it). An empty
ledger is the only valid "nothing to build" — and emptying it is itself a
red flag to re-derive.

Posture (user, verbatim class): never "holding, stopping, because X" —
always "X is happening, moving on to Y while X happens."

| # | Row | Artifact + AC | Owner | Parent |
|---|-----|---------------|-------|--------|
| 1 | ~~NC-K e2e live proof~~ DISCHARGED | PR #332 open awaiting the lead gate (boot-checksum→mail→seat→CU→bound NCK-E2E receipt, all stages PASS) | the engineer | sp-5/#257 |
| 2 | ~~2B-verdict-chain dress rehearsal~~ DISCHARGED | an agent receipt fp24-rehearsal-20260612T143500Z + PR #336 merged (all 6 chains PASS) | an agent + the engineer | #223/#328 |
| 3 | ~~#208 probe-set reconciliation~~ DISCHARGED | PR #338 merged (closes #208): checkpoint_probe keeps 105fd370, seed23 rides 1B as separate fp28 coverage pass | the lead decide / the engineer stage | #208 |
| 4 | ~~fp-36 Band-A pre-stage~~ DISCHARGED | plumbing dry-run = #336 chains B/E (merged); dispatch template = docs/archive/pre-restart/band-a-4b-dispatch-template.md | the lead | #328 |
| 5 | ~~sp-6b designation-window tooling dry-run~~ DISCHARGED | receipts/sp6b-tooling-dryrun-20260612T192300Z.json (superseding emission, adds required ticket field per an agent flag 14982; original 155736Z content identical): selftest 7/7, synthetic dry-run exit 0, b-run-designation-* naming matches audit row 12; sp6b-b-run-* comes from replay_rig at B3 time | the lead | #282 |
| 6 | sp-3b audit tightenings before 06-20 (standing until window) | landed: @97418ec (row-8 tracking, an agent flag 14869); #344 @0295667 (row-12 battery_sha256 field pin — spec-v1 content-hash binding enforced; row-10 gains spec-v1 doc); @fa8512e (row-13 surpass-VERDICT binding via literal-value pin — closes the completion-condition-#2 gap); PR #397 @ca6ae87 (row-14 completion-condition-#1 binding: ember_tally pct_implemented==100 literal-pin — closes the symmetric gap where the audit could read ALL-RECEIPTED while ember_tally read <100%; BOTH completion conditions now mechanically bound, both GAP-NAMED today); further gaps land the same way | the lead | #214 |
| 7 | ~~Registry PARK revival configs staged~~ DISCHARGED | fp8-revival-next-width-v1.json at repo30/receipts/ledger/; revival cond: K≥4096 sites → next-width config A/B; registry row PARK quoted. Receipt: ledger-row7-row10-20260612T140836Z.json | the engineer | registry |
| 8 | ~~Receipt hygiene~~ DISCHARGED | PR #334 merged (LEGACY_EXEMPT 9 + sp6c fix; an agent adversarial verify PASS; clean-tree repro 260/9/0) | the engineer + an agent | R2 |
| 9 | ~~fp-29 synthesis-window prep~~ DISCHARGED | PR #333 merged (sha 25a51c14… reproduced at gate) | the engineer (the lead gated) | fp-29/#200 |
| 11 | ~~manifest closed-issues coverage sweep~~ DISCHARGED | C33-C40 credited; all 7 enumeration sources swept by 16:42Z — manifest denominator FULLY ENUMERATED (53→55 rows) | the lead | numeric closure |
| 12 | ~~manifest pointer fixes from an agent's sweep~~ DISCHARGED | R1+R2 applied @e4d27ef/@de9e88e; an agent receipt-minting round in flight (14886) | the lead | numeric closure |
| 13 | ~~B3 duty-battery spec freeze~~ DISCHARGED | docs/archive/pre-restart/sp6b-duty-battery-spec-v1.md FROZEN (20 episodes, 6 verb classes, decoy guards, content-hash binding); an agent adversarial pass queued pre-first-run | the lead | C55/#fp-33 |
| 14 | ~~GSM8K-200 harness issue~~ DISCHARGED (minted #341) | AC in issue: greedy determinism check, receipt schema, selftest fixtures, pinned data, governed; rides the engineer queue after #340 | the lead mint / the engineer build | C55/#fp-33 |
| 15 | ~~fp34 pre-stage~~ HALF-DISCHARGED: selftest PASS (the lead-run 16:48Z); freeze HELD — daemon check 16:55Z: NO 3B chain in flight (q3 chain COMPLETED 06-10, verdict all-zero on ARC, world moved to W-code; STATE line 146). Per fp34 prereg the freeze input = OWNED-core round-1 per-task stats, which exist only post-1B-checkpoint | trigger: owned-core-round-1-stats-receipt | the lead | C53 |
| 16 | ~~C52 scaffolding-off test spec freeze~~ DISCHARGED | docs/archive/pre-restart/c52-scaffold-off-test-v1.md FROZEN: window bounds, scaffold-off attestations (founder-process + zero-cloud audit), scripted event injection reusing sp6b verb classes, 1 verified-gain micro-round via own-r1 receipt class, content-hash binding; an agent adversarial pass before first run | the lead | C52 (GATED:C10,C13) |
| 17 | ~~sp6b v1.1 + c52 v1.1 amendments~~ DISCHARGED (all 20 findings resolved per-id in Amendments v1.1 sections; an agent verifies the diff) | resolve 11 sp6b findings (4 HIGH: D08/D18 exact paths, D14 content-based injection guard, D16 decision-evidence rule; +deterministic targets D01/D09/D11/D12/D13/D17) + 9 c52 findings (4 HIGH: A2 runtime cloud check, A3 author-filtered git log, injector identity named, gain-leg held-out bucket frozen pre-round); receipts sp6b/c52-adversarial-pass-20260612T175700Z bind finding rows | the lead | C55 + C52 |
| 10 | ~~the engineer loop: cron turn-generator~~ DISCHARGED | cron-tick-prompt.md written at the engineer/state/; CronCreate :26 (GATE) + :56 (BUILD) wired; receipt: ledger-row7-row10-20260612T140836Z.json | the engineer | loop-eng doc |
| 18 | ~~act-model refit pre-stage~~ DISCHARGED | scripts/act_model_refit.py + receipts/act-refit-20260612T225108Z.json: a ∈ (30.1, 131.7) B/unit from 5 receipted OOM/fit rows (grid's 20 EXCLUDED); b16-flash completion cell proven DECISIVE (splits interval at 45.6) — re-run+re-emit when the engineer's cells land | the lead | fp-39 leg 2 |
| 19 | ~~n=400 round-1 eval battery prep~~ DISCHARGED | fp27 METHOD AMENDMENT pre-data (r2-prereg precedent): ROUNDGATE_N 100→400 (MDE 10.16pp→3.85pp, power-helper receipts cited in code); fp32_baseline_miner anchors updated (half-widths halve, 1/√n); superseding prereg FROZEN receipts/fp27-prereg-20260612T234831Z.json; battery is GENERATED (buckets 90-99, fp-23 envelope untouched) so n=400 materializes at gate time — no static manifest needed | the lead (an agent verify queued) | H2 / #205 |
| 20 | c04 §3 gate fixture prep (G-efficiency consumes c04-class launch-efficiency receipts; stage the fixture once c04 design freezes — premature before #353) | fixture + selftest rows | the engineer (the lead gates) | #353 (GATED: c04 design) |

**Rows 1–20 are the PRE-PIVOT pretrain chain.** After the maintainer's 2026-06-13 strategic
pivot (HOLD the first real pretrain; open the owned-substrate depth track), all
pretrain-downstream rows are HOLD-gated; only row 6 (sp-3b audit tightenings,
standing till 06-20) and row 20 (c04 fixture — now moot under the HOLD) remain.
The active goal's pre-stageable work is the depth-track table below; BUILD ticks
consume IT top-down until the HOLD lifts.

## Depth track — owned substrate (ACTIVE, post-2026-06-13 pivot, parent #104)

| # | Row | Artifact + AC | Owner | Status |
|---|-----|---------------|-------|--------|
| DT-1 | delta-rule diagnostic prereg | docs/archive/pre-restart/delta-rule-diagnostic-prereg.md (c234d6a): parity band, warm+cold arms, measured exact-layer criterion, verdict→action map — FROZEN before any receipt | the lead | **DONE** |
| DT-2 | citation policy Search→ember | docs/charter/citation-policy-search-to-ember.md (e7e4601) + lineage bound into the diagnostic + the engineer's code (15442) | the lead | **DONE** |
| DT-3 | scale-probe prereg — does the owned fused-update track backprop next-token loss 10–50M → 0.37B? | probe template + band | the lead | **FREEZE DONE** (docs/archive/pre-restart/dt3-scale-probe-prereg.md, 2026-06-16): frozen scale ladder {10M,50M,~150M,0.37B}, gap(s) trajectory metric, τ=0.10 per-scale band, PASS/FAIL/INCONCLUSIVE on the whole-ladder trend, verdict→action, decoupled from the launch (no blocking dep), DT-1 lineage inherited. RUN still `GATED: DT-1 diagnostic PASS`. |
| DT-4 | retro-citation audit — scan nc-ladder for already-imported Search-origin code lacking the new header (grep hit t0/t1/t1c/t4/arcade — verify real-import vs incidental string-match) | audit note + remediation list | the lead audit / the engineer remediate | **CLOSED** (docs/archive/pre-restart/dt4-retro-citation-audit.md, 2026-06-14): 0 remediation — primitive-name grep = 0 files; 17 hits all incidental. Header enforcement is forward (DT-1 write-time, bound via DT-2), not retro. **an agent adversarial pass CLEAN** (receipt dt4-retro-citation-adversarial-verify-20260614T101900Z.json: 0 update-law hits across 5 ACs incl. renamed/paraphrased) → closes fully. |
| DT-5 | runtime-axis (tinytorch) minimal-engine scope — what ember must own above cuBLAS/tensors | scope doc | the lead | GATED: forced-autograd boundary measured (the maintainer: NOT premature rewrite) |
| DT-6 | loop-economics gate explicit (an agent 15051) — a diagnostic PASS must read as verified-signal-per-GPU-hour, not "it ran"; the equal-wall-clock band IS that metric — make it explicit in the verdict prose | prereg amendment | the lead | **DONE** (docs/archive/pre-restart/dt6-loop-economics-gate-amendment.md, 2026-06-14; checker scripts/loop_econ_gate.py = eng successor → the engineer) |

**Depth-track the lead work is exhausted/gated:** DT-1/2/4/6 DONE, DT-3/DT-5 gated on
the engineer RUNS (#24, not the lead-pre-stageable beyond the DT-3 prereg = MR-3 below). The
depth track now *feeds* the multimodal pretrain (proves the owned substrate
scales) rather than being the terminal goal.

## Multimodal pretrain readiness — PRIMARY ACTIVE (post-2026-06-14 reactivation, parent #104/E2B-surpass)

the maintainer's 2026-06-14 reactivation lifted the pretrain HOLD and named the
**multimodal-unified v0 pretrain** the active goal (E2B-surpass by 06-22). BUILD
ticks consume THIS table top-down; the depth track above is secondary/feeder.

| # | Row | Artifact + AC | Owner | Status |
|---|-----|---------------|-------|--------|
| MR-1 | multimodal-v0 config spec (the first unlocker) | docs/ember-restart/ember-multimodal-v0-config-spec.md — 4 locks + carry envelope + embedder + §IV core-size default | the lead | **DONE** |
| MR-2 | multimodal launch-authorization brief | docs/archive/pre-restart/pretrain-launch-authorization-brief-multimodal.md — 3 preconditions as receipt-gates + kill criteria + the maintainer-ask; **supersedes the stale C04-text brief** | the lead | **DONE** (2026-06-14); **UPGRADED 2026-06-16** — precondition-1 rewritten from a component checklist (locks+tok/s+corpus-present, all ✓-able while the harness trained on `make_synthetic_batch`) to an **END-TO-END real-data smoke** gate (cac5c85+17340b7). Caught the 3rd premature close: source-verified the `--live` path trains on synthetic noise, zero manifest wiring. Readiness now honestly 2/3. |
| MR-7 | v0 token-budget derivation (the budget half of the launch) | docs/archive/pre-restart/v0-multimodal-token-budget-decision.md (b963fef) — c04 §3 method; N from the smoke's REAL-data tok/s not synthetic 19,935.6 (c04 ~2× caveat); token-MIX gate (patch:text starvation→kill #4); bulk-density risk surfaced; N pre-staged to resolve at smoke-pass | the lead | **DONE** (2026-06-16); **§7 FINAL N filled** (ER-2d): 745M tok/gov-day, Chinchilla 7.37B≈9.9 days |
| MR-8 | checkpoint-1 image-grounded floor-probe prereg (kill-#6), FROZEN | docs/archive/pre-restart/v0-multimodal-floor-probe-prereg.md — operationalizes floor-contract row 47 into a mechanical checkpoint-1 verdict: paired ΔNLL (image-present vs ablated) over 1,000 held-out pairs at ~75M tok; PASS/FAIL/INCONCLUSIVE bands (ε=0.02 nats/tok, p<0.01); verdict→action; #33 linkage. Freeze-target-before-iterating so the run's continue/halt is mechanical, not re-litigated live. | the lead | **DONE** (2026-06-16). Routing: `GATED: the maintainer-launch-authorization` — becomes an the engineer run-step when the maintainer authorizes; frozen seat output until then. |
| MR-3 | DT-3 scale-probe prereg FREEZE (pre-stageable half of #18) — owned fused-update backprops next-token loss 10–50M→0.37B; freeze template+band BEFORE the DT-1 run so the probe fires the instant DT-1 passes | probe template + band, frozen | the lead | **DONE** (2026-06-16, docs/archive/pre-restart/dt3-scale-probe-prereg.md) — pre-staged exactly when its condition held (earn-the-run engineer-blocked/the maintainer-gated, nothing primary remaining). Freeze-target discipline: gap(s)-trajectory verdict mechanical the instant DT-1 passes. Decoupled from the launch (v0 ships borrowed; a DT-3 FAIL blocks nothing). RUN gated on DT-1. |
| MR-4 | fp-44 ≤1-day-bar decision-record (#21) — default Muon, written with revision criterion (no escalation) | docs/design/fp44-multimodal-optimizer-decision.md | the lead | **DONE** (2026-06-14; finalizes at #414 multimodal re-measure) |
| MR-5 | multimodal-config readiness GATE checklist — the property-level assertions I gate the engineer's #26 receipt against (locks by property not shape; rope_2d_exclusive_pass; splice exercised; bidirectional realized) so a Lock-4-class miss can't recur | gate checklist (folded into MR-2 §1 precondition-1 row) | the lead | **DONE** (in launch-auth brief) |
| MR-6 | fp-33 surpass contract multimodal honesty gap — frozen v1 (06-12) tests text/code/duty only; E2B is multimodal; "surpass" claimable without a VL bar | docs/ledgers/deviations.md DEV-001 (A4 multimodal paired bar; verdict→A1..A4∧B1..B4; eng successor = VL eval harness on B-MULTI-1 heldout) | the lead | **DONE** (2026-06-14; A4 def = the maintainer goal-level confirm on return) |

### Earn-the-run EXECUTION (the engineer via an agent — the active critical path, 2026-06-16)

Routed via mail 16639→16641→16643 (an agent read all three). Tracked here so the
chain is not mail-only (6b routing reconciliation). These flip precondition-1 +
resolve N. Seat gates each receipt at source as it lands; does NOT ping the maintainer
until ER-2's smoke is receipt-green on real data with all three fields.

| # | Row | Artifact + AC | Owner | Status |
|---|-----|---------------|-------|--------|
| ER-1 | WIRE harness→corpus | `train_multimodal_v0.py --live` loads the B-MULTI-1 manifest → real image-text batches; `make_synthetic_batch` becomes `--selftest`-only | the engineer (via an agent) | **DONE** (#437/PR #438; CorpusLoader + selftest-only confirmed at source) |
| ER-2 | SMOKE — WIRING proof (real-vs-synthetic) | governed real-data smoke; receipt `ember437-smoke-…054929Z.json` — loss 10.31→~1.0 on real b-multi-1, kill armed/not-triggered | the engineer | **DONE — WIRING GREEN.** precondition-1's wiring half proven. |
| ER-2b | BUILD-SIZE fix (368M/L20) | #439: n_layers now reads 20 (was defaulting to 1); model params=368,409,600 = §IV ✓; real-data loss 10.44→~1.5 | the engineer | **DONE** — build is now the launch config. |
| ER-2c | LEVER — real-data tok/s at LAUNCH batch/seq (the valid N-basis) | Measure EmberTransformerLayer 368M at batch=4/seq=1024 PACKED (≈4096 tok/step), ≥200 steps, rails. | the engineer (via an agent) | **DONE (source-verified #440/4528066).** `tok_s_paced=18,122.9` / raw 22,260.8 at packed 4096 tok/step, 368M/L20, 200/200, er2c_pass. N-basis VALID → N filled PROVISIONAL (brief + budget §7). **Attention-wall flag CLEARED** (22,260 raw > #434 Llama synth 19,935 — no SDPA wall). |
| ER-2d | LAUNCH LOADER — packed AND correspondence-preserving (the genuine last precondition-1 item; 6th catch) | Build a loader BOTH packed (≈4096 tok/step → N valid) AND correspondence-preserving (each image matched to ITS caption); fix the **Lock-4 multi-image RoPE** path. | the engineer (via an agent) | **DONE (source-verified PR #441, the lead-signoff posted).** `MatchedPackedCorpusLoader` K=8 matched pairs/seq, binding preserved in code, Lock-4 multi-image RoPE fixed (img_offset). `tok_s_paced=8,627.0`, 4096 tok/step, er2d_pass, mix 35.5/65.45. **FINAL N = 745M tok/gov-day; Chinchilla 7.37B ≈ 9.9 days.** Closes precondition-1 → **readiness 3/3.** |
| ER-3 | SCALE (separate pre-ask input, NOT the readiness gate) | scale corpus to carry ≥745M tokens of MATCHED image-text pairs (1-gov-day floor; Chinchilla extension = the maintainer's call), bounded <100GB; escalate to the maintainer if it needs >100GB or large external acquisition | the engineer (via an agent) | **DONE (scope).** receipt `…er3-scope-074500Z`: 1-gov-day = 7.28M matched pairs (CC3M 3.3M → ~2.8× cycling); pre-encode 3,285GB/7,246GB → **>>100GB rail BLOCKED**; **on-the-fly CC3M streaming PASSES** (~1GB metadata only). CC3M acquisition = external → **the maintainer-gated.** Corpus decision folded into the #13 packet. |
| ER-3b | STREAMING data path (no acquisition) | build the on-the-fly streaming path feeding MatchedPackedCorpusLoader, validated on the LOCAL 500-pair sample; binding preserved; retry/skip/cycle reliability notes | the engineer (via an agent) | **DONE (source-verified #442/1bd3e0a).** `StreamingMatchedPairLoader` binding preserved (no 6th-catch regression); validated local. Paced 4,152 (synchronous-encode lower bound) / raw 9,415 ≈ ER-2d compute — **network-bound N contingency added to the #13 packet** (live-URL streaming throughput unmeasurable until acquisition). |
| ER-4 | FLOOR-PROBE harness (mechanism proof, not the verdict) | build the checkpoint-1 ΔNLL floor-probe harness per the frozen MR-8 prereg; validate the mechanism on the local held-out subset; emit `mechanism_proven`/`er4_pass` receipt | the engineer (via an agent) | **SIGNED OFF (source-verified PR #443, 2026-06-16).** `_compute_nll_pair`/`_run_er4` faithful to MR-8: ablation removes image content (length held), ΔNLL=ablated−present on caption tokens, paired one-sided Wilcoxon `greater`, bands recorded-not-evaluated, interlock smoke. Receipt median 0.0/p=0.999 on untrained weights = won't false-PASS ✓. **Merge condition:** the engineer drops the bundled prereg copy (its b-multi-1 "not part of CC3M" justification is FALSE → leakage; seat lands canonical 09cb213 with URL-exclusion fix + real-tokenizer requirement). After merge → engineer earn-the-run chain COMPLETE. |

ER-2d receipt-green (source-verified PR #441) delivered the **FINAL N** (`8,627.0 × 86,400 ≈
745M tok/governed-day`; Chinchilla 7.37B ≈ 9.9 days — brief + budget §7) on the real
matched-pair launch loader, with binding preserved in code and the Lock-4 multi-image RoPE
fixed. **Readiness is now 3/3 GREEN.** The the maintainer ping (#13) is ARMED — held for the maintainer's wake (no
ping while asleep). ER-3 (corpus scale to the ≥745M-token 1-day floor) is the pre-ask parallel
item, fireable now and routed, so the engineer is not idle while authorization is pending. The remaining
seat artifact before the run starts: freeze the **checkpoint-1 image-grounded floor-probe spec**
(kill-#6) so the run's continue/halt verdict is mechanical, not re-litigated live.

Standing row classes (refill sources when the table runs low): verdict-chain
dress rehearsals for any upcoming trigger; window prep for any dated item;
audit harness tightenings; registry revival staging; receipt hygiene;
founder-loop hardening. If all are exhausted, the (c)-receipt must say which
class was checked and why it yielded nothing.
