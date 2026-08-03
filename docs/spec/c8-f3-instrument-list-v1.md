# C8 F3 external-instrument candidate list v1 — frozen priority order

**Status: FROZEN at authorship (2026-08-03, maintainer). Discharges obligation O3 of the F1–F4
fill amendment (issue #123, comment 4928342201, §4 and §9 item 3), tracked at #1323 after the
split from #582.** Freeze-before-sensitivity check, executed at authorship in this contract tree:
`git ls-files | grep -iE "f3|sensitiv"` returns three `EXP711-SENSITIVITY-CALIBRATION` receipts
(`receipts/exp711-apparatus/`, refs #711 #739 — window-sampling calibration for a different
program, role `calibration`) and three unrelated scripts; **no C8 F3 instrument-sensitivity
receipt exists on disk under any name.** The amendment's ordering constraint — freeze the list
BEFORE any sensitivity run — is therefore satisfied by this document landing now, and any
sensitivity receipt predating it would be inadmissible.

## 1. The binding selection rule (verbatim from the amendment, §4)

> **Instrument-shopping ban**: an ORDERED candidate instrument list is frozen now, before any
> sensitivity run; sensitivity runs on candidates in frozen order; selection = first passer; ALL
> sensitivity receipts published including failures. If no candidate passes, F3 has no instrument
> and the run is INADMISSIBLE — with the failure published, never silently swapped.

The passing test a candidate must clear is the amendment's instrument-validity positive control,
also §4: the cheap-rung A-scratch run's own mid-training checkpoint (`C_cheap/2`) scored against
its final checkpoint (`C_cheap`) on the candidate, under the §0 common CI machinery (paired
per-row NLL delta, BCa cluster bootstrap, B = 10,000, rng seed 20260709, cluster key = the
document/shard family frozen with the suite). A candidate **passes** iff `CI95 LB > 0` — the
instrument demonstrably resolves a known-direction capability gap. It is a zero-extra-training-cost
control: both checkpoints already exist from the A-scratch arm.

Consequences that are part of this freeze:

- Sensitivity runs execute **strictly in the order of §5**. A candidate may not be skipped, and a
  later candidate may not be run before an earlier one has a published receipt.
- The **first passer is the instrument.** Running further candidates after a passer, or preferring
  a later passer on any ground, is the instrument-shopping the ban names.
- Every sensitivity run emits a receipt that lands **regardless of outcome**. A failure receipt is
  the mechanism working, not a setback to be re-run away.
- Exhausting all seven candidates without a passer ⇒ **F3 has no instrument ⇒ the governed run is
  INADMISSIBLE**, published as such. It is not a licence to widen the pool.

## 2. Candidate pool rule — why the pool is closed at the frozen suite (b)

The pool is exactly the seven datasets of frozen eval-suite v1, and nothing else. This is forced,
not chosen:

- The amendment's §0 fixes F3's scoring surface as **suite (b)**, and §1's A1 precondition binds
  suite (b) to `eval_freeze_hash` = `ccde4a676085e633b69d8ba1b501b80f49e2e907`
  (`receipts/eval-suite-freeze/EVAL-FREEZE-HASH`; declaration
  `receipts/eval-suite-freeze/a1-freeze-declaration-20260709T233050Z.json`, `freeze_ts`
  2026-07-09T23:30:50Z, seven pinned datasets).
- `docs/spec/eval-suite-freeze-v1.md` and the declaration's own GPQA clause fix the amendment
  mechanism: *a dataset pinned later joins a future suite VERSION; it is never appended to a
  frozen one.*
- Therefore admitting a candidate from outside the seven would require a suite v2, a fresh
  contamination scan (Q6), a re-declaration, and a new freeze hash — all of which must land
  **before** the claim rung, resetting A1's time-ordering for a run whose whole design depends on
  it. A closed pool of seven is the only ordering executable without re-opening A1.
- The frozen definition of each candidate is **declaration + exclusion amendment**
  (`receipts/eval-suite-freeze/a1-freeze-exclusion-amendment-20260709T234148Z.json`): the
  post-exclusion row set, not the upstream row set. Sensitivity and terminal F3 both score the
  post-exclusion rows.

**Escape hatch, deliberately narrow:** widening the pool requires a dated amendment to this file
plus a suite v2 with its own freeze hash and scan, landed before any claim-rung launch, with the
seven exhausted-and-published first. Silent widening is the failure this section exists to make
impossible.

**Not a candidate, recorded so its absence is not read as oversight:** GPQA-diamond, which the
freeze declaration marks `EXCLUDED from v1` (PIN-PENDING, licence-consent gate,
`docs/deviations.md` DEV-004). It is unavailable to F3 unless it lands in a suite v2 under the
escape hatch above.

## 3. What "provenance-disjoint" means here, and against what

Ember's training-corpus provenance families, taken as the **union of the v0 and v1 assemblies**
(the conservative superset; the C8 arms' corpus is pinned in the run config, and the union cannot
under-count):

| Family | Provenance | Status |
|---|---|---|
| `code_github_clean` | GitHub public repositories, permissive-per-file licence filter | v0 + v1 |
| `wikipedia_en` | English Wikipedia dump (CC-BY-SA-4.0) | v0 + v1 |
| `gutenberg_en` | Project Gutenberg public-domain books | v0 + v1 |
| `ledger_mit` | Ember's own MIT-clean slice, licence class `arc-dsl-mit` | v0 + v1 |
| `fineweb_edu` | FineWeb educational web-text subset | v0 only — dropped from v1 as TAINTED (`receipts/corpus-mix-20260611T075802Z.json`), retained here for disjointness purposes because v0 shards were consumed |

Sources: `configs/v1-pretrain-config.json`, `receipts/corpus-census-20260710.json`,
`manifests/corpus/*`. `shards-v0` (26 `.bin`, 6,973,632,300 content tokens) is the ember
pretraining corpus per `receipts/eval-suite-freeze/a1-corpus-lineage-20260710T051001Z.json`;
`manifests/corpus/b-multi-1` (image-caption, 500 rows) was consumed by **no** completed training
run and is scanned defensively; `density-ab-*` is a proportional sample of `shards-v0` and is
covered transitively.

**Naming collision, called out to prevent a false disjointness read:** `ledger_mit`'s licence
class `arc-dsl-mit` refers to the **ARC-DSL** (Abstraction and Reasoning Corpus domain-specific
language) slice. It is unrelated to candidate #2, **ARC-Challenge** (AI2 Reasoning Challenge,
`allenai/ai2_arc`). Same three letters, different corpora, no shared provenance.

