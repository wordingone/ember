# Start here

This route is for a technically capable reader with no project history. Ember is a complete local
foundation-intelligence project, not only a model, trainer, service, or command-line interface. Read
the [system overview](../../../architecture/system-overview.md) before interpreting a subsystem as the
whole project.

Its operating constraint is one consumer GPU.

## First-reader facts

- Ember is the complete clean-genesis sovereign foundation-intelligence project: the local
  foundation-model creation primitive, continuously improving organism, `ember-cli` operator body,
  and general local AI laboratory.
- It addresses creating and operating owned local foundation intelligence on one consumer GPU.
  Claims require verified public experience and receipts; borrowed learned or evaluative signals
  are excluded from the target lineage.
- `EMBER-01` is certified but grants no model-training or capability credit. `EMBER-02` is active,
  and no current checkpoint is an admitted Ember model. The target is an approximately 30–35B
  sparse unified text-image-audio decoder with native reasoning and structured-tool use.
- The domains are Model, Data, Training, Evaluation, Runtime, Lab, Infrastructure, and Governance.
  Lab integrates experiments across declared interfaces and does not replace domain authority.
- Inspection starts at the root `README.md` and this canonical start page. On Windows, `tools/launchers/Ember.cmd`
  is the operator entry. Python uses `manifests/python-environment-v1.json`; Rust uses
  `runtime/ember-lab/Cargo.toml`; `ember-cli` uses `src/ember/infrastructure/tools/ember-cli/src/package.json`.
- The smallest safe executable check is CPU-only authority verification from the repository root:
  `python src/ember/governance/scripts/verify_authority_conservation.py --root .`. Success reports authority
  conservation; it requires no credentials, weights, or GPU and grants no model capability.
- Exact mutable current truth lives only in
  [`docs/domains/governance/authority/CONTINUITY.md`](../authority/CONTINUITY.md); entry documentation links rather
  than copying it. Public roadmap certificates, not prose or progress bars, carry completion.
- Contribution and independent reproduction start at
  [`docs/contributing.md`](../../../contributing.md) and the public
  [reproducibility charter](../charter/REPRODUCIBILITY.md): bind an exact public source, replay
  documented commands, and verify source identities and receipts without hidden or local evidence.

## Inspect the repository

Begin at the root README, then use the [documentation map](../DOCS-README.md). The canonical mutable
execution position is [continuity](../authority/CONTINUITY.md); the README deliberately does not
copy its changing identities. The [roadmap](../roadmap/README.md) distinguishes target contracts
from certified completion.

## Install the measured Python environment

To inspect Ember, start at the repository-root `README.md` and continue through this canonical
`docs/domains/governance/guides/START-HERE.md` page. On Windows, `tools/launchers/Ember.cmd` is the operator entry.

Installation authorities are distinct: Python uses
[`manifests/python-environment-v1.json`](../../../../manifests/python-environment-v1.json), Rust uses
[`runtime/ember-lab/Cargo.toml`](../../../../runtime/ember-lab/Cargo.toml), and `ember-cli` uses
[`src/ember/infrastructure/tools/ember-cli/src/package.json`](../../../../src/ember/infrastructure/tools/ember-cli/src/package.json).

From the repository root:

```text
python src/ember/infrastructure/tools/ember-restart-3b/python_environment.py install --receipt state\receipts\python-environment-install-v1.json
```

The measured environment contract is
[`manifests/python-environment-v1.json`](../../../../manifests/python-environment-v1.json). Installation
uses CPU and network access, requires no model weights or GPU, and does not establish model capability.
Launching the operator body is different from training, evaluation, or proof of an admitted model.

## Verify before interpreting claims

Run the CPU-only authority verifier from the repository root:

```text
python src/ember/governance/scripts/verify_authority_conservation.py --root .
```

Then read the [verification guide](../../../guides/VERIFY.md) for expected output, receipt selftest, documentation
validation, exact requirements, and claim boundaries.

## Choose the next route

- Understand the eight domains and Lab: [system overview](../../../architecture/system-overview.md)
- Reproduce public evidence: [verification guide](../../../guides/VERIFY.md)
- Contribute: [contribution guide](../../../contributing.md)
- Operate current surfaces: [operator route](../operator/README.md)
- Audit authority and mutable state: [continuity](../authority/CONTINUITY.md)
- Define project vocabulary: [glossary](../../../GLOSSARY.md)
