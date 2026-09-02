# Evaluation domain

Evaluation owns protected task definitions, scoring, contamination boundaries, measurement
receipts, and release-quality evidence. It does not own training data, checkpoint production,
runtime serving, or authority adjudication.

The target `ember.evaluation` interface is dependency-deferred until the protected evaluation API
is terminal and independently reviewed. Existing evaluation scripts remain implementation, not a
claim that the full protected plane is released. Evaluation may depend on Model, Data, Runtime,
Infrastructure, and Governance.

Smallest safe inspection: read the frozen evaluation specifications under
[the frozen evaluation specifications](../governance/spec/) and do not execute protected workloads. The exact deferral is in the
[architecture manifest](../../../manifests/architecture/domain-authority-v1.json).
