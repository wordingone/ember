# C1M-1 branch-deletion manifest (review-only)

goal_id: EMBER-02
workstream_id: EMBER-02C
next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

This is a proposal, not a deletion authorization. It records the three exact
merged candidates named by C1M-1. No remote ref may be deleted until the authorized reviewer
accepts this manifest at an immutable PR head.

## Snapshot and law

- Repository: `wordingone/ember`
- Snapshot: public `master` `c8ce2dd4022cc03533b31059c667b90365da60d5`
- Evidence time: 2026-07-18T00:00Z (GitHub API, safe wrapper)
- Equivalence law: a candidate is prunable only when its PR is merged, its
  merge commit is reachable from current `master`, every PR-changed path is
  present in the merge tree, and no open PR still uses the ref. Squash merge
  means the PR head itself need not be an ancestor of `master`; the merge
  commit and path/blob evidence are the authority.
- Protection: each candidate protection endpoint returned HTTP 404
  (`Branch not protected`). This is evidence, not permission to delete.

## Candidate records

| PR | ref | current ref SHA | base SHA | PR head SHA | merge commit | state | open-PR query | merge reachability |
|---:|---|---|---|---|---|---|---|---|
| 385 | `feat/main-tree-guard` | `198a18b83e6fc19594eadfd6896d99bfb76ca570` | `e115e020311566b149acda5f0336648fe71cb414` | `198a18b83e6fc19594eadfd6896d99bfb76ca570` | `16ed66ab345f45e835d84e094c6c49a1253bb439` | closed/merged | only closed #385; no open match | `master...merge`: behind 663, ahead 0 |
| 403 | `fix/issue-400` | `d105e2e7b454839d12873c5a22a0c6e4b5cfc1d1` | `3848c8feef4437688983273d8e8a0b732f02534d` | `d105e2e7b454839d12873c5a22a0c6e4b5cfc1d1` | `06834127cd104bb3cc92b8b7522fc4ad3356ca51` | closed/merged | only closed #403; no open match | `master...merge`: behind 653, ahead 0 |
| 409 | `fix/custody-sidecar-401` | `d938e32a2e52b3edb374238b39c161f5a66839f1` | `06834127cd104bb3cc92b8b7522fc4ad3356ca51` | `d938e32a2e52b3edb374238b39c161f5a66839f1` | `d134d51f67a64fc739739b93fd05394f97881a67` | closed/merged | only closed #409; no open match | `master...merge`: behind 652, ahead 0 |

`base...head` was respectively 1, 6, and 1 commit ahead. `master...head`
is intentionally diverged for each because these were squash-merged; this is
why the manifest binds the merged commit and the path evidence rather than
using head ancestry as a deletion shortcut.

## Path/blob evidence

For every row below, `merge_blob` is present in the merged tree. A differing
`master_blob` means later public edits, not branch-only content. `head_blob`
and `merge_blob` are equal for every changed path.

### PR 385

| path | head_blob | merge_blob | master_blob |
|---|---|---|---|
| `.githooks/pre-commit` | `f0663d933634887b3b86a12b2b08b8c219e0c01f` | `f0663d933634887b3b86a12b2b08b8c219e0c01f` | `efe8bc7e0c8baa7725056216a59f4cb14eacd17c` |

### PR 403

