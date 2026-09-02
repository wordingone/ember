# Ember documentation

This is the canonical map for public documentation. Choose an audience route, a task, or one of the
eight adopted technical domains. The machine-generated list of current and normative entry pages is
[`docs/INDEX.md`](../../INDEX.md).

## Audience routes

- First-time reader: [`docs/domains/governance/guides/START-HERE.md`](guides/START-HERE.md)
- User or installer: [`docs/domains/governance/guides/START-HERE.md`](guides/START-HERE.md)
- Contributor: [`docs/contributing.md`](../../contributing.md)
- Operator: [`docs/domains/governance/operator/README.md`](operator/README.md)
- Independent reproducer: [`docs/guides/VERIFY.md`](../../guides/VERIFY.md)
- Authority auditor: [`docs/domains/governance/authority/CONTINUITY.md`](authority/CONTINUITY.md)

## Task routes

- Understand the whole system: [`docs/architecture/system-overview.md`](../../architecture/system-overview.md)
- Define unfamiliar terms: [`docs/GLOSSARY.md`](../../GLOSSARY.md)
- Inspect exact mutable state: [`docs/domains/governance/authority/CONTINUITY.md`](authority/CONTINUITY.md)
- Inspect the public roadmap: [`docs/domains/governance/roadmap/README.md`](roadmap/README.md)
- Validate this information system: [`docs/guides/VERIFY.md`](../../guides/VERIFY.md)

## Technical domains

- [`docs/domains/model/README.md`](../model/README.md) — model structure and tokenizer authority
- [`docs/domains/data/README.md`](../data/README.md) — corpus identity, lineage, and admission
- [`docs/domains/training/README.md`](../training/README.md) — optimization and checkpoint production
- [`docs/domains/evaluation/README.md`](../evaluation/README.md) — protected measurement and scoring
- [`docs/domains/runtime/README.md`](../runtime/README.md) — serving and durable runtime behavior
- [`docs/domains/lab/README.md`](../lab/README.md) — cross-domain experiments and integration
- [`docs/domains/infrastructure/README.md`](../infrastructure/README.md) — packaging, tooling, and CI
- [`docs/domains/governance/README.md`](README.md) — authority, evidence, and lifecycle

Infrastructure and Governance are cross-cutting. Lab integrates experiments through declared
interfaces and does not absorb another domain's authority.

## Status and history

<a id="ember.claim.metadata-scope"></a>
Documents marked current or normative in the metadata sidecar are validated as entry documents.
Reference material can explain or support current work but does not govern by itself. Material under
[The historical archive](archive/) is visible historical record and never current instruction. Superseded pages
must point to a canonical replacement rather than disappear silently.
