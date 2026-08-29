# Start here

This route is for a technically capable reader with no project history. Ember is a complete local
foundation-intelligence project, not only a model, trainer, service, or command-line interface. Read
the [system overview](../architecture/system-overview.md) before interpreting a subsystem as the
whole project.

## Inspect the repository

Begin at the root README, then use the [documentation map](../DOCS-README.md). The canonical mutable
execution position is [continuity](../authority/CONTINUITY.md); the README deliberately does not
copy its changing identities. The [roadmap](../roadmap/README.md) distinguishes target contracts
from certified completion.

## Install the measured Python environment

From the repository root:

```text
python tools/ember-restart-3b/python_environment.py install --receipt state\receipts\python-environment-install-v1.json
```

The measured environment contract is
[`manifests/python-environment-v1.json`](../../manifests/python-environment-v1.json). Installation
uses CPU and network access, requires no model weights or GPU, and does not establish model
capability. Rust and ember-cli use separate package authorities documented in the
[system overview](../architecture/system-overview.md).

On Windows, `Ember.cmd` is the operator entry. Launching the operator body is different from
training, evaluation, or proof of an admitted model; follow the live authority and resource gates
before any heavy execution.

## Verify before interpreting claims

Run the CPU-only authority verifier from the repository root:

```text
python scripts/verify_authority_conservation.py --root .
```

Then read the [verification guide](VERIFY.md) for expected output, receipt selftest, documentation
validation, exact requirements, and claim boundaries.

## Choose the next route

- Understand the eight domains and Lab: [system overview](../architecture/system-overview.md)
- Reproduce public evidence: [verification guide](VERIFY.md)
- Contribute: [contribution guide](../contributing.md)
- Operate current surfaces: [operator route](../operator/README.md)
- Audit authority and mutable state: [continuity](../authority/CONTINUITY.md)
- Define project vocabulary: [glossary](../GLOSSARY.md)