| path | head_blob | merge_blob | master_blob |
|---|---|---|---|
| `receipts/disconfirmation-eval-20260707T173924Z.json` | `08b179c735c78396937355573899baf933a41032` | `08b179c735c78396937355573899baf933a41032` | `08b179c735c78396937355573899baf933a41032` |
| `receipts/disconfirmation-eval-20260707T174158Z.json` | `f7d847ee064067107ce78f26d647c7e9224b3067` | `f7d847ee064067107ce78f26d647c7e9224b3067` | `f7d847ee064067107ce78f26d647c7e9224b3067` |
| `receipts/disconfirmation-eval-20260707T184903Z.json` | `46a8a19d9b9e46b269ca9718955fa87605ee504f` | `46a8a19d9b9e46b269ca9718955fa87605ee504f` | `46a8a19d9b9e46b269ca9718955fa87605ee504f` |
| `receipts/milestone-reconciliation-20260707T173937Z.json` | `e51328e69680e8ebfdf5529d6e7ec52b5895c47e` | `e51328e69680e8ebfdf5529d6e7ec52b5895c47e` | `e51328e69680e8ebfdf5529d6e7ec52b5895c47e` |
| `receipts/milestone-reconciliation-20260707T174211Z.json` | `922a2f531f9e0fe3d6237550db21f314187a529a` | `922a2f531f9e0fe3d6237550db21f314187a529a` | `922a2f531f9e0fe3d6237550db21f314187a529a` |
| `receipts/milestone-reconciliation-20260707T184931Z.json` | `ae6d338198ed4f6a6ba181a01f8d5884844ab7b5` | `ae6d338198ed4f6a6ba181a01f8d5884844ab7b5` | `ae6d338198ed4f6a6ba181a01f8d5884844ab7b5` |
| `receipts/milestone-reconciliation-20260707T205426Z.json` | `87eb6b0423fbe0ea25af37b74d3da01e95b8891d` | `87eb6b0423fbe0ea25af37b74d3da01e95b8891d` | `87eb6b0423fbe0ea25af37b74d3da01e95b8891d` |
| `receipts/publication-gate-20260707T173926Z.json` | `4c1b4133cc096eb538e36374c65ec2a4c5e0009c` | `4c1b4133cc096eb538e36374c65ec2a4c5e0009c` | `039070cb5a2b76fd547e5f0c6f88f3703305dea1` |
| `receipts/publication-gate-20260707T174201Z.json` | `723eefb22d4916e2f042ee87737f05be60ac6759` | `723eefb22d4916e2f042ee87737f05be60ac6759` | `ddf04eb32548bdbb996993849ca727acfe4f7ce1` |
| `receipts/publication-gate-20260707T184909Z.json` | `b2d50e387ec44d38b4676af16cee8028b58e2fbe` | `b2d50e387ec44d38b4676af16cee8028b58e2fbe` | `42d41de5610c1a5318d5ffefbed79e8a5d345e6d` |
| `receipts/publication-gate-20260707T205415Z.json` | `b5fb2f35ab40eb4747e30dd108724b0aeffdf3ff` | `b5fb2f35ab40eb4747e30dd108724b0aeffdf3ff` | `1e6db9e2943b2c5b8e05a622101a148f0ccb6dcf` |
| `scripts/check_milestone_reconciliation.py` | `4274c32db0b1bd736b3cdf55f00ebcf444adc3a7` | `4274c32db0b1bd736b3cdf55f00ebcf444adc3a7` | `4274c32db0b1bd736b3cdf55f00ebcf444adc3a7` |
| `scripts/check_publication_gate.py` | `b9a24ac58b69cbbac154c5b58c8c071637d521e8` | `b9a24ac58b69cbbac154c5b58c8c071637d521e8` | `b9a24ac58b69cbbac154c5b58c8c071637d521e8` |
| `scripts/ember_totality/c_comprehensive_receipts_custody_test.py` | `3108c417c52e3dbe387d7dedaee131744d795b68` | `3108c417c52e3dbe387d7dedaee131744d795b68` | `3108c417c52e3dbe387d7dedaee131744d795b68` |
| `scripts/ember_totality/receipts-totality/ember-totality-20260708T033700Z.json` | `3329b3077836bf5881cd7b9f06a507b9f4bb9dfa` | `3329b3077836bf5881cd7b9f06a507b9f4bb9dfa` | `5376e5c569239478c8b470a0564d97b5573e692f` |
| `scripts/ember_totality/receipts-totality/ember-totality-20260708T034014Z.json` | `20e06ef52176ceb508953977cd1b2c0d0f511bc5` | `20e06ef52176ceb508953977cd1b2c0d0f511bc5` | `61054671de25c057492ee12e5a5faec2ecd91c10` |
| `scripts/ember_totality/writers_custody_two_run_test.py` | `9a0b02d3d6a1fab6e1161a14ed318bd7abaf2a0a` | `9a0b02d3d6a1fab6e1161a14ed318bd7abaf2a0a` | `9a0b02d3d6a1fab6e1161a14ed318bd7abaf2a0a` |

### PR 409

| path | head_blob | merge_blob | master_blob |
|---|---|---|---|
| `scripts/ember_totality/c_custody_sidecar_agewindow_test.py` | `f5c8bd8c7e7ee5193b83573c1f202eccf1105967` | `f5c8bd8c7e7ee5193b83573c1f202eccf1105967` | `f5c8bd8c7e7ee5193b83573c1f202eccf1105967` |
| `scripts/ember_totality/test_c_custody.py` | `5499ecdda3aa09dab2bd6692fb09f6f324cfd80e` | `5499ecdda3aa09dab2bd6692fb09f6f324cfd80e` | `a92cc36c997359291778e30abd0e793a2d274ac6` |

