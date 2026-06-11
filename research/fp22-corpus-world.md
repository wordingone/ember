# fp-22 — v0 corpus + verify-floor world for the owned 0.37B core (#122)

Frozen 2026-06-11. Consumes fp-19 (envelope: 0.37B compute-optimal FITS,
7.4B-token need, 1.9× margin at 8 days) and §8.15d (license-clean mix).
This doc is the remaining DESIGN half of the v0 launch gate; the
acquisition half is eng-36 (#130), the schedule half is eng-33 (#123,
merged), the config half is fp-19 (gated).

**Evidence-class convention (artifact-local, per the adopted boundary +
Jun-via-Kai 14492):** every load-bearing choice below carries one of
RECEIPTED / EXTERNAL-CITED / HYPOTHESIS / FABLE-DERIVED-QUARANTINED,
plus a named DISCHARGE experiment where not yet receipted. The build
lane is maximal; certification comes only from executed receipts.
Wording note: this names a bounded local training run on a ~0.37B
decoder — a candidate-substrate experiment with receipts, not a
certified frontier-development claim.

## 1. v0 corpus — license-clean ~7.4B tokens, <100GB disk HARD

Need: 7.4B tokens (RECEIPTED — fp19-bench envelope, 20 tok/param ×
368M). Acquisition: eng-36 (#130) with per-source URL-pin + sha256 +
license stamp + doc-dedup + token-count receipts.

| # | source | license basis | role | est. tokens | class |
|---|--------|---------------|------|-------------|-------|
| 1 | the-stack-v2 permissive-only slice (fallback: the-stack permissive subset if v2 gating blocks local pull) | per-file detected permissive licenses, upstream-curated | code majority | ~4.0B | EXTERNAL-CITED (license curation is upstream's receipt; our stamp re-verifies per-file fields at ingest) |
| 2 | FineWeb-Edu sample | ODC-By | quality prose | ~2.0B | EXTERNAL-CITED |
| 3 | Wikipedia EN snapshot slice | CC-BY-SA (share-alike noted in manifest; weights are not a derivative distribution of text under our use — HYPOTHESIS, discharge: license note carried in manifest either way) | reference prose | ~0.8B | EXTERNAL-CITED |
| 4 | Project Gutenberg | public domain | long-form prose | ~0.5B | EXTERNAL-CITED |
| 5 | own ledger MIT-clean slice (arc-dsl-mit class rows, fp-6 classified) | MIT (RECEIPTED — fp-6/eng-70 stamps) | in-domain seasoning, tiny | ~0.01B | RECEIPTED |

**EXCLUDED:** qwen-research-class rows (fp-6 boundary: research-license
output is not license-clean pretraining material — the adaptation-loop
episodes stay in the adaptation loop); any synthetic-from-third-party-model
text without an explicit clean license; anything failing the per-file
license stamp at ingest (fail-closed, same `parse_allow` discipline —
UNKNOWN never allow-listed).

**Mix ~60/40 code/prose by tokens.** Class: HYPOTHESIS (code-heavy mixes
aid program-synthesis-class downstream at small scale — directionally
supported in the literature but not receipted by us). DISCHARGE: the
1B/2B/4B checkpoint probes (§3) measure the only thing we need — verify
floor on the W-class world; if the floor fails while loss is healthy,
the mix is the first pre-registered suspect (recorded here, pre-run).

**Doc-dedup:** exact-hash doc-level dedup at ingest (eng-36 AC).
Class: EXTERNAL-CITED (multiplier table row 1.1×, citations carried) +
RECEIPTED-by-construction once eng-36's before/after counts land.
fp-17's lesson transfers: duplication = implicit mix weights; the
dedup receipt is the corpus-side closure of that channel.

**Disk:** ~30GB raw target, <100GB HARD (escalation bar — never
approached without user sign-off). Big files URL-pin + checksum, never
committed; manifests + receipts committed.

**Tokenizer:** 32k vocab (fp-19 config pin), trained on a stratified
~1GB sample of THIS corpus, frozen before pretrain step 0, sha-stamped
into every checkpoint receipt. Class: HYPOTHESIS (32k is the envelope's
assumption; vocab-size sensitivity at 0.37B is not receipted).
DISCHARGE: none needed for v0 — the envelope was MEASURED at vocab 32k,
so the throughput number already carries this choice; revisit only on
floor failure.

## 2. Verify-floor world — what a 0.37B core must clear

The owned core's world must satisfy: (a) exact mechanical verification
(receipts, not judgment), (b) clearable by a 0.37B-class model at
SOME curriculum level (the borrowed-core lesson: ARC-1 at 3B floor
≈ 0 → K2; never launch a core into a world whose floor it cannot
touch), (c) cheap verification (the loop's binding resource is
verified-episodes-per-GPU-hour — STATE ladder note).

**Primary: synthetic program-curriculum with exact-output verification.**
Levels frozen now (generator = fp-23's prereg; eng implementation
follows):

- **L1 — deterministic transforms:** input string/list → exact output
  (reverse, sort, filter, arithmetic fold). Verification = execute +
  exact match. Thousands of tasks generatable with held-out splits.
- **L2 — compositional transforms:** 2–3 chained L1 ops, same exact
  verification.
- **L3 — MBPP-easy band:** the rate-1.0 tasks from OUR receipts
  (RECEIPTED: the w1/r2_arms solve-rate table identifies tasks the 3B
  solves at 100% — the easiest natural-language-to-code band we own).

Class of the curriculum choice: HYPOTHESIS (a 0.37B base clears L1
after ~2B tokens — extrapolated from published sub-1B code-model
behavior, not receipted). DISCHARGE: the checkpoint probes below ARE
the discharge — this is exactly what they exist to settle, with a
pre-registered kill if the hypothesis is wrong.

**Secondary (held-out, never trained on): MBPP validation-43** — the
same surface as the borrowed-core G1, giving the only cross-core
comparable number we own (3B-with-adapter vs owned-0.37B, same harness,
same exact stats). RECEIPTED harness (w4_eval/stats_exact, merged).

## 3. Floor bar + checkpoint probe protocol (pre-registered)

Checkpoints at 1B / 2B / 4B tokens (fp-19 pin; eng-33 harness carries
them as segment boundaries).

**Probe at each checkpoint (governed, k≤16, exact verification):**
- L1 curriculum, 100 held-out tasks, k=16 → verified-episodes count +
  per-governed-GPU-minute rate.
- L2 same shape (information only until 4B; no bar).
- MBPP validation-43, k=8 (cross-core comparable; information only).

**THE FLOOR BAR (binding, frozen here):** by the **2B-token
checkpoint**, the core must produce **≥1 verified L1 episode per
governed GPU-minute at k≤16**. PASS → continue to 4B and the full
budget; the loop (W2-ingest → theta-arms → G1) ports onto the owned
core at 4B. FAIL at 2B → one pre-registered retry leg: resume to the
4B checkpoint (curriculum learning is late-onset at small scale —
HYPOTHESIS); FAIL again at 4B → **rung-kill fires**: the blocker is
core scale, escalate to the user per NC2-own rung-kill (his call:
hardware/money vs 0.1B-class fallback at 19× margin vs world redesign).
No third retry; no silent bar lowering (gate-discipline: tighten on
failure, never relax).

**Probe receipts carry:** checkpoint token-count + step + tokenizer
sha + corpus manifest sha + adapter=none assertion + pacing block +
governor block + per-level verified counts with exact CIs
(stats_exact). The boundary-eval pair around any daemon restart rides
p_gate (#124, merged).

## 4. v0 launch gate — assembly (all legs named, none waived)

| leg | artifact | state |
|-----|----------|-------|
| config | fp-19 envelope + v0 pin | GATED (receipt) |
| schedule/timeshare | eng-33 harness (#125) | MERGED (CPU selftest BIT_EXACT; dry-run continuity CLOSE at rtol=2.0; live/GPU resume-integrity RECEIPT required at the v0 run — kai 14510) |
| corpus | eng-36 (#130) receipts: per-source license + sha + dedup + token counts | OPEN (Eli, GO) |
| tokenizer | trained + frozen + sha-stamped pre-step-0 | OPEN (rides eng-36 sample) |
| world | this doc §2–§3 (curriculum generator = fp-23 prereg + eng slice) | THIS DOC |
| interlock | EMBER_GATE_AUTHORIZED=1 + --live + fp19 governor floor | MERGED (#124/#125 pattern) |
| GPU window | round-2 arms + evals complete or checkpoint-handoff per eng-33 | IN FLIGHT |

Launch order (map: ~06-13): eng-36 receipts gate → tokenizer freeze →
L1 generator selftest + held-out split receipt → dispatch segment-1
via the eng-33 runner (governed, interlocked) → probes per §3.

## 5. What fp-22 does NOT decide

- Curriculum L1 generator internals + verifier edge cases → fp-23
  (prereg: probe analysis + generator spec frozen BEFORE pretrain
  step 0, same discipline as fp-15's freeze-before-data).
- Muon vs AdamW execution detail → fp-19 pin stands (Muon-as-upside,
  pre-registered AdamW switch on fake-quant instability).
- Ternary/b1.58 substrate → staged v1 lever (STATE), untouched by v0.
- Whether the 60/40 mix is optimal → not decidable pre-run; suspect
  ordering pre-registered in §1.
