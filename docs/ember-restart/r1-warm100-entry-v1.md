goal_id: EMBER-02
workstream_id: EMBER-02A
next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

# R1 WARM-100 entry adapter v1

`scripts/ember_restart/contract.py r1-entry` is a thin producer/consumer
adapter around the existing `ember-owned-rung-v1` validator. It does not
replace that validator and it does not launch a run.

The command first runs `contract.py validate` on the supplied candidate
manifest. Only a green `CHECKPOINT_CANDIDATE` can produce the entry receipt.
The receipt then binds the immutable source commit and Git blob hashes for the
contract, Ember CLI train command, fixed certified consumer, and Ember Lab
training-verification source, plus the preregistration, runtime config, and
fixed-prior manifest bytes.

The resulting schema is `ember-r1-warm100-entry-v1` with:

- `entry: WARM-100`, `steps: 100`, and `result: PREP_ONLY`;
- dispatch fixed to `ember-cli` -> `ember-lab` through
  `certified_train_launch.py`;
- `energy.boundary: DEGRADED_PROXY` disclosed;
- `closed_boundary.status: PENDING_EXECUTION` and
  `closed_boundary.ledger_complete: false`;
- an explicit claim boundary with execution, sufficiency, capability, and
  benchmark credit all false.

The receipt is path-free and self-hashed. Reopening it requires the caller to
reopen the exact candidate manifest and pass that path to
`validate_r1_warm100_entry`; manifest bytes, source commit, pinned prereg/config
files, source blobs, dispatch, and claim boundary are independently checked.

This carrier satisfies the CPU/source launch-readiness tranche only. The
remaining terminal work is a governed Ember CLI -> Ember Lab WARM-100 run that
produces the actual per-step ledger, checkpoint round-trip, energy-proxy,
frontier, forecast, seed-noise, and A1 receipts required by the preregistration.
No execution, model, sufficiency, capability, benchmark, or result credit is
claimed here.
