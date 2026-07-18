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

## Reconstruction and deletion plan (not executed)

For each ref, the exact reconstruction is:

```text
git fetch --no-tags https://github.com/wordingone/ember.git master
git switch --detach c8ce2dd4022cc03533b31059c667b90365da60d5
git show <merge_commit> --stat
git diff --stat <base_sha> <head_sha>
git diff --binary <base_sha> <head_sha> > candidate.patch
git apply --check candidate.patch
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
