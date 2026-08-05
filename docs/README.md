# docs/ — the map

This is the single entry point into `docs/`. If you are new to this repository, read in this
order:

1. **This file** — orients you to the directory structure below.
2. **[`START-HERE.md`](START-HERE.md)** — the actual onboarding document: what this repo is,
   the evidence model (receipts, not prose), D-gate/P-gate, and how to run the reproducible
   checks with no GPU and no model weights.
3. **[`spec/`](spec/)** — the frozen specifications currently in force.
4. **[`anatomy/`](anatomy/)** — the system anatomy set: what each subsystem is and how the
   pieces fit together.

From there, [`PROBLEMS.md`](PROBLEMS.md) (with `problems-meta.yaml`) is the live problem
registry, and the sections below tell you where everything else lives.

`docs/` root itself holds only three things: this map, `START-HERE.md`, and the problem
registry. Everything else is filed under one of the directories below by what kind of thing
it is, not by when it was written.

## Current, binding material

These directories describe what is true and in force today. If a document here conflicts
with something in `archive/`, this wins.

- **[`spec/`](spec/)** — frozen specifications: preregistrations, protocol definitions,
  eval-suite freezes, growth-chain and scale specs. Start with
  [`spec/conditions-v1.md`](spec/conditions-v1.md),
  [`spec/credibility-battery-v1.md`](spec/credibility-battery-v1.md),
  [`spec/eval-suite-freeze-v1.md`](spec/eval-suite-freeze-v1.md), and
  [`spec/ember02-preregistration-v1.md`](spec/ember02-preregistration-v1.md).
- **[`anatomy/`](anatomy/)** — the numbered system-anatomy set (`00_INDEX.md` through
  `15_TECHNICAL_REPORT.md`): constitution and authority, repo topology, model architecture,
  training pipeline, evaluation, the governor, tooling, receipts, the runbook. Start with
  [`anatomy/00_INDEX.md`](anatomy/00_INDEX.md) and
  [`anatomy/01_CONSTITUTION_AND_AUTHORITY.md`](anatomy/01_CONSTITUTION_AND_AUTHORITY.md).
- **[`charter/`](charter/)** — standing contracts and protocols that govern *how* work is
  done here: reproducibility requirements, the floor contract, technique-ownership
  contracts, doc-freshness protocol, the goal-clear and goal-mode mechanisms, the GitHub
  work system. Start with [`charter/REPRODUCIBILITY.md`](charter/REPRODUCIBILITY.md),
  [`charter/ember-floor-contract.md`](charter/ember-floor-contract.md), and
  [`charter/nc2-own-technique-contract.md`](charter/nc2-own-technique-contract.md).
- **[`ledgers/`](ledgers/)** — living, append-only registries: the completeness ledger, the
  debt ledger, the authority matrix, deviations, work-ahead. These are read fresh every
  time, never archived while active. Start with
  [`ledgers/ember-completeness.md`](ledgers/ember-completeness.md),
  [`ledgers/ember-debt-ledger.md`](ledgers/ember-debt-ledger.md), and
  [`ledgers/ember-authority-matrix.md`](ledgers/ember-authority-matrix.md).
- **[`design/`](design/)** — architecture and design decisions on the current line: the
  actual stack, the SOTA-stack floor, inference-to-training translation, the C-FED
  federation design. Start with [`design/the-actual-stack.md`](design/the-actual-stack.md)
  and [`design/sota-stack-floor.md`](design/sota-stack-floor.md).
- **[`ember-restart/`](ember-restart/)** — the 3B restart line: protocols, conventions, the
  governed runner, multimodal config, the integration contract. Start with
  [`ember-restart/integration-contract-v1.md`](ember-restart/integration-contract-v1.md) and
  [`ember-restart/ember-restart-3b-governed-runner-v1.md`](ember-restart/ember-restart-3b-governed-runner-v1.md).
- **[`custody/`](custody/)** — custody dispositions, branch manifests, deletion receipts,
  and the HF-custody sync note: what happened to which branch, checkpoint, or dataset, and
  under what authority. Start with
  [`custody/custody-disposition-20260708.md`](custody/custody-disposition-20260708.md) and
  [`custody/branch-inventory.md`](custody/branch-inventory.md).

## Reference material (current, but not normative)

- **[`research/`](research/)** — research notes, prereg drafts, external-stack surveys, and
  first-principles audits. Not binding on their own; a research note becomes binding only
  once a `spec/` or `charter/` document cites it. Start with
  [`research/README.md`](research/README.md) and
  [`research/first-principles-audit-2026-06-10.md`](research/first-principles-audit-2026-06-10.md).
- **[`verification/`](verification/)** — verification artifacts and acceptance runs (CLI
  deploy acceptance, live-board checks, TUI resize/bisect receipts). Start with
  [`verification/ember-cli-deploy-250-acceptance-20260706.md`](verification/ember-cli-deploy-250-acceptance-20260706.md).
- **[`audit/`](audit/)** — point-in-time authority and mandate audits. Start with
  [`audit/issue-35-authority-supersession-crosswalk.md`](audit/issue-35-authority-supersession-crosswalk.md).
- **[`roadmap/`](roadmap/)** — the milestone roadmap, EMBER-00 through EMBER-11. Start with
  [`roadmap/README.md`](roadmap/README.md).
- **[`operator/`](operator/)** — operator-facing reference: commands and how to operate the
  system day to day. Start with [`operator/README.md`](operator/README.md).
- **[`hygiene/`](hygiene/)** — repo-hygiene manifests and audits (deletion manifests,
  custody matrices, branch-deletion proposals). Start with
  [`hygiene/deletion-manifest-20260708.md`](hygiene/deletion-manifest-20260708.md).
- **[`superpowers/`](superpowers/)** — feature work plans and their paired design specs
  (`plans/` + `specs/`, dated). Start with
  [`superpowers/plans/2026-07-27-ember-roadmap-publication.md`](superpowers/plans/2026-07-27-ember-roadmap-publication.md)
  and its paired
  [`superpowers/specs/2026-07-27-ember-roadmap-publication-design.md`](superpowers/specs/2026-07-27-ember-roadmap-publication-design.md).

## Archive — superseded record, binds nothing

**[`archive/`](archive/) is deliberately retained history, not current guidance.** Nothing
in it governs today's work; it exists because the lab keeps its own record rather than
deleting the trail. If you are deciding what to do next, do not cite `archive/` — cite
`spec/`, `charter/`, or `ledgers/` instead.

- **[`archive/pre-restart/`](archive/pre-restart/)** — the superseded pre-restart era: the
  C04/C52/FP3x/SP5/SP6/NCK/DT/WMC/arcade lines and the old `index.md` this file replaces.
  57 files, kept as record of what was tried before the 3B restart line in
  `ember-restart/` superseded it.
- **[`archive/goal/`](archive/goal/)** — superseded goal archives: prior full goal-archive
  snapshots and coverage matrices, retained for provenance. For the live goal, read the
  root [`../GOAL.md`](../GOAL.md), not anything under here.

## Two documents that are byte-identical on purpose

`20260617-maximally-viable-product.md` and `archive/pre-restart/ember-mvp-v0.md` (after the
2026-06-17 doc moved into archive alongside it) are the same content under two historically
load-bearing filenames — several scripts probe for both. `20260617-maximally-viable-product.md`
is now a two-line pointer to `ember-mvp-v0.md`; both paths keep resolving.
