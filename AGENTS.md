# Ember — Agent Entry Map

> One-read orientation for agentic collaborators. If you read nothing else, read
> **START HERE** and **Hard Rules** below.

## What Ember Is

Ember is a **local self-improving research substrate** that runs, trains, and learns on a
single consumer GPU. It improves by *verified experience only*: it acts in worlds it can
inspect, verifies its outputs against ground truth the world itself provides, and burns only
verified episodes into its weights. Every claimed gain must survive held-out evaluation, beat a
matched control, and disappear when its artifact is deleted.

The endgame is **ember trains ember** — a model that accumulates verifiable improvement across
sessions and could run without external help if all supporting infrastructure were removed. It
owns every layer of its stack: pretraining from scratch (quantization-native, multimodal),
parameter growth (function-preserving), portability, and a learning loop that verifies before it
commits.

**One integrated system:**
- `scripts/` + the pretraining/ledger/eval pipeline — the research harness where the model is built
  and improved under the resource governor, with receipts as the only evidence. Agentic
  collaborators observe it *programmatically* (receipts, STATE, job/governor state).
- `tools/ember-cli/` — the turnkey local-model agentic coding CLI **AND the maintainer's primary
  observability + control surface over the harness.** The maintainer does NOT have programmatic live
  observability the way agentic collaborators do — ember-cli is the one window in. It renders the
  harness's live state and is the inference front-end whose verified traces feed training.

These are not separable. The CLI renders the harness's live state (training progress, receipts,
job + governor/VRAM state, the POSITION block, the problem ledger) into a legible interface, *and*
its verified traces feed the harness that improves the model the CLI runs. No competitor closes — or
even exposes — that loop; every other agentic CLI is an inference-only client with no harness to
observe.

---

## START HERE — three entry points

