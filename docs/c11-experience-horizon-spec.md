# C11 — Experience-horizon capability delta, spec v1

Canonical spec for totality condition **C11** as defined in
`docs/spec/conditions-v1.md` (C11 row). `conditions-v1.md` names this file and
sets the contract; this file makes the contract machine-checkable and is the
authority `scripts/ember_totality/test_c11.py` implements.

**The lever is experience, not the clock.** Wall-clock duration is a timer that
runs while learning happens; it is never the thing being earned. A run that sat
for 24 hours and a run that sat for 1 hour are indistinguishable to this
condition unless the longer one *consolidated strictly more novel problems into
resident weights and reached a held-out capability the shorter one does not
reach*. The retired 1h/3h/24h wall-clock re-earn sequence is **superseded** and
is not a pass path.

## What C11 requires (from `conditions-v1.md`)

Across increasing experience-horizon scales (short < medium < long *novel*
problems learned and consolidated into resident weights), each longer horizon —
via real learning updates (pre ≠ post parameter hashes; gradient steps
Merkle-bound to the novel problem ids) — produces a measured held-out capability
delta the shorter horizon does not reach, and the long-horizon consolidation is
load-bearing: deleting it degrades long-horizon capability back toward the
**short-horizon** level. Capability is proven by **live re-execution** of
sampled solutions, never trusted arrays.

Does NOT count: wall-clock duration; CPU re-hash of repeated rows; fabricated
outcome booleans; identical pre/post checkpoints; deletion measured against the
untrained base instead of the short-horizon checkpoint.

Invalid tokens: `unearned_duration`, `clock_in_disguise`, `fabricated_outcomes`,
`novelty_spoof`, `deletion_uses_wrong_baseline`.

## Receipt surface

Four receipts under `receipts/ember-mvp/c11-experience-horizon/`:

| File | Role |
|---|---|
| `horizon-short.json` | shortest experience horizon |
| `horizon-medium.json` | middle horizon |
| `horizon-long.json` | longest horizon |
| `deletion.json` | long-horizon consolidation deletion ablation |

A genuinely absent receipt set is **UNEVALUABLE** (claim-bearing input missing),
never GREEN and never RED — nothing has been claimed yet. A receipt set that is
present but does not satisfy a check is **RED**. Partial evidence reports
per-check gaps by name and stays UNEVALUABLE only for the checks whose inputs
are absent; any check whose inputs are present and fail makes the whole
condition RED.

### Horizon receipt schema

```json
{
  "ticket": "EMBER-C11-EXPERIENCE-HORIZON",
  "ts": "20260803T000000Z",
  "horizon": "short",
  "ordering_basis": "novel_problem_count",
  "substrate": {"model_id": "...", "param_count": 3000000000},
  "novel_problems": {
    "problem_ids": ["np-0001", "np-0002"],
    "pretrain_overlap_ids": [],
    "corpus_exclusion_digest": "sha256:..."
  },
  "learning_update": {
    "pre_param_hash": "sha256:...",
    "post_param_hash": "sha256:...",
    "hash_algorithm": "sha256 over the sorted state_dict tensor bytes",
    "merkle_leaf_recipe": "sha256(f\"{step}:{problem_id}\")",
    "merkle_root": "sha256:...",
    "gradient_steps": [{"step": 0, "problem_id": "np-0001", "grad_norm": 0.41}]
  },
  "heldout": {
    "suite_id": "c11-heldout-v1",
    "claimed_score": 0.5,
    "items": [
      {"item_id": "ho-0001", "passed": true,
       "execution": {"executor": "...", "exit_code": 0,
                     "stdout_sha256": "...", "duration_s": 0.83}}
    ]
  },
  "wall_seconds": 3607.0
}
```

`wall_seconds` may be recorded. It is **never** read as evidence — see CHK-9,
which proves the verdict does not depend on it.

### Deletion receipt schema

```json
{
  "ticket": "EMBER-C11-EXPERIENCE-HORIZON-DELETION",
  "ts": "20260803T000000Z",
  "deleted_component": "long_horizon_consolidation",
  "baseline_label": "short_horizon_checkpoint",
  "baseline_checkpoint_hash": "sha256:<horizon-short post_param_hash>",
  "arms": {
    "short":                    {"checkpoint_hash": "sha256:...", "items": [...]},
    "long":                     {"checkpoint_hash": "sha256:...", "items": [...]},
    "long_minus_consolidation": {"checkpoint_hash": "sha256:...", "items": [...]}
  }
}
```