## PR 403 intermediate-commit audit

The complete six-commit chain was refreshed from the PR API. The path digest is SHA-256 over sorted LF-terminated commit-file paths. Every path and its blob disposition is listed; `retained` means present in the merged tree/current master, `later-removed` means intentionally removed by the named later commit and is not branch-only residue.

| commit | path | blob SHA | content disposition |
|---|---|---|---|
| `c71ad32c88627a16f4752aa246f547813f26e4ba` | `scripts/check_milestone_reconciliation.py` | `4274c32db0b1bd736b3cdf55f00ebcf444adc3a7` | retained |
| `c71ad32c88627a16f4752aa246f547813f26e4ba` | `scripts/check_publication_gate.py` | `b9a24ac58b69cbbac154c5b58c8c071637d521e8` | retained |
| `c71ad32c88627a16f4752aa246f547813f26e4ba` | `scripts/ember_totality/c_comprehensive_receipts_custody_test.py` | `3108c417c52e3dbe387d7dedaee131744d795b68` | retained |
| `db541939ccbabc7d38ad4eed98152b83a3e93d87` | `receipts/disconfirmation-eval-20260707T173924Z.json` | `08b179c735c78396937355573899baf933a41032` | retained |
| `db541939ccbabc7d38ad4eed98152b83a3e93d87` | `receipts/disconfirmation-eval-20260707T174158Z.json` | `f7d847ee064067107ce78f26d647c7e9224b3067` | retained |
| `db541939ccbabc7d38ad4eed98152b83a3e93d87` | `receipts/disconfirmation-eval-20260707T184903Z.json` | `46a8a19d9b9e46b269ca9718955fa87605ee504f` | retained |
| `db541939ccbabc7d38ad4eed98152b83a3e93d87` | `receipts/milestone-reconciliation-20260707T173937Z.json` | `e51328e69680e8ebfdf5529d6e7ec52b5895c47e` | retained |
| `db541939ccbabc7d38ad4eed98152b83a3e93d87` | `receipts/milestone-reconciliation-20260707T174211Z.json` | `922a2f531f9e0fe3d6237550db21f314187a529a` | retained |
| `db541939ccbabc7d38ad4eed98152b83a3e93d87` | `receipts/milestone-reconciliation-20260707T184931Z.json` | `ae6d338198ed4f6a6ba181a01f8d5884844ab7b5` | retained |
| `db541939ccbabc7d38ad4eed98152b83a3e93d87` | `receipts/milestone-reconciliation-20260707T205426Z.json` | `87eb6b0423fbe0ea25af37b74d3da01e95b8891d` | retained |
| `db541939ccbabc7d38ad4eed98152b83a3e93d87` | `receipts/publication-gate-20260707T173926Z.json` | `4c1b4133cc096eb538e36374c65ec2a4c5e0009c` | retained (later content evolution) |
| `db541939ccbabc7d38ad4eed98152b83a3e93d87` | `receipts/publication-gate-20260707T174201Z.json` | `723eefb22d4916e2f042ee87737f05be60ac6759` | retained (later content evolution) |
| `db541939ccbabc7d38ad4eed98152b83a3e93d87` | `receipts/publication-gate-20260707T184909Z.json` | `b2d50e387ec44d38b4676af16cee8028b58e2fbe` | retained (later content evolution) |
| `db541939ccbabc7d38ad4eed98152b83a3e93d87` | `receipts/publication-gate-20260707T205415Z.json` | `b5fb2f35ab40eb4747e30dd108724b0aeffdf3ff` | retained (later content evolution) |
| `db541939ccbabc7d38ad4eed98152b83a3e93d87` | `scripts/ember_totality/receipts-milestone/milestone-reconciliation-20260708T034146Z.json` | `e6975d8d209ad4f67e45f3f59758eec8b0c44a8d` | later-removed by `965863ba` |
| `db541939ccbabc7d38ad4eed98152b83a3e93d87` | `scripts/ember_totality/receipts-milestone/milestone-reconciliation-20260708T034147Z.json` | `6c2a5339cfdadf7a3897fd585376157ce6b8caf2` | later-removed by `965863ba` |
| `db541939ccbabc7d38ad4eed98152b83a3e93d87` | `scripts/ember_totality/receipts-publication/publication-gate-20260708T034147Z.json` | `c850a070d4d985f47c3c5d7156fe0b47958241cb` | later-removed by `965863ba` |
| `db541939ccbabc7d38ad4eed98152b83a3e93d87` | `scripts/ember_totality/writers_custody_two_run_test.py` | `9a0b02d3d6a1fab6e1161a14ed318bd7abaf2a0a` | retained |
| `d01b59fe5c223cafc6999e05dce5e12b55af4519` | `scripts/ember_totality/receipts-totality/ember-totality-20260708T033700Z.json` | `3329b3077836bf5881cd7b9f06a507b9f4bb9dfa` | retained |
| `d01b59fe5c223cafc6999e05dce5e12b55af4519` | `scripts/ember_totality/receipts-totality/ember-totality-20260708T034014Z.json` | `20e06ef52176ceb508953977cd1b2c0d0f511bc5` | retained |
| `5ebc9ef8a7c5d6fea222da75fb24277c325eb167` | `receipts/ember-m10-surface3/2026-06-28T03-17-28Z/temp-home/baseline/.avir/plugins/marketplaces/claude-plugins-official` | `30a213f9b39e3c40b0073bb5b41081da9f2b6634` | later-removed by `d105e2e7` |
| `5ebc9ef8a7c5d6fea222da75fb24277c325eb167` | `receipts/ember-m10-surface3/2026-06-28T03-17-40Z/temp-home/baseline/.avir/plugins/marketplaces/claude-plugins-official` | `30a213f9b39e3c40b0073bb5b41081da9f2b6634` | later-removed by `d105e2e7` |
| `5ebc9ef8a7c5d6fea222da75fb24277c325eb167` | `receipts/ember-m10-surface3/2026-06-28T03-21-56-952Z/home-avir/.avir/plugins/marketplaces/claude-plugins-official` | `30a213f9b39e3c40b0073bb5b41081da9f2b6634` | later-removed by `d105e2e7` |
| `5ebc9ef8a7c5d6fea222da75fb24277c325eb167` | `receipts/ember-m10-surface3/2026-06-28T05-44-30-Z/home-A2-baseline/.avir/plugins/marketplaces/claude-plugins-official` | `30a213f9b39e3c40b0073bb5b41081da9f2b6634` | later-removed by `d105e2e7` |
| `5ebc9ef8a7c5d6fea222da75fb24277c325eb167` | `receipts/ember-m10-surface3/2026-06-28T05-44-30-Z/home-A3-baseline/.avir/plugins/marketplaces/claude-plugins-official` | `30a213f9b39e3c40b0073bb5b41081da9f2b6634` | later-removed by `d105e2e7` |
| `5ebc9ef8a7c5d6fea222da75fb24277c325eb167` | `receipts/ember-m10-surface3/2026-06-28T05-48-42-Z/home-A2-baseline/.avir/plugins/marketplaces/claude-plugins-official` | `30a213f9b39e3c40b0073bb5b41081da9f2b6634` | later-removed by `d105e2e7` |
| `5ebc9ef8a7c5d6fea222da75fb24277c325eb167` | `receipts/ember-m10-surface3/2026-06-28T06-58-45Z/home-r1-baseline/.avir/plugins/marketplaces/claude-plugins-official` | `30a213f9b39e3c40b0073bb5b41081da9f2b6634` | later-removed by `d105e2e7` |
| `5ebc9ef8a7c5d6fea222da75fb24277c325eb167` | `receipts/ember-m10-surface3/2026-06-28T06-58-45Z/home-r2-baseline/.avir/plugins/marketplaces/claude-plugins-official` | `30a213f9b39e3c40b0073bb5b41081da9f2b6634` | later-removed by `d105e2e7` |
| `5ebc9ef8a7c5d6fea222da75fb24277c325eb167` | `receipts/ember-m10-surface3/2026-06-28T06-58-45Z/home-r3-baseline/.avir/plugins/marketplaces/claude-plugins-official` | `30a213f9b39e3c40b0073bb5b41081da9f2b6634` | later-removed by `d105e2e7` |
| `5ebc9ef8a7c5d6fea222da75fb24277c325eb167` | `receipts/ember-m10-surface3/2026-06-28T07-40-42Z/home-r1-baseline/.avir/plugins/marketplaces/claude-plugins-official` | `30a213f9b39e3c40b0073bb5b41081da9f2b6634` | later-removed by `d105e2e7` |
| `5ebc9ef8a7c5d6fea222da75fb24277c325eb167` | `receipts/ember-m10-surface3/2026-06-28T07-40-42Z/home-r2-baseline/.avir/plugins/marketplaces/claude-plugins-official` | `30a213f9b39e3c40b0073bb5b41081da9f2b6634` | later-removed by `d105e2e7` |
| `5ebc9ef8a7c5d6fea222da75fb24277c325eb167` | `receipts/ember-m10-surface3/2026-06-28T07-40-42Z/home-r3-baseline/.avir/plugins/marketplaces/claude-plugins-official` | `30a213f9b39e3c40b0073bb5b41081da9f2b6634` | later-removed by `d105e2e7` |
| `965863ba591c23c055041b33e454946bfc1f5b19` | `scripts/ember_totality/receipts-milestone/milestone-reconciliation-20260708T034146Z.json` | `e6975d8d209ad4f67e45f3f59758eec8b0c44a8d` | removed, retained disposition in merge |
| `965863ba591c23c055041b33e454946bfc1f5b19` | `scripts/ember_totality/receipts-milestone/milestone-reconciliation-20260708T034147Z.json` | `6c2a5339cfdadf7a3897fd585376157ce6b8caf2` | removed, retained disposition in merge |
| `965863ba591c23c055041b33e454946bfc1f5b19` | `scripts/ember_totality/receipts-publication/publication-gate-20260708T034147Z.json` | `c850a070d4d985f47c3c5d7156fe0b47958241cb` | removed, retained disposition in merge |
| `d105e2e7b454839d12873c5a22a0c6e4b5cfc1d1` | `receipts/ember-m10-surface3/2026-06-28T03-17-28Z/temp-home/baseline/.avir/plugins/marketplaces/claude-plugins-official` | `30a213f9b39e3c40b0073bb5b41081da9f2b6634` | removed, retained disposition in merge |
| `d105e2e7b454839d12873c5a22a0c6e4b5cfc1d1` | `receipts/ember-m10-surface3/2026-06-28T03-17-40Z/temp-home/baseline/.avir/plugins/marketplaces/claude-plugins-official` | `30a213f9b39e3c40b0073bb5b41081da9f2b6634` | removed, retained disposition in merge |
| `d105e2e7b454839d12873c5a22a0c6e4b5cfc1d1` | `receipts/ember-m10-surface3/2026-06-28T03-21-56-952Z/home-avir/.avir/plugins/marketplaces/claude-plugins-official` | `30a213f9b39e3c40b0073bb5b41081da9f2b6634` | removed, retained disposition in merge |
| `d105e2e7b454839d12873c5a22a0c6e4b5cfc1d1` | `receipts/ember-m10-surface3/2026-06-28T05-44-30-Z/home-A2-baseline/.avir/plugins/marketplaces/claude-plugins-official` | `30a213f9b39e3c40b0073bb5b41081da9f2b6634` | removed, retained disposition in merge |
| `d105e2e7b454839d12873c5a22a0c6e4b5cfc1d1` | `receipts/ember-m10-surface3/2026-06-28T05-44-30-Z/home-A3-baseline/.avir/plugins/marketplaces/claude-plugins-official` | `30a213f9b39e3c40b0073bb5b41081da9f2b6634` | removed, retained disposition in merge |
| `d105e2e7b454839d12873c5a22a0c6e4b5cfc1d1` | `receipts/ember-m10-surface3/2026-06-28T05-48-42-Z/home-A2-baseline/.avir/plugins/marketplaces/claude-plugins-official` | `30a213f9b39e3c40b0073bb5b41081da9f2b6634` | removed, retained disposition in merge |
| `d105e2e7b454839d12873c5a22a0c6e4b5cfc1d1` | `receipts/ember-m10-surface3/2026-06-28T06-58-45Z/home-r1-baseline/.avir/plugins/marketplaces/claude-plugins-official` | `30a213f9b39e3c40b0073bb5b41081da9f2b6634` | removed, retained disposition in merge |
| `d105e2e7b454839d12873c5a22a0c6e4b5cfc1d1` | `receipts/ember-m10-surface3/2026-06-28T06-58-45Z/home-r2-baseline/.avir/plugins/marketplaces/claude-plugins-official` | `30a213f9b39e3c40b0073bb5b41081da9f2b6634` | removed, retained disposition in merge |
| `d105e2e7b454839d12873c5a22a0c6e4b5cfc1d1` | `receipts/ember-m10-surface3/2026-06-28T06-58-45Z/home-r3-baseline/.avir/plugins/marketplaces/claude-plugins-official` | `30a213f9b39e3c40b0073bb5b41081da9f2b6634` | removed, retained disposition in merge |
| `d105e2e7b454839d12873c5a22a0c6e4b5cfc1d1` | `receipts/ember-m10-surface3/2026-06-28T07-40-42Z/home-r1-baseline/.avir/plugins/marketplaces/claude-plugins-official` | `30a213f9b39e3c40b0073bb5b41081da9f2b6634` | removed, retained disposition in merge |
| `d105e2e7b454839d12873c5a22a0c6e4b5cfc1d1` | `receipts/ember-m10-surface3/2026-06-28T07-40-42Z/home-r2-baseline/.avir/plugins/marketplaces/claude-plugins-official` | `30a213f9b39e3c40b0073bb5b41081da9f2b6634` | removed, retained disposition in merge |
| `d105e2e7b454839d12873c5a22a0c6e4b5cfc1d1` | `receipts/ember-m10-surface3/2026-06-28T07-40-42Z/home-r3-baseline/.avir/plugins/marketplaces/claude-plugins-official` | `30a213f9b39e3c40b0073bb5b41081da9f2b6634` | removed, retained disposition in merge |