### 1. The canonical goal — `GOAL.md`
Authoritative (37KB). Read §0 CONTROL + §1 AUTHORITY first for the operating constraints:
**receipts-only truth**, the **no-idle rule**, **break-the-wall (solve, don't escalate)**, and §4's
verifiable completion checkpoints (completion ⟺ every check passes AND the closing receipt exists).
`GOAL-paste.md` / `GOAL-prompt-4k.md` are compact summaries for small-context use;
`GOAL-archive-mm-20260617.md` is history.

### 2. Current state & blocker — `STATE.md`
Chronological, newest first (large). Read only the top **POSITION** block (~2–3KB): the current
blocking task, progress across parallel tracks, and the live problem-ledger pointer. Everything
below POSITION is the dated audit trail.

### 3. The integrated surface
- `scripts/` — the research harness: MVP cycle spine, readiness gate, benchmark runners, governor
  binding, receipt generation/validation, state substrate. Observed programmatically by agentic
  collaborators.
- `tools/ember-cli/` — the agentic coding CLI **and the maintainer's observability/control cockpit
  over the harness**. Specs, design language, and the build ledger live under
  `tools/ember-cli/state/`. This is how the maintainer monitors ember.

### 4. Building & running

**ember-cli (the coding CLI + cockpit):** built with [Bun](https://bun.sh/) (≥1.0).
Source at `tools/ember-cli/src/`.

```sh
cd tools/ember-cli/src
bun install        # install dependencies (first time)
bun run dev        # run from TypeScript source
bun run build      # compile → ember.exe
```

`./ember.exe` starts an interactive session. It auto-discovers a local
llama-compatible inference server at `http://localhost:8080` by default;
override with `EMBER_MODEL_URL=http://host:port`.

**Research harness (`scripts/`):** Python 3 with PyTorch + CUDA.

Key entry commands for agentic collaborators:

| command | what it does |
|---|---|
| `python scripts/sp3_terminal_audit.py --run` | current position — every condition RECEIPTED or GAP-NAMED |
| `python scripts/receipt_check.py` | validate all receipts against the floor schema |
| `python scripts/ember_mvp_readiness.py` | MVP readiness gate check |
| `python scripts/ember_mvp_cycle.py` | closed-cycle spine (end-to-end loop) |

Agentic collaborators do not need to run ember-cli to contribute to the
harness — they observe it via receipts, `STATE.md` POSITION, and the audit
script above.

---

## Repo map (root directories)

| Directory | Purpose | Type |
|---|---|---|
| `scripts/` | Research harness: cycle spine, readiness gate, governor binding, receipt + state tooling | Source |
| `tools/` | `ember-cli/` (the coding CLI + the maintainer's observability cockpit over the harness) + Python wrappers | Source |
| `receipts/` | ONE JSON per executed job — sole admissible evidence; checked by `scripts/receipt_check.py` | Generated |
| `docs/` | Specs, contracts, preregistrations, decision records (~68 files) | Specs |
| `configs/` | Live frozen v0 pretraining config + validator contract | Config (live) |
| `config/` | Alternate config set; `configs/` is the live one — verify before use | Config |
| `corpus-manifests/` | Per-source manifests of the license-clean v0 corpus (bytes live out-of-tree) | Manifests |
| `tokenizer/` | Frozen 32k tokenizer, byte-pinned, reserved band IDs 0–7 | Frozen artifact |
| `probes/` | Canonical frozen probe sets (seed-pinned) | Reference data |
| `ledger/` | Verified-episode ledger + matched-control pool for training | Data |
| `data/` | Training/eval datasets for experiments | Training data |
| `models/` | Checkpoints and outputs from training runs | Generated |
| `runs/` | Experiment run logs and intermediate outputs | Generated |
| `kaggle-datasets/` | External benchmark datasets | Reference data |
| `mle-bench-data/`, `mle-bench-raw-inbox/`, `mle-bench-submissions/` | MLE-bench benchmark pipeline | Benchmark data |
| `density-ab-manifests/` | A/B manifests for density experiments | Reference data |
| `research/` | Internal working notes, surveys (working context, NOT claims) | Working docs |
| `resources/` | Supporting resources | Reference data |
| `state/` | Session state tracking (event receipts, gate notes) | Generated |
| `origin/` | Empty (unused) | Empty |
| `.claude/` | Agent project context | System |

---

## Docs discipline — consolidate, don't enumerate

- **Fold into the canonical owning file; supersede in place.** A new insight, decision, or status
  update edits the one authoritative doc (GOAL.md, the STATE.md POSITION block, the relevant spec).
  Superseded content is replaced, or moved to a dated archive — not left as a new sibling file.
- **A new top-level file or directory must justify itself.** Prefer a new *section* in an existing
  doc, or a *row* in an index, over a new file. A warranted new file is indexed the same turn (no
  orphans).
- **One of each canonical thing:** one authoritative GOAL (compact variants are *generated*, not
  hand-maintained duplicates); one live STATE (POSITION) plus a dated archive; one config directory;
  every `docs/` file listed in `docs/index.md`.
- **A periodic consolidation pass keeps the tree legible.** The maintainer's high-velocity insights
  are an asset; consolidation is the system's job.

This binds agentic collaborators (including doc-writing agents) and the maintainer alike.

---

## Hard Rules (enforced in code and review)

**Evidence & receipts**
- **Receipts-only truth.** Every claim traces to a JSON receipt in `receipts/`. Prose, readiness
  files, and summaries are working context, never evidence.
- **Self-attestation is flagged.** `scripts/receipt_semantic_check.py` re-derives verdicts from the
  numbers; a receipt asserting `pass=true` without measurement does not count.

**Resource governor**
- Never 100% VRAM, never GPU wall-to-wall. Every job passes a hard VRAM-fraction cap, a free-memory
  margin assertion, and a decode pacer. A headroom violation is fatal-exit — **kill and relaunch
  governed; fix-forward in place is banned.**
- No >1h / heavy run without a measured efficiency (lever) receipt.

**Artifacts & boundaries**
- **No person names** in any git-tracked or public artifact (files, commits, PRs, issues). Use roles
  ("the maintainer", "agentic collaborators"). Per user direction.
- **ISO dates only** (e.g. 2026-06-27); never three-letter month abbreviations in tracked names/logs.
- **Nothing leaves this PC** without explicit prior approval (escalation set: money, paid cloud, new
  hardware, >100GB disk, anything off-machine). Fetching public artifacts is fine.

**Public/private baseline shipping**
- `/baseline` work is delivered only when the public repo and private backup repo both expose the
  same reviewed `/baseline` state on their default `master` branches, or when a human explicitly
  records a different final branch in a tracked receipt. A staging branch push is progress only.
- Every baseline staging branch must be short-lived, named for the scoped baseline increment, and
  backed by organized commits plus a PR or merge receipt. Branch existence, local commits,
  in-session promises, private-only proof, or unmerged PRs cannot satisfy completion.
- A baseline PR is mergeable only after the strict baseline verifier, publication-surface verifier,
  line-ending check, public/private remote proof, and current family receipts agree. If any verifier
  says STAGING, FAIL, NOT COMPLETION, or missing operator acceptance, the branch may be pushed for
  review but must not be represented as final delivery.
- Updating `master` is a completion-path action, not a hiding place: merge only the reviewed
  baseline subtree and its verifier receipts, preserve negative evidence, and keep unrelated dirty
  work out of the commit.

**Capability gates**
- **Deletion gate:** a gained capability must vanish when its artifact is deleted (no hidden
  cross-run state outside the ledger).
- **Persistence gate:** a gained capability must survive process/session restart, measured at
  re-launch.

**Walls**
- **Break the wall, don't escalate.** Upstream blocker → fork/patch/build; unsupported → implement;
  missing format → produce it. A `BLOCKED` verdict names the exact missing surface + the next
  executable command, then moves on. Escalation is reserved for the escalation set above.

---

## Docs index (topic clusters)

`docs/` holds ~68 files; see `docs/index.md` for the running map. Principal clusters:

- **Core specs:** `formalization-v0.md`, `ledger-schema-v3.md`, `nck-spec-v0.md`, `nck-invariant-contract-v0.md`
- **Training pipeline & gates:** `ember-mvp-v0.md`, `ember-mvp-cycle-spine-status.md`, `pretrain-launch-authorization-brief-multimodal.md`, `v0-multimodal-floor-probe-prereg.md`
- **Preregistrations (frozen before runs):** `fp33-surpass-prereg-v1.md`, `dt3-scale-probe-prereg.md`, `dt6-loop-economics-gate-amendment.md`
- **Design decisions (owned substrate):** `c04-pick-decision-table-v1.md`, `kernel-v1-freeze-spec.md`, `ember-owned-substrate-diagnostic.md`
- **Technique registry:** `technique-registry.jsonl`, `nc2-own-technique-contract.md`
- **Problem ledger:** `docs/PROBLEMS.md` (generated from `problems-meta.yaml` — edit the source, not the output)
- **The cockpit (coding CLI + harness observability):** `tools/ember-cli/state/specs/` (M9 parity floor, M10 surpass track, field-UX research, fireball cognitive-mode, harness observability)
