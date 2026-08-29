# Ember documentation

This is the canonical map for public documentation. Choose an audience route, a task, or one of the
eight adopted technical domains. The machine-generated list of current and normative entry pages is
[`INDEX.md`](INDEX.md).

## Audience routes

- First-time reader: [`guides/START-HERE.md`](guides/START-HERE.md)
- User or installer: [`guides/START-HERE.md`](guides/START-HERE.md)
- Contributor: [`contributing.md`](contributing.md)
- Operator: [`operator/README.md`](operator/README.md)
- Independent reproducer: [`guides/VERIFY.md`](guides/VERIFY.md)
- Authority auditor: [`authority/CONTINUITY.md`](authority/CONTINUITY.md)

## Task routes

- Understand the whole system: [`architecture/system-overview.md`](architecture/system-overview.md)
- Define unfamiliar terms: [`GLOSSARY.md`](GLOSSARY.md)
- Inspect exact mutable state: [`authority/CONTINUITY.md`](authority/CONTINUITY.md)
- Inspect the public roadmap: [`roadmap/README.md`](roadmap/README.md)
- Validate this information system: [`guides/VERIFY.md`](guides/VERIFY.md)

## Technical domains

- [`domains/model/README.md`](domains/model/README.md) — model structure and tokenizer authority
- [`domains/data/README.md`](domains/data/README.md) — corpus identity, lineage, and admission
- [`domains/training/README.md`](domains/training/README.md) — optimization and checkpoint production
- [`domains/evaluation/README.md`](domains/evaluation/README.md) — protected measurement and scoring
- [`domains/runtime/README.md`](domains/runtime/README.md) — serving and durable runtime behavior
- [`domains/lab/README.md`](domains/lab/README.md) — cross-domain experiments and integration
- [`domains/infrastructure/README.md`](domains/infrastructure/README.md) — packaging, tooling, and CI
- [`domains/governance/README.md`](domains/governance/README.md) — authority, evidence, and lifecycle

Infrastructure and Governance are cross-cutting. Lab integrates experiments through declared
interfaces and does not absorb another domain's authority.

## Status and history

<a id="ember.claim.metadata-scope"></a>
Documents marked current or normative in the metadata sidecar are validated as entry documents.
Reference material can explain or support current work but does not govern by itself. Material under
[`archive/`](archive/) is visible historical record and never current instruction. Superseded pages
must point to a canonical replacement rather than disappear silently.