Arm `items` carry the same per-item shape as `heldout.items`, including the
`execution` block — deletion capability is re-executed too, never asserted.

## The nine recomputed checks

Every check derives its own numbers from raw rows. No scalar the receipt reports
about itself is trusted; where a receipt states a summary (`claimed_score`,
`merkle_root`), the check recomputes it and compares.

**CHK-1 — horizon ordering by novel-problem count.** Recount distinct novel
problem ids per horizon and require
`|short| < |medium| < |long|`. The ordering key is the count of consolidated
novel problems; no duration field participates. Violation → `clock_in_disguise`.

**CHK-2 — novelty integrity.** Within each horizon the problem-id list carries
no repeats (`len(set) == len(list)`; a repeated row re-hashed is not new
experience), `pretrain_overlap_ids` is empty, and each longer horizon's id set is
a strict superset of the shorter one's (a longer horizon has seen everything the
shorter one saw, plus more). Violation → `novelty_spoof`.

**CHK-3 — real parameter change.** Per horizon `pre_param_hash != post_param_hash`,
and the three horizons' `post_param_hash` values are pairwise distinct. Identical
checkpoints mean nothing was learned regardless of what else the receipt claims.

**CHK-4 — gradient steps Merkle-bound to the novel problem ids.** Recompute the
Merkle root from the receipt's own `gradient_steps` leaves using the declared
`merkle_leaf_recipe` (`sha256(f"{step}:{problem_id}")`, pairwise-hashed in
receipt order, odd node promoted) and require it to equal `merkle_root`. Every
leaf's `problem_id` must be in that horizon's novel id set, and the step list
must be non-empty. This is what binds the claimed learning to the claimed
novelty; without it the two halves of the receipt are unrelated.

**CHK-5 — held-out capability delta strictly increasing.** Recompute each
horizon's score as the mean of its held-out `passed` rows and require
`long > medium > short`, each gap exceeding the pre-registered noise floor
(`NOISE_FLOOR`, 0.02 absolute in v1). `claimed_score` is compared to the
recomputed value and a mismatch is a failure, not a tiebreak.

**CHK-6 — held-out contamination.** The union of all three horizons' training
problem ids must not intersect any held-out `item_id`. A capability delta
measured on problems that were trained on is not a delta.

**CHK-7 — live re-execution of sampled solutions.** Every held-out item carries
an `execution` block with an executor identity, an integer `exit_code`, a
`stdout_sha256`, and `duration_s > 0`. The pass rate recomputed from
`exit_code == 0` must agree with the `passed` flags. A `passed` array without
execution evidence is `fabricated_outcomes` — the receipt is asserting outcomes
rather than having run anything.

**CHK-8 — deletion measured against the short-horizon checkpoint.**
`baseline_checkpoint_hash` must equal `horizon-short.json`'s `post_param_hash`
(deletion against the untrained base is `deletion_uses_wrong_baseline`), the
three arm checkpoint hashes must be distinct, and, recomputing all three arm
scores from their own items: `long > long_minus_consolidation`, and
`long_minus_consolidation` must sit closer to `short` than to `long` — the
consolidation being removed drags capability back toward the short-horizon
level, which is what "load-bearing" means here.

**CHK-9 — duration-invariance (the clock is not the lever).** Re-derive CHK-1
through CHK-8 over a copy of the receipt set with every duration-shaped field
(`wall_seconds`, `duration_s`, and any `*_seconds` key) stripped out, and require
the identical verdict. If removing the clock changes the answer, the clock was
load-bearing → `unearned_duration`. This check also sweeps all four receipts for
any of the five invalid tokens appearing as a live value.

CHK-9 deliberately re-runs the other eight rather than inspecting a flag: a
condition whose whole point is that duration is not the lever is best proven by
showing the verdict survives duration's removal.

## What is still outstanding

The checker is complete and evaluates this contract today. The **evidence** does
not exist yet: producing accepted short/medium/long capability-delta receipts
requires the sufficiently trained owned 3B substrate under EMBER-05. Until those
land, C11 reports UNEVALUABLE naming the absent receipts and the per-check gaps —
which is the honest state, and is distinct from the pre-#107 behaviour where C11
reported UNEVALUABLE because the checker was still looking for the retired
1h/3h/24h duration receipts.

Control fixtures exercising each check's sharp tooth live in
`scripts/ember_totality/chk_controls/run_controls.py` (`build_c11_horizon`).
