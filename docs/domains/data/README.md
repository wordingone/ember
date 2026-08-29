# Data domain

Data owns corpus identity, provenance, partitions, licensing, lineage, and admission into training
or evaluation. It does not own model structure, optimization, scoring policy, or serving.

The target `ember.data` interface is dependency-deferred while the governed data-plane program is
still completing. Existing data code and manifests remain real implementation, but the deferred
interface must not be described as terminal. Data may depend on Model, Infrastructure, and
Governance.

Smallest safe inspection: read the public corpus documentation under
[`docs/corpus/`](../../corpus/) and verify provenance fields without downloading or training on
data. The exact deferral is in
[`manifests/architecture/domain-authority-v1.json`](../../../manifests/architecture/domain-authority-v1.json).
