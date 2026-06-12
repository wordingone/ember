# Density A/B spec v1 — curated vs bulk shard mix (2026-06-12)

Eli proposal; Leo gates before freeze. Linked from c04-token-budget-v1.md
§F-3. This is the cheapest decision-changing receipt on the board: it
prices H2/L8 and gates the c04 (P, budget) pair.

Receipt target: `receipts/density-ab-{ts}.json`

---

## 1. The question

Does the current bulk v0 corpus mix yield a meaningfully lower W-code
floor metric than a curated (code-dominant) mix, **at matched FLOPs**?

The budget doc shows c03-shape affords 3.51B tokens/day at the measured
production rate (8,872 tok/s). Chinchilla-optimal for 284M params needs
5.69B tokens. Required density multiplier: **1.62×**. This A/B measures
whether the density gap is real and of the right magnitude to close.

---

## 2. Arm definitions (from v0 corpus provenance)

Both arms tokenize from `B:/M/avir/eli/state/ember-eng/corpus-v0/`
(v0 freeze receipt `corpus-mix-20260611T075802Z.json`) using the frozen
v0 tokenizer. Source-level token totals from that receipt:

| source | tokens | fraction |
|---|---|---|
| code_github_clean | 4,053M | 58.1% |
| fineweb_edu | 1,667M | 23.9% |
| wikipedia_en | 747M | 10.7% |
| gutenberg_en | 506M | 7.3% |
| ledger_mit | 0.23M | <0.1% |
| **total** | **6,974M** | 100% |

**Arm A — bulk (current v0 mix):** draw 100M tokens proportionally from
the existing v0 binary shards (`shards-v0/v0-0000*.bin`). This reuses
the packed, packing-waste-free token stream from the live run. Shard
assignment: take contiguous windows from shards 0..25 at the current
sequence packing, stopping at the 100M-token mark. No re-tokenization
needed.

**Arm B — curated (code-only):** draw 100M tokens exclusively from
`corpus-v0/code_github_clean/` JSONL files, re-tokenized and packed at
seq=1024 (same packing protocol as v0 assembly). Adds `ledger_mit`
(232K tokens, 0.23% → all of it, padded to fill). Code fraction: ~100%
(vs 58.1% in arm A). This maximizes the density hypothesis: W-code is
structured code-adjacent syntax; github code is the closest proxy in
the v0 corpus.

**Matched FLOPs:** both arms use the same training config and identical
token count (100M). FLOP difference: zero by construction.

---

## 3. Training config

| field | value |
|---|---|
| model | c01 (hidden=640, layers=12, heads=10, vocab=32000) |
| params | ~79M |
| tokens per arm | 100M (matched) |
| seq | 1024 |
| batch | 8 (c01 nominal from fp19) |
| steps per arm | 100M / (8 × 1024) ≈ 12,207 steps |
| optimizer | AdamW (no Muon — c01 bench config; density comparison is optimizer-neutral) |
| QAT | enabled (v0 config; same fake-quant scheme) |
| governor | VRAM 0.80, MARGIN 1.5 GiB, PACE 0.05s — never loosened |
| estimated wall time | ~40 min each arm at c01 throughput ~30k tok/s paced |

No checkpoint during the bench — single segment, no resume complexity.
State saved at end of arm for reproducibility.

---

## 4. Eval metric and MDE

**Floor metric:** W-code generation rate — fraction of eval prompts for
which the model produces a syntactically valid W-code block.

**Eval set:** n=400 W-code prompts (from the H2/round evaluation set, or
a frozen n=400 draw from the same distribution). Power math from budget
doc: at n=400, MDE = 3.85pp (visible delta ≥ ~4 percentage points).

**Signal criterion:** |rate_B − rate_A| ≥ 4pp → density hypothesis
CONFIRMED; arm B data worth curating. |delta| < 4pp → no detectable
advantage; bulk mix is sufficient at 100M tokens (H2 interpretation
required — the bulk run may still underfit at 100M).

**Null control:** if BOTH arms produce rate < 1% (model too small / too
few tokens to generate valid W-code at all), the bench is
UNINFORMATIVE. Mitigate: run a 3rd cell (arm A, 200M tokens) to confirm
the 100M budget is above the learning threshold before concluding.
Report all three rates.

---

## 5. Shard preparation

**Arm A:** no new shards — read directly from existing `shards-v0/*.bin`
via the production shard loader (same interface as timeshare_pretrain.py
`ShardLoader`). Slice by step count (12,207 steps × 8 × 1024 = 100M
tokens from the beginning of the stream). This is deterministic and
uses the exact v0 packing without re-assembly.

**Arm B:** re-tokenize `corpus-v0/code_github_clean/*.jsonl` + all of
`corpus-v0/ledger_mit/*.jsonl`. Pack at seq=1024. Write to a temporary
shard file `density-ab-curated-100M.bin`. Estimated tokenization wall
time: ~5 min at the v0 assembly throughput. Add this to the <1h budget.

---

## 6. Receipt schema

```json
{
  "ticket": "DENSITY-AB-V1",
  "ts": "...",
  "issue": 225,
  "arm_a": {
    "label": "bulk-v0-mix",
    "source_shards": "v0-00000..v0-00025, first 100M tokens",
    "code_fraction": 0.581,
    "tokens": 100000000,
    "training_steps": 12207,
    "final_wcode_rate": null
  },
  "arm_b": {
    "label": "curated-code-only",
    "sources": ["code_github_clean", "ledger_mit"],
    "code_fraction": 1.0,
    "tokens": 100000000,
    "training_steps": 12207,
    "final_wcode_rate": null
  },
  "mde_n": 400,
  "mde_pp": 3.85,
  "delta_pp": null,
  "verdict": null
}
```

**Verdict ladder:**
- `DENSITY_CONFIRMED` — |delta| ≥ 4pp, arm B > arm A
- `DENSITY_REVERSED` — |delta| ≥ 4pp, arm A > arm B (unexpected; re-examine W-code eval quality)
- `DENSITY_BELOW_MDE` — |delta| < 4pp; no detectable advantage
- `UNINFORMATIVE` — both rates < 1%

---

## 7. Gate linkage

This receipt, once filed, gates c04 token budget §F-3:
- `DENSITY_CONFIRMED` → curated mix required; density multiplier obligation stands; c04 curriculum spec must cite a curated assembly plan
- `DENSITY_BELOW_MDE` → bulk mix is acceptable at the affordable budget; curriculum density is not load-bearing
- `UNINFORMATIVE` → must re-run at larger n or longer training; the c04 pick is DEFERRED until receipt is informative

Gate-9 (#349) variant: any c04 pretrain ≥12 GPU-h that cites bulk corpus without a density receipt class = LAUNCH BLOCKED.

---

## 8. Owner + order

- **Eli:** shard prep (arm B tokenization) + training harness + receipt emission
- **Leo:** approve this spec (gate before freeze), gate the verdict, update c04 budget doc at fp-39-recalibrated rates
- **Order:** fp-39 prod bench first → recalibrate budget table → then density A/B bench
