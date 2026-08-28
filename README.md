<!-- EMBER_CONSERVATION_V1
minimum_new_network_parameters=3000000000
destination_total_parameters=>27000000000
required_native_capabilities=text,image,audio,reasoning,structured_tool_use
borrowed_lineage=frozen_reference_only
mechanism_erasure=forbidden
-->

# Ember

Ember is a clean-genesis sovereign foundation intelligence, a local
foundation-model creation primitive, a continuously improving organism, its
ember-cli body, and a general local AI laboratory. The target is an owned
30-35B sparse unified text-image-audio decoder with native reasoning and
structured tool use, created and operated on one 24 GiB GPU.

For a fresh context, start with [docs/guides/START-HERE.md](docs/guides/START-HERE.md).

## Install the measured Python environment

Python dependency authority: manifests/python-environment-v1.json

From the repository root, install the exact direct Python environment measured
for Ember:

    python tools/ember-restart-3b/python_environment.py install

The manifest records CPython, CUDA-wheel index, exact direct-package versions,
the pinned Transformers source commit, import-to-distribution mappings, and
guarded optional integrations. The default install excludes the exact ARC-AGI
feature pins because their upstream wheel declares Python 3.12 or newer while
the measured Ember interpreter is Python 3.10. Validate the repository contract
and the current interpreter without installing anything:

    python tools/ember-restart-3b/python_environment.py verify --check-installed

Rust remains authoritative in
[`runtime/ember-lab/Cargo.toml`](runtime/ember-lab/Cargo.toml), and the
ember-cli TypeScript package remains authoritative in
[`tools/ember-cli/src/package.json`](tools/ember-cli/src/package.json). This
measured contract is not yet a claim that a fresh clean environment was
independently installed.

## Current truth

Mutable board, checkpoint, and receipt-date status is generated only in
[docs/authority/CONTINUITY.md](docs/authority/CONTINUITY.md), where it remains
bound to its source receipts and manifests.

Planted-red probe: docs/authority/PLANTED-FRONT-DOOR-RED.md.

## Roadmap status

The twelve-milestone decomposition and its public contracts live in
[docs/roadmap/README.md](docs/roadmap/README.md). Milestone completion is
claimed only through a public certificate record under
[docs/roadmap/certificates/](docs/roadmap/certificates/); issue counts and
progress bars are never completion evidence.

- **EMBER-01 — custody, identity, and experiment spine: CERTIFIED 2026-08-05.**
  Nine of nine certificate legs resolved-true, zero unresolved failures, bound
  to public commit `323be9da58a7527f3526d4a9a839ae2b5765bfd1`. Record:
  [docs/roadmap/certificates/EMBER-01.md](docs/roadmap/certificates/EMBER-01.md).
  The certificate credits no model, no training, and no capability to EMBER-01.
- **EMBER-02 — three-billion-parameter foundation birth** is the active goal
  (`docs/authority/GOAL.md`; execution boundary in
  [docs/authority/CONTINUITY.md](docs/authority/CONTINUITY.md)). It is not
  complete; no current checkpoint is an admissible Ember model.

## Non-negotiable model floor

The first model and every 3B, 7B, 15B, and >27B rung are sufficiently trained
native text-image-audio models with reasoning and structured tool use. The
headline hypothesis is Verified Expert Accretion. Borrowed learned or evaluative
signals never enter the lineage. Negative evidence preserves research families
and later synergy tests.

## Verify the authority tree

Run:

    python scripts/verify_authority_conservation.py --root .
    python -m pytest -q scripts/tests/test_authority_conservation.py

A local landing or dispatch check also supplies the operator-owned durable goal
selection.

## Read next

- docs/authority/INVARIANT.md - unamendable identity
- docs/authority/GOAL.md - complete project and machine contract
- docs/roadmap/README.md - public milestone decomposition and completion certificates
- docs/authority/STATE.md - compatibility pointer only; exact artifact identities and maturity live in docs/authority/CONTINUITY.md
- docs/contracts/goal-clear-protocol.md - proof required for completion
- docs/authority/ember-authority-matrix.md - D-001 through D-062 conservation matrix
- docs/contracts/ember-completeness.md - preserved legacy M/C manifest and diagnostic tally input
- docs/authority/CONTINUITY.md - exact current artifact identities, maturity, execution boundary, and resume order
- docs/authority/GOVERNANCE.md - authority, provenance, and landing rules

Deliberate scoped-canary reference for issue 1952 red1: `docs/authority/ISSUE1952-RED1-DEAD-REF.md` must be reported unresolved.