Intermediate path-set digests: c71ad32 `fb226dca278b5db1cec2423252f003b5c32ee91a4c5acf011093c83972a8c072` (3); db541939 `27a7192c06dd14d2dcfb030aedd77754e81a41c31a4564a666fda59b68aef083` (15); d01b59 `50a5014484170f5b2d89c874f52fa283620bd413abca7ef2cebe80a92c35aad9` (2); 5ebc9e `9f53cb3bfde3c3e7ae6240db845eb03338d5f0339e8f06085c16a89398d3420a` (12); 965863 `aa46c44d557fcad2a8bba3d27eb87493412417c7479dfc274bafe864161e45d3` (3); d105e2 `9f53cb3bfde3c3e7ae6240db845eb03338d5f0339e8f06085c16a89398d3420a` (12).
## Refreshed custody and consumer evidence

Refresh snapshot: 2026-07-18T00:12:38Z; current public master remained `c8ce2dd4022cc03533b31059c667b90365da60d5`. The three live refs still resolved to the exact SHAs in the candidate table; each protection endpoint returned HTTP 404 (`Branch not protected`); each head-specific PR query returned zero open PRs. Merge timestamps and the explicit seven-day floor are:

| PR | merged_at | age at snapshot (seconds / days) | `age >= 604800` |
|---:|---|---:|---|
| 385 | `2026-07-07T18:00:57Z` | `886301 / 10.258113` | true |
| 403 | `2026-07-08T04:27:38Z` | `848700 / 9.822917` | true |
| 409 | `2026-07-08T05:23:08Z` | `845370 / 9.784375` | true |

