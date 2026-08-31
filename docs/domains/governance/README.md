# Governance domain

Governance owns authority, receipts, lifecycle gates, manifests, documentation truth, and the
target `ember.governance` interface. It does not perform model learning, corpus admission,
evaluation scoring, or runtime serving.

Governance is cross-cutting and may depend on Infrastructure. Its documents and verifiers preserve
distinctions among target, implemented, executed, measured, independently reproduced, and admitted.
They cannot create technical evidence by declaration.

Smallest safe verification: run the CPU-only authority command in the
[verification guide](../../guides/VERIFY.md). Canonical mutable state is
[`docs/authority/CONTINUITY.md`](../../authority/CONTINUITY.md), and unamendable identity is
[`docs/domains/governance/authority/INVARIANT.md`](../../authority/INVARIANT.md).
