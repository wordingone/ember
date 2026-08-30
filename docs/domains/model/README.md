# Model domain

Model owns model configuration, parameter structure, tokenizer authority, and the target
`ember.model` interface. It does not own corpus admission, optimization runs, evaluation verdicts,
serving, or lifecycle authority.

The public interface is target-declared. Current configuration and tokenizer implementations exist,
but their presence is not an admitted model. Model may depend on Infrastructure and Governance.

Smallest safe inspection: open [`pyproject.toml`](../../../pyproject.toml) and the
[`tokenizer/`](../../../domains/model/tokenizer/) source without executing a model. Domain and package authority
is fixed by [`manifests/architecture/domain-authority-v1.json`](../../../manifests/architecture/domain-authority-v1.json).