**Each candidate's disjointness rationale below carries three legs, and all three are required:**

1. **Upstream provenance family** — how the items were produced (authored, scraped, aggregated).
2. **Nearest ember family and the argument for disjointness anyway** — the honest adjacency, not
   a claim of remoteness where none exists.
3. **Measured overlap** — the per-dataset result of the executed contamination scan against all
   owned training shards (`receipts/a1-predicate-scan/a1-predicate-scan-20260709T231932Z.json`,
   per-item JSONL beside it), under the adopted #193-v2 convention (item unit, W = 13 tokens,
   contaminated iff `max_run_tokens >= 50` OR window fraction `> 0.10`).

Leg 3 is evidence, not proof: it measures text overlap with the corpus **as it stood at the
2026-07-09 scan**. Hence the re-verification trigger in §7.

## 4. Ordering rationale — why #1 before #2

The order is lexical on two keys, disjointness first:

**Key 1 (primary) — measured exclusion rate**, i.e. the fraction of the upstream test split the
contamination scan removed. This is the sharpest available measurement of provenance overlap with
the actual training shards, it comes from an executed scan rather than an argument, and it is
directly the thing F3 needs: an instrument whose rows are external in provenance. A dataset that
lost nothing is a cleaner instrument than one that had to be cut to reach zero, because the cut
itself is a selection performed on the very rows that will score the deletion arm.

**Key 2 (tie-break) — resolving power at the cheap rung**, i.e. how likely this candidate is to
clear the `CI95 LB > 0` positive control at `C_cheap/2` vs `C_cheap`. Two factors, both bearing
on the same bound: the number of independent clusters after exclusion (the cluster bootstrap's CI
width is governed by clusters, not rows), and how much per-row NLL actually moves in the second
half of a sub-1B training run. Elementary prose with worked, multi-sentence continuations moves
early; contest-level LaTeX and graduate-adversarial multiple choice are dominated by irreducible
entropy the cheap rung never resolves, so their measurable delta is small even when the row count
is large.

Scoring statistic note: F3 scores **token-weighted NLL**, not accuracy (amendment §0). Near-chance
accuracy at 0.8B is therefore not itself disqualifying — which is why the large multiple-choice
suites remain candidates at all — but it is also why they do not lead: a suite whose answer tokens
are one label among ten contributes little NLL mass that the cheap rung can move.

Applying both keys:

