# Ember system overview

<a id="ember.claim.domains"></a>
Ember creates, evaluates, operates, and governs owned local foundation intelligence. The adopted
architecture assigns every current path and public interface to one of eight domains. A target
interface describes the destination boundary; it is not evidence that the implementation or an
admitted model already exists.

## Domains

- Model owns model configuration, parameter structure, and tokenizer authority.
- Data owns corpus identity, provenance, partitioning, and admission into training or evaluation.
- Training owns optimization, growth, checkpoint production, and training-state continuity.
- Evaluation owns protected task definitions, scoring, and release-quality evidence.
- Runtime owns serving and durable execution behavior.
- Lab integrates cross-domain experiments through declared interfaces without replacing domain
  authority.
- Infrastructure owns packages, tools, workflows, hosts, and external state boundaries.
- Governance owns authority, receipts, lifecycle gates, manifests, and documentation truth.

Infrastructure and Governance are cross-cutting. Dependencies are directional and constrained by
[`manifests/architecture/domain-authority-v1.json`](../../manifests/architecture/domain-authority-v1.json).
Each [domain overview](../domains/governance/DOCS-README.md#technical-domains) names its dependencies, implemented or
designed state, smallest safe verification route, and canonical evidence.

## Package and state boundaries

<a id="ember.claim.package-authorities"></a>
Python package authority is [`pyproject.toml`](../../pyproject.toml), Rust runtime authority is
[`runtime/ember-lab/Cargo.toml`](../../runtime/ember-lab/Cargo.toml), and ember-cli authority is
[`src/ember/infrastructure/tools/ember-cli/src/package.json`](../../src/ember/infrastructure/tools/ember-cli/src/package.json). Application state,
data, checkpoints, caches, evidence, and worktrees are explicit typed roots rather than hidden
source-tree assumptions.

## Maturity

The architecture map is adopted. Some public interfaces remain target-declared or dependency-
deferred. An architectural destination, source implementation, executed receipt, independently
reproduced result, and admitted model are separate states. Exact mutable state belongs in
[continuity](../domains/governance/authority/CONTINUITY.md), not in this overview.
