# #1719 ODC-By dataset-card admission design

<!-- goal_id: EMBER-02 -->
<!-- workstream_id: EMBER-02B -->
<!-- next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember -->

Date: 2026-08-17 PT  
Source authority: issue #1719 and public Ember commit `80b34e5ef5e87b17ef5f11e8a7a716f28896bd4b`.

## Objective and boundary

Admit the exact Hugging Face dataset-card token `odc-by` as canonical SPDX `ODC-By-1.0` only when the connector receipt reopens one root `README.md`, that README independently declares exactly `license: odc-by` in closed leading YAML front matter, and the connector license plus supplied evidence both declare `ODC-By-1.0`.

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