Full patch/path equality was recomputed from immutable objects, not inferred from titles. The canonical path-set digest is SHA-256 over sorted LF-terminated relative paths; the patch digest is SHA-256 of `git diff --binary` bytes.

| PR | path count | path-set digest (head = merge) | patch digest (head = merge) |
|---:|---:|---|---|
| 385 | 1 | `54a619840101a061ea7e1418a8a6cd07bc7d24d300363d22179223f496ba7d9b` | `4C90BCAF0089BCC2B403F7D6980B5F97B1292FF278B09A06AFC138D6CEA3486C` |
| 403 | 17 | `d30f31a2140e362a2ff12c9a1e901574177f4222348d2a6e4a92c4ec3a1ab1b7` | `02402EADD6526DF01C3738F29C588DA6947F2D978A489597958190F2AA3A6BE1` |
| 409 | 2 | `ddd2cefddfd1af21755829622681f53329fe6553e25342bb783f7f897aeabfba` | `0C3FA95F293B662C670AEE34AA52601F51444BF6607FD7D26CB08F98FFE7` |

No-consumer searches were bounded and exact. GitHub code search returned zero tracked-file matches for each branch ref, head SHA, and merge SHA. Issue search returned only the candidate issue references: branch `feat/main-tree-guard` -> #385; `fix/issue-400` -> none; `fix/custody-sidecar-401` -> #401 and #409; equivalent head-SHA searches returned #385, #403, and #401/#409 respectively. Releases matched 0, tags matched 0, and deployments matched 0 for all nine searched ref/SHA tokens. Canonical search-result digest (sorted query/result lines, LF-terminated) is `c4057e2aae59fda9eb323ba6775ed7dd287aac1fb19d158ae941f9ffbeb313aa`.

