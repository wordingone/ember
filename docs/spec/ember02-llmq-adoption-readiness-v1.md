# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

# #1413 CPU/file-only LLMQ adoption readiness artifact

This is a CPU/file-only preparation artifact for the current Ember repository. It is not a launcher, trainer,
model authority, benchmark, or result receipt. The current Ember tree has no
pinned LLMQ dev source/build receipt or one-RTX-4090 3B benchmark receipt.

The checker therefore fails closed with `PRELAUNCH_REJECTED` until a safe
relative LLMQ source path is reopened and its raw bytes match `source_sha256`,
and a separately reopened, content-addressed source manifest binds that path,
the exact 40-hex source commit, a 64-hex source-tree identity, and the
non-empty command lineage. The build receipt and benchmark receipt are never
accepted as inline dictionaries: each must be a safe relative artifact path,
match its declared raw SHA-256, carry a self-hash over canonical JSON bytes,
and bind the source commit/tree and non-empty command lineage. The build
receipt also reopens the binary path and rehashes its raw bytes; the benchmark
receipt binds that build-receipt SHA, exact `Qwen2.5-3B`/`RTX 4090` identity,
`PASS` status, and finite positive FP8/BF16 tok/s fields. Both the
adoption-design and mechanism-attribution paths are reopened and rehashed
against their digests. A missing benchmark receipt remains an explicit
external remainder; an incomplete, inline, foreign, or drifted artifact is a
prelaunch refusal.
With those static identities present but no benchmark receipt, it reports
`READY_FOR_EXTERNAL_EXECUTION` while the actual governed LLMQ build and 4090
benchmark remain an explicit external remainder. Any eventual execution must
route through Ember CLI -> Ember Lab.

The checked-in CLI is deterministic and path-free at the output boundary:

```text
python -B scripts/llmq_adoption_readiness.py --payload <packet.json> \
  --source-root <repository-root> --out <readiness-receipt.json>
```

It returns exit 3 and writes a content-addressed `PRELAUNCH_REJECTED` receipt
when a source, build, design, attribution, or benchmark operand is absent,
foreign, malformed, or drifted. It never launches LLMQ or Ember Lab.
