# #1719 ODC-By dataset-card admission design

<!-- goal_id: EMBER-02 -->
<!-- workstream_id: EMBER-02B -->
<!-- next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember -->

Date: 2026-08-17 PT
Source authority: issue #1719 and public Ember commit `80b34e5ef5e87b17ef5f11e8a7a716f28896bd4b`.

## Objective and boundary

Admit the exact normalized (lowercased) Hugging Face dataset-card token `odc-by` as canonical SPDX `ODC-By-1.0` only when the connector receipt reopens one root `README.md`, that README independently declares the same token in closed leading YAML front matter, and the connector license plus supplied evidence both declare `ODC-By-1.0`. The existing parser uniformly lowercases the declared token before lookup for every closed-map entry; punctuation variants and aliases remain outside the map.

The global text-lab allow-set already contains `ODC-By-1.0`; this change adds no other license, alias, connector, evidence route, corpus byte, training authority, or model-result claim. It does not mint tranche4d. The two E rows remain unresolved until this source change is independently reviewed, merged, and then consumed by a separate no-overwrite admission mint.

## Considered approaches

1. **Exact closed-map entry — selected.** Add only `"odc-by": "ODC-By-1.0"` to `_HF_DATASET_CARD_LICENSES`. Reuse the existing README reopen/hash binding and exact card/connector/evidence equality checks. This is the smallest auditable expansion.
2. **Generic SPDX normalization — rejected.** Case folding or punctuation normalization would admit unreviewed aliases and silently widen the closed set.
3. **Evidence-side override — rejected.** Trusting the caller's `declared_spdx` without the README declaration would let supplied metadata replace source evidence.

## Closed data flow

`adapt_connector_receipt` reopens all connector files and hashes them. `_bind_hf_dataset_card_license` requires the exact `hf_fetch` connector, exactly one root `README.md` matching the evidence SHA, and passes those reopened bytes to `_hf_dataset_card_license`. The parser accepts only one scalar license key in closed leading front matter. The new map entry canonicalizes only `odc-by`; the binder then requires the canonical value to equal both the connector receipt license and `evidence.declared_spdx`. The existing row and L4 receipt retain the canonical license and the canonical evidence hash.

## Tests and completion criteria

- RED: an exact `odc-by` README with connector and evidence both declaring `ODC-By-1.0` is currently refused because the token is absent from the closed map.
- Negative regression: connector/evidence claims of `ODC-By-1.0` refuse when the reopened README independently declares another token, omits the license key, changes path/hash, or uses any near-match token.
- GREEN requires the focused production adapter tests, the existing malformed/ambiguous/hash/path/license matrix, source compilation, diff check, authority guard, and independent exact-byte review.
- Public metadata must remain `Refs #1719`, nonclosing. No corpus admission, byte movement, training, sufficient-pretraining, or issue-closure credit is earned by this source change alone.

## Real-consumer successor: connector-token canonicalization

The first current-source tranche4d mint exposed a narrower missing edge before publishing output: production `hf_fetch` receipts preserve the source token as `license: odc-by`, while the adapter called the canonical-SPDX conjunction gate before applying the dataset-card closed map. The original fixture used `license: ODC-By-1.0` and therefore did not reproduce the acquisition receipt grammar.

The successor canonicalizes the single receipt-level token through `_HF_DATASET_CARD_LICENSES` only when all three route identities are exact: `source=huggingface`, connector `{name: hf_fetch, version: v1}`, and `evidence.kind=hf_dataset_card`. The existing README reopen, closed leading-frontmatter parser, evidence hash, and canonical three-way equality remain unchanged. Generic connectors remain canonical-SPDX-only. Whitespace, punctuation variants, aliases, conjunctions, and a foreign connector claiming the same token remain refused. Existing connector receipts are not rewritten because they truthfully record the acquired source token.

Completion requires a production-shaped `license: odc-by` RED/GREEN, alias and foreign-connector negatives, the full affected adapter suite, and the actual current-master tranche4d mint against the frozen connector receipts and admission plan. That real mint is the downstream-consumer proof; it does not by itself close #1719.

## Real-consumer successor: one-item dataset-card license lists

The next current-source mint reopened the exact peS2o README and found its declaration uses the YAML sequence form `license:` followed immediately by the sole item `- odc-by`; Zyda uses the scalar form. The parser therefore accepts exactly those two shapes for the sole license key: the existing scalar token, or an empty scalar remainder followed immediately by one plain token list item. After the item, only the end of front matter or a new top-level key is permitted. Both shapes feed the same lowercase closed map and retain the same reopened README hash and three-way connector/card/evidence equality.

Empty or multi-item sequences, inline flow lists, nested mappings, duplicate keys, anchors, aliases, comments, and trailing item content are refused. No generic YAML parser, normalization rule, new license, receipt rewrite, or fallback is introduced. The production-shaped peS2o list is the deliberate RED; Zyda's scalar declaration stays green. Completion still requires the actual no-overwrite three-row tranche4d mint against the frozen plan and predecessor receipt.