Paired fresh pre-delete receipt: `docs/vera-c1m-branch-deletion-predelete-receipt-v1.md`, byte SHA-256 `B9866D4BA1AC4B7D8E74424AFEC78760F90C57365FDEE545D89D094B74876BAF`. It is explicitly `PREDELETE_REVIEW_ONLY` with `deletion_performed: false` and carries the same live ref/age/consumer facts.

The manifest branch itself is `docs/vera-c1m-branch-deletion-manifest` at PR #929. It is retained through review and any accepted ref deletions; after the manifest is merged and the three DELETE requests each return HTTP 204, the exact branch ref is retired in a separate final recheck while this manifest remains in `master`. No retirement or deletion is executed by this PR.
## Reconstruction and deletion plan (not executed)

For each ref, the exact reconstruction is:

```text
# For each candidate ref (the immutable ref is the input; current master is never
# used as a patch base):
git fetch --no-tags origin refs/heads/<branch>:refs/remotes/origin/<branch>
git rev-parse refs/remotes/origin/<branch>       # equals recorded current ref SHA
git switch --detach <head_sha>
git rev-parse HEAD                               # equals recorded PR head SHA
git diff --name-only <base_sha> <head_sha> | sort
git diff --name-only <base_sha> <merge_sha> | sort
git diff --binary --output=head.patch <base_sha> <head_sha>
git diff --binary --output=merge.patch <base_sha> <merge_sha>
Get-FileHash -Algorithm SHA256 head.patch,merge.patch  # equal digests recorded above
# Compare sorted path output and patch hashes; equality is the acceptance check.
# The recorded path-set and patch digests are the equality proof.
```

