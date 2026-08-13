goal_id: EMBER-02
workstream_id: EMBER-02A
next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

# R1 WARM-100 entry adapter (schema v2)

`scripts/ember_restart/contract.py r1-entry` is a thin producer/consumer
adapter around the existing `ember-owned-rung-v1` validator. It does not
replace that validator and it does not launch a run. This file documents the
adapter's current schema, `ember-r1-warm100-entry-v2`; the filename is kept
stable across the v1 -> v2 bump rather than renamed, since nothing links to it
by version-numbered path.

The command first runs `contract.py validate` on the supplied candidate
manifest. Only a green `CHECKPOINT_CANDIDATE` can produce the entry receipt.
The receipt then binds the immutable source commit and Git blob hashes for the
contract, Ember CLI train command, fixed certified consumer, and Ember Lab
training-verification source, plus the preregistration, runtime config, and
fixed-prior manifest bytes.

## Source-identity binding (v2, issue #1296 P1)

Before v2, nothing tied `source_root` to the canonical Ember checkout or
`source_commit` to real published Ember history: any git repository whose
`HEAD` matched the claimed commit and whose tree was clean could mint a green
receipt binding its own, potentially attacker-authored, bytes at the governed
paths. v2 closes that gap with two additional bindings, both enforced
identically in `build_r1_warm100_entry` and `validate_r1_warm100_entry`, root
first then commit:

- **`source_root` -> canonical checkout or managed worktree.** `source_root`
  must share the canonical checkout's Git common directory (a clone or fork
  has its own object store even with byte-identical contents) and must either
  be that checkout itself or a `scripts/worktree_lifecycle.py`-managed
  worktree of it. An ad-hoc `git worktree add` that bypasses the lifecycle
  tool is refused, as is a missing or malformed worktree-lifecycle registry.
- **`source_commit` -> governed-remote ancestry.** The governed remote's ref
  is resolved by contact (`git ls-remote`, never a locally configured
  `origin` -- an `origin` URL is a one-line, spoofable config write, not an
  identity), and `source_commit` must be that ref's tip or a real ancestor of
  it (`git merge-base --is-ancestor`), proven against real Git history rather
  than trusted from any string comparison. Minting fails closed if the
  governed remote is unreachable; there is no offline/degraded fallback for
  this rung-entry gate.

The result is recorded in a closed `source_binding` block:

```json
{
  "canonical_common_dir_bound": true,
  "worktree_identity": "MAIN" | "MANAGED" | "LEGACY",
  "governed_remote": "<contacted remote>",
  "remote_master_sha": "<40-hex>",
  "ancestry": "EQUAL" | "ANCESTOR"
}
```

`canonical_root`, `governed_remote`, and `governed_ref` are library-only
parameters on `build_r1_warm100_entry`/`validate_r1_warm100_entry`, used by
tests to bind against a synthetic canonical checkout or a hermetic,
file-transport remote. The CLI exposes no equivalent flags: it always binds
against the real canonical checkout (the repository that owns the executing
`contract.py` bytes) and the real governed remote
(`https://github.com/wordingone/ember`).

The resulting schema is `ember-r1-warm100-entry-v2` with:

- `entry: WARM-100`, `steps: 100`, and `result: PREP_ONLY`;
- dispatch fixed to `ember-cli` -> `ember-lab` through
  `certified_train_launch.py`;
- `energy.boundary: DEGRADED_PROXY` disclosed;
- `closed_boundary.status: PENDING_EXECUTION` and
  `closed_boundary.ledger_complete: false`;
- an explicit claim boundary with execution, sufficiency, capability, and
  benchmark credit all false;
- the `source_binding` block described above.

The receipt is path-free and self-hashed. Reopening it requires the caller to
reopen the exact candidate manifest and pass that path to
`validate_r1_warm100_entry`; manifest bytes, source commit, source-identity
binding, pinned prereg/config files, source blobs, dispatch, and claim
boundary are independently checked.

This carrier satisfies the CPU/source launch-readiness tranche only. The
remaining terminal work is a governed Ember CLI -> Ember Lab WARM-100 run that
produces the actual per-step ledger, checkpoint round-trip, energy-proxy,
frontier, forecast, seed-noise, and A1 receipts required by the preregistration.
No execution, model, sufficiency, capability, benchmark, or result credit is
claimed here.
