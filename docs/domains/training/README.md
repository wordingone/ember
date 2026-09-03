# Training domain

Training owns optimization, growth, training-state continuity, and checkpoint production. It does
not own data admission, model authority, evaluation verdicts, serving, or governance acceptance.

The target `ember.training` interface is declared. Training implementations and contracts exist,
but execution and model admission remain receipt-bound. Training may depend on Model, Data,
Infrastructure, and Governance.

Smallest safe inspection: read the governed training contracts under
[`docs/domains/governance/ember-restart/`](../governance/ember-restart/) without launching a job. CPU-only authority checks are
listed in the [verification guide](../../guides/VERIFY.md).