Tested in a clean temporary worktree (current master was not used as a patch base), with the exact immutable refs:

```text
#385 ref=198a18b83e6fc19594eadfd6896d99bfb76ca570 head=198a18b83e6fc19594eadfd6896d99bfb76ca570 path_count=1 path_equal=True patch_equal=True head_patch=4C90BCAF0089BCC2B403F7D6980B5F97B1292FF278B09A06AFC138D6CEA3486C merge_patch=4C90BCAF0089BCC2B403F7D6980B5F97B1292FF278B09A06AFC138D6CEA3486C
#403 ref=d105e2e7b454839d12873c5a22a0c6e4b5cfc1d1 head=d105e2e7b454839d12873c5a22a0c6e4b5cfc1d1 path_count=17 path_equal=True patch_equal=True head_patch=02402EADD6526DF01C3738F29C588DA6947F2D978A489597958190F2AA3A6BE1 merge_patch=02402EADD6526DF01C3738F29C588DA6947F2D978A489597958190F2AA3A6BE1
#409 ref=d938e32a2e52b3edb374238b39c161f5a66839f1 head=d938e32a2e52b3edb374238b39c161f5a66839f1 path_count=2 path_equal=True patch_equal=True head_patch=0C3FA95F293B662C670AEE34AA52601F51444BF6607FD7D26CB08F98FFE7 merge_patch=0C3FA95F293B662C670AEE34AA52601F51444BF6607FD7D26CB08F98FFE7
```
The GitHub API deletion operation, only after the authorized reviewer accepts this manifest and a
fresh pre-delete recheck passes, is one request per exact ref:

```text
DELETE /repos/wordingone/ember/git/refs/heads/feat/main-tree-guard
DELETE /repos/wordingone/ember/git/refs/heads/fix/issue-400
DELETE /repos/wordingone/ember/git/refs/heads/fix/custody-sidecar-401
```

Before each request, re-check the ref SHA, branch protection, open-PR query,
merge reachability, and all `merge_blob`/`master_blob` paths. Abort on any
change, new open consumer, or API response other than HTTP 204. This PR does
not perform those DELETE requests.
