# Runtime domain

Runtime owns serving, durable process behavior, and the target `ember.runtime` interface. It does
not own model construction, training, evaluation policy, host tooling, or authority acceptance.

The interface is target-declared. The Rust Ember Lab runtime is implemented in a private repository and installed from the released
build on [wordingone/ember-studio](https://github.com/wordingone/ember-studio/releases), but a service build or launch does not prove
model capability. Runtime may depend on Model, Training, Infrastructure, and Governance.

Smallest safe inspection: read the release notes and checksum of the installed ember-lab build without
starting a service.