| Rank | Candidate | Exclusion rate (key 1) | Post-excl. rows (key 2) |
|---|---|---|---|
| 1 | GSM8K | 0 / 1319 = 0.00% | 1319 |
| 2 | ARC-Challenge | 0 / 1172 = 0.00% | 1172 |
| 3 | MATH-500 | 0 / 500 = 0.00% | 500 |
| 4 | HellaSwag | 8 / 10003 = 0.08% | 9995 |
| 5 | MMLU-Pro | 69 / 12032 = 0.57% | 11963 |
| 6 | MBPP | 12 / 500 = 2.40% | 488 |
| 7 | HumanEval+ | 58 / 164 = 35.37% | 106 |

Within the zero-rate tier the tie-break orders GSM8K > ARC-Challenge > MATH-500: GSM8K rows carry
full multi-sentence worked solutions, the largest scored-token mass per row of the three, over
1319 clusters; ARC-Challenge has a comparable cluster count but short question-plus-four-options
items, so less NLL mass per row; MATH-500 has the fewest clusters (500) *and* the least
cheap-rung-tractable content, so it is last of the clean three despite a spotless scan.

HellaSwag ranks 4th and not higher despite the largest post-exclusion row count: its rate is
nonzero, its WikiHow half is instructional web text — the nearest neighbour to `fineweb_edu` among
the non-code candidates — and its adversarial wrong endings are machine-generated rather than
human-authored, which weakens "external in provenance" as a description of a third of the token
mass on each row. (No L3 implication: L3 bans an external model touching a *training* token, and
this is eval text.) MMLU-Pro follows on rate. MBPP and HumanEval+ are last: both are Python
solution-and-docstring text, i.e. the same idiom family as `code_github_clean` even though the
items were authored rather than scraped, and HumanEval+ additionally lost 35% of its split to
exclusion, leaving 106 rows — the weakest instrument in the pool on both keys simultaneously. It
is retained as a candidate for completeness of the frozen order, not because it is expected to be
a defensible instrument.

## 5. The frozen list

Each entry: provenance family → disjointness rationale (three legs per §3) → fetch/build pointer.

**Fetch/build convention, common to all seven.** The declaration records `revision: "main"` for
every dataset. `main` is a mutable ref and is **not** the pin — the binding pin is
`test_split_sha256` over the fetched split. Fetch procedure: download the named split from the
canonical URL, re-hash, and compare against the recorded `test_split_sha256`. **A mismatch is a
fetch FAILURE**, published as such and requiring a dated amendment; it is never cured by re-pinning
to whatever upstream now serves. Harness: the standard open harness pinned by commit SHA in the
freeze receipt (`docs/spec/eval-suite-freeze-v1.md` "Harness"); prompt templates and scoring
configs are frozen in that receipt and are not tuned per candidate. Licences below were re-checked
against upstream on 2026-08-03.

---

### 1. GSM8K

- **Provenance family**: human-authored grade-school math word problems, written under
  commission by human problem-writers for the benchmark itself; not scraped from any web,
  encyclopedic, book, or code source.
- **Disjointness**: nearest ember family is `fineweb_edu` (general web text, v0 only), and the
  adjacency is topical rather than textual — the items were composed for the benchmark, so no
  upstream document of theirs exists in any ember family. Measured: **0 of 1319 items excluded**;
  the scan found nothing crossing either #193-v2 threshold against all owned shards.
- **Fetch/build**: `https://huggingface.co/datasets/openai/gsm8k`, split `test`, 1319 rows,
  `test_split_sha256` `fb581f0270b25988e071316835842a1c8449f4e27af6fc0f539ef270b987f9ff`,
  748,022 bytes. Licence: MIT (upstream `cardData.license`).

### 2. ARC-Challenge

- **Provenance family**: grade-school science examination items drawn from standardized tests,
  assembled by AI2; the Challenge split is the subset that retrieval and word-co-occurrence
  baselines both fail.
- **Disjointness**: nearest ember family is `wikipedia_en` on subject matter (elementary science),
  but exam items are not encyclopedia prose and share no source document with the dump. Unrelated
  to `ledger_mit`/ARC-DSL despite the name (§3). Measured: **0 of 1172 items excluded**.
- **Fetch/build**: `https://huggingface.co/datasets/allenai/ai2_arc`, split `test`, 1172 rows,
  `test_split_sha256` `c0e7635ee91b9ca47bf388f1f6cd5140fda083a71dccda44de72c364645df3f3`,
  425,043 bytes. Licence: CC-BY-SA-4.0 (upstream `cardData.license`).

### 3. MATH-500

- **Provenance family**: competition mathematics problems with worked solutions — the 500-item
  subset of the MATH benchmark, whose items originate in mathematics-competition archives.
