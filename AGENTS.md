# ember — Repo Map

| Directory | Purpose | Type |
|-----------|---------|------|
| `.claude` | Claude Code session state; machine-local, untracked. PR-lane worktrees are **not** here: `src/ember/governance/scripts/worktree_lifecycle.py` creates them outside the repository, under the root named by `EMBER_WORKTREE_ROOT`, and refuses the C: drive without an explicit operator exception. See Worktree lifecycle below | infra |
| `.github` | GitHub Actions workflows and CI/CD configuration | infra |
| `.githooks` | Git hooks for pre-commit, commit-msg, pre-push gates | infra |
| `baseline` | Foundation baseline protocols, specifications, receipts, and control data for C1–C8 reference gates | spec |
| `cockpit-398-build` | Standalone build/staging checkout for the cockpit UI work (issue #398); machine-local, untracked | tool |
| `configs` | Training and inference configuration files (NanoCausalLM, multimodal, QAT variants) | data |
| `data` | Downloaded/generated evaluation datasets and eval-suite run fixtures consumed by training/eval scripts; machine-local, untracked | data |
| `docs` | Specifications, design documents, reproducibility instructions, and decision records | spec |
| `kaggle-datasets` | Raw Kaggle dataset downloads used for corpus/benchmark sourcing; machine-local, untracked | data |
| `manifests` | Condition manifests, registry mappings, and completeness enumeration | spec |
| `mle-bench-data`, `mle-bench-raw-inbox`, `mle-bench-submissions` | MLE-bench benchmark task data — extracted task data, raw inbound archives pending extraction, and generated submission artifacts respectively; machine-local, untracked | data |
| `models` | Trained model checkpoints and serving artifacts; machine-local, untracked (also gitignored) | data |
| `receipts` | Executed job receipts in JSON format — ground truth for all board verdicts | data |
| `receipts-local` | Local receipt drafts and redaction-pending artifacts staged before landing in `receipts/` via PR; machine-local, untracked | data |
| `runs` | Per-experiment training/eval run output (logs, checkpoints, metrics); machine-local, untracked | data |
| `runtime` | `ember-lab` Rust crate (control-plane/RPC named-pipe runtime); tracked | tool |
| `scratch` | Ephemeral working notes and one-off analysis artifacts; machine-local, untracked | tool |
| `scratchpad` | Ephemeral agent scratch workspace for in-flight investigation; machine-local, untracked | tool |
| `scripts` | Probe runners, verification checkers, and utility scripts | tool |
| `state` | State tracking, ledgers, and position records | data |
| `tests` | Test scripts and test fixtures | tool |
| `tokenizer` | Tokenizer implementations, serialized tokenizer artifacts, and configuration | tool |
| `tools` | Standalone tools, CLI utilities, and build/analysis helpers | tool |
| `TEMP` | Junk artifact directory (private-use-codepoint name; contains a nested `claude/<session-id>/...` scratch tree) left behind by a mangled temp-path write that landed inside the repo root instead of the OS temp dir; not a real working directory — flagged here for coordinator cleanup (rename/remove) | junk |

## Owned local processes

Automated commands that may create descendants (including Bun/Node tests, watchers, development servers, builds, Cargo tests, and Python harnesses) must run through `python -B src/ember/governance/scripts/owned_process.py --timeout-seconds <finite-seconds> -- <command...>`. Raw unbounded `bun test`, watch mode, or background process launch is forbidden for agent work. The owned runner must fail closed when containment cannot be established, and task completion requires that its process tree has been cleaned up. Windows uses a kill-on-close Job Object; callers must remain backend-neutral so Linux/macOS process-group containment can evolve without a second launcher authority.

## Worktree lifecycle

All Ember worktree creation and retirement must use `python src/ember/governance/scripts/worktree_lifecycle.py create` and `python src/ember/governance/scripts/worktree_lifecycle.py retire`. Raw `git worktree add` and recursive worktree deletion are forbidden. Each managed worktree requires an owner, purpose, and expiry; dirty worktrees are never retired automatically, detached heads are archived first, and the repository-local worktree ceiling may only ratchet downward toward 12.

Deleting a worktree directory without deregistering it is what strands a registry row, and a stranded row reds the custody census. So every removal path deregisters in the same operation: `retire` records its intent before touching disk, reads back Git's registration afterwards, and writes a dated, reasoned tombstone in the same state write that drops the row. `reconcile --path` does the same for a row whose directory is already gone — cleared, never silently dropped. `python src/ember/governance/scripts/worktree_lifecycle.py audit --strict` is the mechanical check, and it is what the pre-commit and pre-push hooks run. It is read-only and total: it inventories stale registrations, unscannable registrations (probing with the custody census's own commands, so a green run implies a green census), unregistered linked-worktree directories whose gitdir resolves into this repository, and interrupted removals. Findings carry a severity — `error` for records the registry owns, `backlog` for inherited debt — and the hooks fail on errors only, so a stranded row fails immediately while the pre-existing legacy backlog stays visible without blocking anyone. `audit --strict --all` fails on the backlog too; that is the mode to run while draining it.
