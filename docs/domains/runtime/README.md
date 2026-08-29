# Runtime domain

Runtime owns serving, durable process behavior, and the target `ember.runtime` interface. It does
not own model construction, training, evaluation policy, host tooling, or authority acceptance.

The interface is target-declared. The Rust Ember Lab runtime is implemented under
[`runtime/ember-lab/`](../../../runtime/ember-lab/), but a service build or launch does not prove
model capability. Runtime may depend on Model, Training, Infrastructure, and Governance.

Smallest safe inspection: open
[`runtime/ember-lab/Cargo.toml`](../../../runtime/ember-lab/Cargo.toml) and inspect the package
authority without starting a service.
