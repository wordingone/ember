# CourtListener wave-1 content disposition

The existing L4 `raw/courtlistener/manifest.jsonl` is the byte authority for
the four acquired files. Its largest row, `opinion-clusters-2026-06-30.csv.bz2`
(2,457,231,057 bytes), is a CourtListener bulk export whose bounded header/sample
contains metadata fields and no observed prose cells. The other three rows are
structured court metadata/citation exports. They are therefore not admitted as
prose-gap training yield by byte size.

The content sidecar is `content-annotation-v1.json` in the raw custody root and
the matching checked-in projection is
`manifests/corpus/courtlistener-content-annotation-v1.json`. Both bind the exact
L4 manifest byte hash, source paths, source hashes/bytes, selection rules, and a
bounded eight-row schema sample. The sidecar is additive: it does not replace
the connector receipt or authorize training by itself.

To recreate the raw sidecar without downloading or rewriting corpus bytes:

```text
python -B src/ember/infrastructure/tools/corpus_connectors/courtlistener_custody.py \
  --manifest <RAW_CUSTODY_ROOT>/courtlistener/manifest.jsonl \
  --data-root <RAW_CUSTODY_ROOT>/courtlistener \
  --output <RAW_CUSTODY_ROOT>/courtlistener/content-annotation-v1.json \
  --sample-rows 8
```

The command is refusal-first and will not overwrite an existing sidecar. Its
projection is `eligible_prose_bytes=0` and `eligible_sources=[]`; this is a
write-off of the wave-1 CourtListener prose-gap slot, not a claim that the raw
bytes are deleted or that a re-fetch occurred. A future opinion-text bulk
acquisition must use `http_fetch` with its own L4 receipt and a distinct
selection rule before it can enter the prose projection.
