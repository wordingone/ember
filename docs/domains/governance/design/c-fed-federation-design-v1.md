# C-FED: external-compute federation design (design-only, zero egress)

<!-- goal_id: EMBER-02 -->
<!-- workstream_id: EMBER-02A -->
<!-- next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember -->

Status: DESIGN-ONLY. Nothing described in this document has executed. Zero outbound
transfer has occurred; this is design-only, nothing has left the PC. No account has been
opened on kaggle, colab, or hf under this design; no checkpoint, shard, or receipt has been
uploaded anywhere. Per-avenue approval is required from the user before any transfer this
document describes is carried out for real.

## Why this document exists

Board row C-FED asks a narrower question than "can Ember use free/cheap external compute."
It asks whether Ember has a *named, checkable design* for moving training work across
compute substrates it does not own outright (Kaggle notebooks, Google Colab, HF Spaces/
compute) without breaking the two invariants the rest of the repo already enforces:

1. **Custody**: every artifact that leaves the machine is named, hashed, and accounted for
   (the same discipline `root-spec.json`'s material-root classification and the
   `local-ignored-payload-registry` custody scan already apply to on-machine artifacts).
2. **Receipts-only truth**: nothing is credited to Ember unless it is backed by a content-
   addressed, canonical-JSON receipt an independent reader can re-verify (the same rule that
   governs `state/ember01-completion-receipt-20260801.json` and every `receipts/**` artifact
   in this tree).

No prior document in this repo names this design. `docs/contracts/ember-completeness.md`'s C-FED row
(M-row "Federation surface (inter-founder coordination)") describes a *different* meaning of
"federation" — mailbox routing between founders on this one machine, not external-compute
substrates. This document is new content, written from the repo's real existing mechanisms,
not a restatement of that unrelated row.

## The three mechanisms

### 1. Checkpoint portability

Ember already treats a trained checkpoint as a portable, hash-verified bundle rather than a
framework-specific blob: the identity-manifest round-trip proven at
`state/receipts/cond3-legs34/bundle_v2` (cond3/cond4, `state/ember01-completion-receipt-
20260801.json`) demonstrates that a checkpoint's identity survives a save/load cycle against
an independently re-derived manifest, and that a tampered manifest is caught fail-closed.

Federated checkpoint portability reuses this exact mechanism, unchanged, across a substrate
boundary instead of a save/load boundary: a checkpoint produced on an external avenue (Kaggle/
Colab/HF compute) is only ever re-admitted to this machine's lineage if its identity manifest
round-trips against the same verifier used for legs 3/4 today
(`src/ember/governance/scripts/verify_ember01_completion.py` / the identity-manifest checker it calls). No new
trust boundary is introduced — the external avenue is treated exactly like any other producer
of an untrusted checkpoint: verify identity before crediting it.

### 2. Work-sharding

Ember already has a real, landed sharding primitive: shard corpora, defined at freeze time
and byte-scanned at launch (`TOKEN-SHARDS-V0`, `docs/contracts/ember-completeness.md` M33/M34, the
launch-rail's "shards byte-scan + live interlock"). Federated work-sharding is the same
primitive applied to *training work units* instead of *corpus bytes*: a shard is a bounded,
named unit of work (a fixed token range, a fixed cycle count, a fixed budget —
`docs/archive/pre-restart/barrier-program.md`'s "fixed shards-v0 corpus" and `ember_growth_harness.py`'s
`MIN_REPEATED_POSITIVE_CYCLES`-bounded cycle notion are the existing precedent for "bounded,
named, receipt-backed unit of work") dispatched to one avenue, executed there, and returned
as a receipt plus an optional checkpoint delta. The shard boundary is the same boundary the
launch-rail already byte-scans; federation does not invent a new unit, it dispatches an
existing one to a different execution substrate.

### 3. Receipt-merge

Every Ember artifact of record is already a content-addressed, append-only, canonical-JSON
receipt (the append-only receipts law, refs #482 — landed bytes are never edited in place;
a correction is always a new sidecar/supplemental artifact). Receipt-merge is this same
append-only law applied across substrate boundaries: a receipt produced on an external avenue
is admitted into this repo's `receipts/` tree only as a new, independently hashed artifact —
never by rewriting or replacing a receipt already on this machine. Where multiple avenues
each produce a partial receipt for the same shard, merging means each partial receipt lands
as its own artifact and a *new*, superseding receipt (following the same supersession-row
pattern the frozen-spec cure mechanism already uses for `test_c_invariant.py`) names all of
its inputs by path and sha256 and states the combined verdict. No partial receipt is ever
silently absorbed or overwritten; the merge is itself a new, independently checkable artifact.

## Avenues

| Avenue | Role in this design | Today's status |
|---|---|---|
| Kaggle | Free-tier GPU notebook execution for a bounded work-shard; output re-admitted only via checkpoint-portability (§1) | Not yet used. No account provisioned under this design. |
| Colab | Same role as Kaggle — free/cheap-tier notebook execution for a bounded shard | Not yet used. No account provisioned under this design. |
| HF (huggingface) | Artifact hosting / Spaces compute for a bounded shard, and the existing "HF upload (standing)" authorization already on file (`user_hf_checkpoint_upload_authorized_2026_07_04` — ember weights only) is the only avenue with any standing authorization at all, and only for outbound weight upload, not inbound work dispatch | Not yet used for work-sharding. Existing standing authorization covers weight upload only, not this design's dispatch/return flow. |

## Egress manifest

Per-avenue approval is required before any transfer this design describes is carried out.
The egress manifest is the artifact that makes that approval checkable: for any real future
dispatch, it names, per avenue, exactly what would leave this machine (which shard, which
byte range, which hash), to whom (which avenue, which named account/project), and what would
be expected back (a receipt, a checkpoint delta, both) — before the transfer happens, not
after. No egress manifest instance exists yet because no dispatch has happened; this document
fixes the *shape* an egress manifest must have so that when a real dispatch is proposed, it is
checkable against this shape rather than invented ad hoc:

```
{
  "schema": "ember-egress-manifest-v1",
  "avenue": "kaggle | colab | hf",
  "shard": {"path": "<repo-relative path or receipt id>", "sha256": "<hex>"},
  "outbound": [{"artifact": "<name>", "sha256": "<hex>", "destination": "<named account/project>"}],
  "expected_return": ["receipt", "checkpoint-delta"],
  "approval": {"approved_by": "<user>", "approved_at": "<ISO8601Z>"}
}
```

Zero outbound transfer has occurred against this schema. It exists so that the day a real
dispatch is proposed, the proposal is checkable, not improvised.

## What this document does not claim

This document does not claim any of the three mechanisms above have been executed across a
real substrate boundary. Checkpoint-portability's identity-manifest verifier is real and has
executed (legs 3/4, on this machine, against a locally-produced checkpoint) — it has not yet
been exercised against a checkpoint that crossed a substrate boundary. Work-sharding's shard
primitive is real and has executed (`TOKEN-SHARDS-V0`, launch-rail) — it has not yet dispatched
a shard to an external avenue. Receipt-merge's append-only law is real and enforced today for
every receipt in this repo — no receipt in this repo has yet originated from an external
avenue. The capability half of C-FED — actually dispatching work and getting a real receipt
back from Kaggle, Colab, or HF — stays legitimately RED until that first real dispatch
happens under real per-avenue approval. This document is the pre-birth design half only.