- **Disjointness**: nearest ember family is `fineweb_edu` (v0 web text could in principle carry
  competition-math pages), which is exactly why the measured leg matters: **0 of 500 items
  excluded**. No competition-math source is a named ember family, and neither `gutenberg_en` nor
  `wikipedia_en` carries contest solution text. **See §7 — this candidate's margin is the one most
  exposed to a corpus acquisition under the charter's domain A.**
- **Fetch/build**: `https://huggingface.co/datasets/HuggingFaceH4/MATH-500`, split `test`, 500
  rows, `test_split_sha256`
  `200806fb17234213e909649c09a14ce01ef836b32d3bcb1a261fcf96cda4470f`, 442,443 bytes. Licence: no
  licence field is declared on the HF dataset repo (checked 2026-08-03); the upstream source,
  `github.com/hendrycks/math`, is MIT. Record the derived-licence status in the sensitivity
  receipt rather than asserting a declared licence.

### 4. HellaSwag

- **Provenance family**: sentence-completion items built over ActivityNet video captions and
  WikiHow how-to articles, with wrong endings produced by adversarial filtering against a
  generative model.
- **Disjointness**: nearest ember family is `fineweb_edu` — WikiHow is instructional web text of
  the same register, the closest adjacency of any non-code candidate. Held disjoint on two
  grounds: WikiHow is not a member of any named family, and the measured leg is **8 of 10003 items
  excluded (0.08%)**, all removed. Disclosed against it: the machine-generated distractor endings
  make part of each row's token mass model-authored rather than human-external. No L3 implication
  (L3 governs training tokens, not eval text).
- **Fetch/build**: `https://huggingface.co/datasets/Rowan/hellaswag`, split `test`, 10003 rows
  (9995 post-exclusion), `test_split_sha256`
  `6a78734fc71263f4257d9b52dbfd697830622b2eedb6473094120eed2d142a9f`, 11,663,748 bytes. Licence:
  no licence field is declared on the HF dataset repo (checked 2026-08-03); the upstream release,
  `github.com/rowanz/hellaswag`, is MIT. Same recording rule as MATH-500.

### 5. MMLU-Pro

- **Provenance family**: an aggregation and hardening of multi-domain multiple-choice examination
  material, expanded to ten options per item with distractors added by the benchmark's authors.
- **Disjointness**: nearest ember families are `wikipedia_en` and `fineweb_edu`, since the
  aggregated exam pools overlap encyclopedic and web subject matter more than any other candidate.
  This is the honest adjacency, and it is what the measured leg cut: **69 of 12032 items excluded
  (0.57%)** — the largest absolute exclusion count in the pool, though not the largest rate. The
  post-exclusion split is disjoint by measurement; the pre-exclusion split was not.
- **Fetch/build**: `https://huggingface.co/datasets/TIGER-Lab/MMLU-Pro`, split `test`, 12032 rows
  (11963 post-exclusion), `test_split_sha256`
  `5fdd1b7583302292e6d71ecf27cec521ad532bf24773beed7c5f9fd382a1b8f5`, 9,604,506 bytes. Licence:
  MIT (upstream `cardData.license`).

### 6. MBPP

- **Provenance family**: crowd-sourced, hand-written short Python programming problems with
  reference solutions and tests, authored for the benchmark.
- **Disjointness**: nearest ember family is `code_github_clean`, and the adjacency is real — the
  items are Python source in the same idiom, even though they were authored rather than scraped,
  so token-level distributional overlap is expected regardless of document-level disjointness.
  Measured: **12 of 500 items excluded (2.40%)**. Held disjoint on the authored provenance plus
  the post-exclusion scan; ranked low precisely because the family adjacency is the strongest in
  the pool after HumanEval+.
- **Fetch/build**: `https://huggingface.co/datasets/google-research-datasets/mbpp`, split `test`,
  500 rows (488 post-exclusion), `test_split_sha256`
  `88d690200dbe7f37274844b41276646481b217c4995df688914b5fb3eced79ce`, 287,032 bytes. Licence:
  CC-BY-4.0 (upstream `cardData.license`).

### 7. HumanEval+

- **Provenance family**: hand-written Python function-synthesis problems (HumanEval, authored to
  avoid duplication of public repository code), extended by EvalPlus with additional generated
  test cases.
- **Disjointness**: nearest ember family is `code_github_clean`, the same adjacency as MBPP.
  Measured: **58 of 164 items excluded (35.37%)** — by far the highest rate in the pool, leaving
  106 rows. The post-exclusion split is disjoint by measurement, but a third of the instrument was
  removed to get there, and 106 clusters is the thinnest statistical base available. Listed last
  and expected to fail the positive control; if it nonetheless passes, the sensitivity receipt
  must record the 35% exclusion prominently.
