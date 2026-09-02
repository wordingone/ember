# A1 post-freeze held-out addition — mechanical selection rule v1

**Status: FROZEN at authorship (2026-07-09, A1 eval-freeze execution lane, issue #593
deliverable 4).** One never-before-run held-out eval, selected by a published
deterministic rule — no discretionary pick.

## The rule (reproducible from this text alone)

1. **Candidate pool** (named, public, frozen in the exact order below — chosen for:
   public availability on HuggingFace without a license-consent gate, local
   runnability on the one-GPU budget, zero-cost scoring, and absence from suite (b)
   and from every prior ember eval receipt):

   | index | dataset | canonical source | split |
   |-------|---------|------------------|-------|
   | 0 | WinoGrande (winogrande_xl) | `allenai/winogrande` | validation |
   | 1 | PIQA | `ybisk/piqa` | validation |
   | 2 | OpenBookQA (main) | `allenai/openbookqa` | test |
   | 3 | BoolQ | `google/boolq` | validation |
   | 4 | CommonsenseQA | `tau/commonsense_qa` | validation |
   | 5 | LAMBADA (standard) | `EleutherAI/lambada_openai` | test |
   | 6 | TruthfulQA (multiple_choice) | `truthfulqa/truthful_qa` | validation |
   | 7 | SciQ | `allenai/sciq` | test |

2. **Selection function**: with `H` = `eval_freeze_hash` (the 40-hex-char commit sha
   declared by the A1 freeze receipt), the selected candidate is

   ```
   index = int(H[:8], 16) mod 8
   ```

   — the first 8 hex characters of the freeze hash, read as an unsigned integer,
   modulo the pool size. One line, no tunable parameter, no re-draw clause: whatever
   index falls out IS the selection.

3. **Never-before-run check** (part of the rule, mechanical): the selected dataset's
   name must not appear in any receipt enumerated by the quarantine pass
   (`receipts/eval-suite-freeze/a1-prefreeze-quarantine-*.json` enumeration source:
   `git ls-files receipts/`). All eight candidates were verified absent at authorship;
   if a future re-derivation ever finds the selected candidate cited pre-freeze, the
   selection moves to `(index + 1) mod 8` — deterministic collision handling, also
   part of this frozen rule.

## What the selection produces

The selected eval is the **post-freeze held-out addition**: it was provably not
chosen for favorable numbers (the freeze hash did not exist before the freeze commit,
and the pool + rule are frozen in the same PR that creates the hash). Its pin
(revision sha + test-split sha256 + row count) joins the NEXT suite version (v2) per
the freeze doc's versioning law — a frozen suite is never appended to. Until pinned
into v2 it may be run as a development signal only.

## Why this shape

The falsifier fill (refs #123) requires the held-out addition to be immune to
selection-after-results; a deterministic function of a commit sha that cannot exist
before the freeze is the cheapest such commitment (same mechanism class as
hash-committed placement generators, refs #582 O4). The reader check: recompute
`int(H[:8], 16) mod 8` from the declared `eval_freeze_hash` and confirm the claimed
selection matches.
