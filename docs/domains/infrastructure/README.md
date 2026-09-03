# Infrastructure domain

Infrastructure owns packages, source layout, tools, workflows, hosts, and external typed-root
boundaries. It does not own domain semantics, evidence interpretation, or model admission.

The target `ember.infrastructure` interface is declared. Infrastructure is cross-cutting and is a
permitted dependency of the other domains where the architecture manifest says so. Package files
describe build authority; they do not establish runtime or model results.

Smallest safe verification: inspect [`pyproject.toml`](../../../pyproject.toml),
[`runtime/ember-lab/Cargo.toml`](../../../runtime/ember-lab/Cargo.toml), and
[`src/ember/infrastructure/tools/ember-cli/src/package.json`](../../../src/ember/infrastructure/tools/ember-cli/src/package.json), then run the
CPU-only authority command in the [verification guide](../../guides/VERIFY.md).
