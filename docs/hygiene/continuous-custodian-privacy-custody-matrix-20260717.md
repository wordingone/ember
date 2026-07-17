# Continuous custodian privacy and custody confirmation matrix

Generated 2026-07-17 against public master `f919b116066106fc91a7d86feff39eecc70e14d0`. This is a read-only C3 confirmation; it does not authorize research-path edits, checkpoint deletion, branch deletion, GPU use, or merge.

| Surface | Privacy boundary confirmed | Custody evidence / repeatable check | Current disposition |
|---|---|---|---|
| Public repository and PR bodies | Public text contains role-neutral paths and claims; private filesystem paths and founder-role internals stay out of public artifacts. | Repository guard plus exact PR-body review at each immutable head. | CONFIRMED for the C3 increment; research PR bodies remain owner-reviewed. |
| Root authority/status documents | Root Markdown set is eight files; authority is not duplicated into generated output. | `git ls-tree -r --name-only master -- *.md` and root-file census. | BASELINE_MATCH: 8 root Markdown files. |
| Issues and closure records | Issue comments are public evidence only; no private mail or local paths are used as closure proof. | Issue view with exact body/comment SHA and linked public commit/receipt. | BATCH_ONE_REVIEW_ONLY; no issue was closed. |
| Branches and deletion | A branch is never removed from age or title alone; open-PR, ancestry, protection, and external-reference checks are required. | `git ls-remote --heads origin`, PR-head census, compare-to-master proof, retained deletion manifest. | NO_SAFE_CANDIDATE; zero remote mutations. |
| PRs and CI | Immutable head, check state, review state, and base are recorded before any hygiene action. | Safe GitHub PR view/check/run queries. | #919 remains C2 HOLD after the reported destructive-path P0. |
| Checkpoints and quarantine | Raw checkpoint bytes remain outside the public repository; quarantine/admission receipts bind content and lineage. | Public manifest/receipt hashes plus exact consumer audit; never use a prose claim as custody. | P0 escalated: failed counter path deletes the only candidate bytes. |
| Datasets and benchmarks | Public tree stores custody metadata (URL, revision, license, tree/split hash), not answer-bearing or target-training data. | Benchmark custody manifests and source/answer exclusion checks. | READ-ONLY CONFIRMATION; no downloads or materialization. |
| Receipts and generated output | Receipts are content-addressed and reconstructable; local absolute paths and generated scratch are excluded. | Receipt schema/hash checks and `.gitignore`/repo-guard scans. | CONFIRMED for C3; no receipt mutation. |
| Private/local worktrees and scratch | Local worktrees may contain private implementation state but are not public evidence; no unmerged finished work is silently treated as landed. | Worktree/branch census and public head comparison. | INVENTORIED; no deletion or publication without owner approval. |
| Resource and GPU custody | Custodian scans do not claim or occupy training GPU time; high-write actions require disk-budget receipts. | Process/GPU check and disk-budget runner policy. | ZERO GPU; no high-write benchmark action. |

## Explicit C2 finding carried forward

At exact PR #919 head `574d54fd114ff36ed1c923258cd47983e84fcb56`, `tools/ember-restart-3b/run_vertical_slice.py` still routes counter/judge failure through `_quarantine_counter_failed_checkpoint()` and `shutil.rmtree(checkpoint_target)`. That is a destructive research-path P0 and is escalated to the research owner; this C3 branch does not modify it.

## C3 scope guard

The C3 hygiene increment is limited to custody evidence and repository hygiene. It does not alter training, model, optimizer, kernel, checkpoint writer, evaluator runtime, or admission logic.
