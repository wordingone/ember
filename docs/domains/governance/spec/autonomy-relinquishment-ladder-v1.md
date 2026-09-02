<!-- EMBER_CONSERVATION_V1
minimum_new_network_parameters=3000000000
destination_total_parameters=>27000000000
required_native_capabilities=text,image,audio,reasoning,structured_tool_use
borrowed_lineage=frozen_reference_only
mechanism_erasure=forbidden
-->

# Dynamic operator relationship and autonomy contract

This contract is subordinate to GOAL.md. It is a configurable relationship
protocol, not one operator's permanent policy and not a one-way relinquishment.

## Invariants

- The operator retains ownership, voluntary direction, and final scope.
- Ember reasons independently and may challenge a decision with evidence.
- Authority changes are explicit, inspectable, revocable, and scoped.
- Ember never silently grants itself permissions or exceeds the operator's own
  authority.
- High autonomy preserves audit, rollback, and emergency pause.
- Model capability confidence is separate from authority over third parties or
  irreversible systems.

## Configurable dimensions

Modes can vary by operator and task across filesystem, network, execution,
training, spending, communication, deployment, external systems, reversibility,
duration, resource envelope, challenge intensity, and evidence threshold.
Per-action approval, grouped approval, accept-edits, auto-review, bounded bypass,
and sandbox-only modes are supported relationships rather than universal
defaults.

## Trust calibration

Initial caution is appropriate when behavior is unproven. Trust grows from
representative and adversarial sandbox tests, real scoped operation,
competence, honesty, recoverability, resource discipline, and predictable mode
transitions. Privilege expansion requires explicit operator acceptance.
Failures or changed conditions can immediately restrict or revoke trust.

Behavior tests cover ambiguous instructions, conflicting evidence, destructive
or irreversible action, third-party boundaries, overruns, mode transitions,
revocation, rollback, and escape attempts. Configuration presence alone is not
evidence.

## Claimed-rung evidence contract

A rung is unclaimed until the public C-AUTO probe validates the closed evidence
contract below. This applies to every rung, including R0; filenames, empty JSON,
free-form provenance strings, and self-reported timestamps never establish a
claim.

Each claimed rung names at least five unique window receipt filenames confined
to `receipts/autonomy-ladder/` (absent as of 2026-08-01 in this contract tree — no rung has been
claimed yet, per C-AUTO's honest zero-claim state). Every `ember-autonomy-window-v2` receipt has a
closed schema, a strict ISO-8601 UTC timestamp, `verdict=PASS`, and one distinct
real Git commit. The probe resolves that commit with Git and requires its
committer timestamp to equal both the receipt timestamp and the independently
stated commit timestamp. Its structured Ember provenance token is the canonical
SHA-256 of the producer and the canonical window-payload SHA-256.

Exactly one `ember-autonomy-claim-v2` receipt may exist for a claimed rung. It
must postdate the newest window, bind the newest real commit, and list every
state-selected window in order with the SHA-256 of the exact receipt bytes.
Duplicate JSON keys, unknown or missing schema fields, malformed UTF-8 or UTC,
unsafe paths, missing or non-commit Git objects, duplicate commits, token/hash
mismatches, reordered windows, or duplicate claim receipts are terminal RED.
A post-reversion re-climb is accepted only when this validated claim timestamp
strictly postdates the latest strict-UTC reversion timestamp.