- **Fetch/build**: `https://huggingface.co/datasets/evalplus/humanevalplus`, split `test`, 164
  rows (106 post-exclusion), `test_split_sha256`
  `4e8dbe9885c253ae507acd46b280ec7085db7c889316a87d8954ae25f4eedef2`, 11,320,600 bytes. Licence:
  Apache-2.0 (upstream `cardData.license`).

## 6. Sensitivity-run protocol and receipts

For candidate `i` in the §5 order, until a passer is found:

1. Fetch the candidate per §5, verify `test_split_sha256`, apply the exclusion amendment's
   per-dataset item removals. Any hash mismatch aborts with a published failure receipt.
2. Score the cheap-rung A-scratch `C_cheap/2` and `C_cheap` checkpoints on the post-exclusion
   rows, token-weighted mean NLL per row, `delta_i = L_half(i) − L_final(i)`.
3. Compute the CI by the §0 common machinery: paired BCa bootstrap, B = 10,000, two-sided 95%,
   rng seed 20260709, cluster-resampled at the document/shard-family level with the cluster key
   frozen with the suite.
4. Emit `receipts/c8-prelaunch/f3-instrument-sensitivity-<CANDIDATE>-<UTC>.json` carrying at
   minimum: `instrument_list_sha` (this file), `candidate`, `rank`, `test_split_sha256`,
   `n_rows_post_exclusion`, `n_clusters`, `delta_mean_nats`, the bootstrap block, `passed`
   (`CI95 LB > 0`), and `ts` — **landed whether it passed or failed.**
5. On a pass: stop. That candidate is the F3 instrument, recorded in the terminal receipt's
   `f3.sensitivity{candidates[], receipts[], selected, detected}` block (amendment §7) together
   with the receipts of every candidate that failed before it. On a fail: proceed to `i+1`.
6. After candidate 7 fails: publish the exhaustion and record the governed run INADMISSIBLE for
   want of an F3 instrument.

All of this must complete **before any claim-rung launch** (amendment §1: "F3 instrument validity
receipted before any claim-rung launch"), and every receipt's `ts` must precede `launch_ts`.

**Scope resolution, stated rather than assumed.** The amendment gives suite (b) as F3's scoring
surface and simultaneously requires a selected single instrument. This file resolves the two as:
the **selected candidate alone** is F3's terminal scoring surface, scored on its full
post-exclusion row set with no further subsetting; **full suite (b)** remains the surface for the
`Δ̂_b > 0` directional conjuncts of F1 and F2. This reading is tightening-only — scoring the
deletion check on one named suite is strictly harder than scoring it on the union of seven, where
a strong signal in any one member could carry the check.

## 7. Re-verification trigger (the disjointness rationale has an expiry)

Every measured-overlap leg in §5 is the 2026-07-09 scan against the corpus **as it then stood**.
The AI-Lab Corpus Charter (`docs/ai-lab-corpus-charter.md`) commits to acquiring domains that
`receipts/corpus-census-20260710.json` grades at NONE, and the census names the intended sources
by name. Several would land directly on top of a candidate's provenance:

- Domain **A (Mathematical Foundations)** names open-web-math and proof-pile-2 — both carry
  competition-math and forum solution text, which would collapse the disjointness margin of
  **MATH-500 (#3)** and narrow **GSM8K (#1)**.
- Domain **E (ML / AI / Model Science)** names arXiv and NeurIPS/ICML proceedings, which carry
  benchmark items quoted in papers, including items from every candidate here.
- Domain **G (Formal Logic / Verification / Proof)** names Lean mathlib, adjacent to **MATH-500**.

**Binding rule:** if ANY corpus acquisition lands in a C8 arm's training config after 2026-07-09,
the Q6 contamination scan is re-run against the enlarged shard set and the affected candidate's
disjointness leg is re-verified **before** its sensitivity run — or, if the candidate was already
selected, before the claim-rung launch. A candidate whose exclusion rate rises under the re-scan
is re-ordered by §4's keys in a dated amendment to this file; it is never silently retained at its
old rank. The frozen ORDER may change only through such an amendment, and only with the re-scan
receipt cited.

## 8. Amendment rule

This file is frozen. Changes land as dated amendments appended below, each citing the receipt or
ruling that forces them; the frozen text above is never retro-edited (same custody shape as the
freeze declaration). Amendments may reorder candidates only under §7's re-scan, may widen the pool
only under §2's escape hatch, and may not relax the §1 selection rule in any direction — an
amendment that makes it easier for a candidate to be selected, or that removes the obligation to
publish failures, is out of bounds by the amendment law the F1–F4 fill was itself written under.

**Amendments:** none.

refs #1323 #582 #123 #487 #449
