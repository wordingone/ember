# EMBER-02 R1-E8 receipt schemas v1

This document freezes the pure-validation packet for the A1 discriminating
gate in `ember02-preregistration-v1.md` §4-A1. It does not authorize a model
implementation or claim that an A1 run has occurred.

All JSON receipt objects are closed: unknown or missing fields refuse. Every
`{path, sha256}` reference is packet-relative, may not traverse its packet
root, and is reopened from raw bytes. Receipt `receipt_sha256` values are the
SHA-256 of canonical JSON (`sort_keys=true`, separators `,` and `:`, UTF-8)
after removing that field. Derived decimals use 12 places and round-half-even.

## Schemas

- `ember02-r1-e8-run-v1` binds terminal certified-launch identity, arm/tier,
  source, architecture and parameter counts, optimizer coverage/offload,
  matched data identity, energy coverage, and checkpoint. A1 requires total
  and active parameters both at least 3,000,000,000 and no router or experts.
  Tier 1 requires full-state AdamW, CPU offload, and optimizer coverage equal
  to the complete parameter count.
- `ember02-r1-e8-liveness-series-v1` binds a run-receipt digest to contiguous
  raw step rows containing tokens, whole-boundary seconds, and proxy joules.
- `ember02-r2-charged-budget-contract-v1` is the canonical external authority
  for the two projected R2 token counts. The E8 validator never derives or
  selects a charged-budget formula. The contract is reopened and hash-bound
  to both run receipts and their comparison identity. Absence is permanently
  `EVIDENCE_MISSING`, regardless of measured throughput.
- `ember02-r1-e8-liveness-v1` binds the threshold document, charged-budget
  contract, Tier-1/A3 runs, and both raw liveness series. The validator derives
  T-06 and T-08 from the bound threshold document, recomputes tokens/second,
  joules/token and the contract-projected token ratio, then adjudicates
  `TIER1_LIVE` or `FALLBACK_REQUIRED`.
- `ember02-r1-e8-parity-series-v1` binds a candidate/reference run digest to
  exactly T-09 contiguous loss and gradient-norm rows.
- `ember02-r1-e8-parity-v1` is legal only after a bound liveness receipt says
  `FALLBACK_REQUIRED`. It binds the Tier-2 candidate, Tier-1 AdamW reference,
  raw series, and a green R1-E7 receipt containing both required sigma values.
  The validator derives T-09, T-20, and F-11 inputs from the bound threshold
  document and recomputes both inequalities.

## Battery composition

`scripts/r1_exit_battery.py::check_r1_e8` is the first real consumer. It may
return `MET` only for either (a) a valid Tier-1 liveness receipt with no parity
receipt, or (b) a valid below-floor liveness receipt plus a valid parity PASS.
Missing authority remains `EVIDENCE_MISSING`; malformed, stale, swapped,
subscale, arithmetically inconsistent, or route-confused evidence is
`REFUSED`; a valid parity FAIL is `NOT_MET`.

This source carrier leaves real execution unresolved: no receipt here proves
that a certified dense >=3B A1 model, full-state CPU-offloaded AdamW, or a
matched Tier-2/reference segment has run.

## Liveness evidence producer

`tools/ember-restart-3b/a1_e8_evidence.py::mint_liveness_receipt` mints the
`ember02-r1-e8-liveness-v1` packet from already-produced evidence: it reopens
the Tier-1 A1 run (`a1_execution.finalize_tier1_run`'s output) and the
matched A3 run by exact raw SHA-256, copies both plus the externally frozen
`ember02-r2-charged-budget-contract-v1` authority byte-verified into one flat
packet directory, derives both runs' `ember02-r1-e8-liveness-series-v1`
objects from raw per-step telemetry, and recomputes tokens/second and
joules/token independently of the validator before minting the closed,
self-digested receipt. It never derives, selects, or infers
`projected_r2_tokens`; an absent contract raises a distinguished
`E8EvidenceProducerMissing`, routed by callers to `EVIDENCE_MISSING`, never a
refusal.

Raw per-step liveness telemetry reuses the frozen `train_step` envelope
(`{"ts":..., "kind":"train_step", "source":"ember-restart-3b", "payload":
{"run_id":..., "step":int, ...}}`), with the payload additionally carrying
`tokens` (positive integer), `wall_seconds` (positive decimal), and
`proxy_joules` (non-negative decimal) for the steps a liveness series covers.

`tools/ember-restart-3b/a1_execution.py::run_dense_a1` wires `tokens` and
`wall_seconds` honestly as of issue #1464's first residual: each is measured
per step (`time.perf_counter()` at step start, differenced at
telemetry-write time).

`tools/ember-restart-3b/run_vertical_slice.py`'s governed (`run()`) and
semantic (`run_semantic()`) routes emit the same frozen `tokens` and
`wall_seconds` fields, via the shared helper `_frozen_envelope_fields`. Both
routes' `progress_callback` closures already receive a per-step progress
dict from the shared pretraining producer (`pretrain.py::
run_pretraining_segment`, which `run_manifest_bound_semantic_segment`
delegates to for the semantic route) carrying the identical measured
quantities under its own names -- `tokens_consumed` (the step's exact token
count) and `step_ms` (a `time.perf_counter()`-measured wall-clock duration
in milliseconds). `_frozen_envelope_fields` is an honest unit/name
transcription of those same measurements (`wall_seconds = step_ms /
1000.0`), never a new or fabricated measurement; a source quantity that is
absent or not a usable positive number is omitted rather than defaulted, so
`derive_liveness_series` continues to correctly find that row
liveness-incomplete. The existing `tokens_consumed`/`step_ms` keys are left
in the payload unchanged for the E4 receipt accumulator and battery, which
still read them under their original names.

`proxy_joules` is now derived, closing issue #1464's second residual, by
`tools/ember-restart-3b/a1_energy_apportionment.py`. The energy sidecar
(`energy_proxy_logger.py --watch-pidfile`, launched as an independent OS
process that communicates with the training child only through a pidfile --
so an evidence sampler can never block or crash certified training) now
persists its raw measured-window GPU readings as it captures them, one
`{"ts": <unix seconds>, "watts": <non-negative float>}` object per line, to
`energy_proxy_logger.samples_path_for(receipt_path)` -- a sibling of the
aggregate `ember-energy-proxy-run-v1` receipt, named by the receipt's file
stem plus `.gpu-samples.jsonl`. This is the raw record the whole-run
`energy` block was already integrated from; it was previously discarded
once aggregated.

`a1_energy_apportionment.apportion_step_energy` reopens that raw record and
a run's raw `train_step` telemetry, and derives each step's `proxy_joules`
as the trapezoidal integral of REAL measured draw over the step's
whole-boundary wall interval `[ts - wall_seconds, ts]` -- the same `ts` and
`wall_seconds` `_train_step_envelope` already writes. This is measured
apportionment, never fabrication: a step's `proxy_joules` is minted only
when (a) at least one raw sample timestamp falls inside the step's own
interval, and (b) both interval boundaries fall inside the sample record's
own timestamp coverage, so the trapezoid only ever interpolates between two
real observations and never extrapolates past one. A step that fails either
condition -- the sidecar never ran, its samples are too sparse to touch this
step's interval, or this step's interval reaches outside the sample
record's own coverage -- keeps no `proxy_joules` field at all, exactly the
schema-legal absence `derive_liveness_series` already refuses correctly (its
`no liveness-complete train_step rows` refusal). A samples record that is
present but malformed, non-finite, or carries a negative watts reading
refuses the WHOLE record (`EnergyApportionmentError`) rather than silently
skipping the bad line: a corrupted or negative-power sample stream cannot be
trusted to bound any step's interval honestly, including steps far from the
defect.

`a1_energy_apportionment.enrich_telemetry_with_energy` performs the actual
write: an in-place, atomic (same-directory temp file + `os.replace`)
rewrite of the telemetry file that adds `proxy_joules` to every row this
module could honestly derive, leaving every other line -- other runs, other
event kinds, and any row it could not derive -- byte-identical, and never
overwriting a row that already carries the field. It is wired into
`certified_train_launch.py::execute_validated_launch` as
`_apportion_a1_step_energy`, called after `_finish_energy_sidecar` closes
the sidecar's measured window and strictly before `_finalize_a1_packet_a`
-- no receipt has pinned the A1 telemetry file's bytes yet at that point, so
the in-place rewrite is safe. Never fatal, mirroring the sidecar's own
non-fatal spawn posture: a run this pass cannot enrich (no sidecar samples,
no overlapping coverage) simply stays exactly as liveness-incomplete at the
E8 producer as it did before this module existed.

Architectural note: the sidecar and the training loop are two independent
processes by design (the #1489 lesson: an evidence sampler must never be
able to block or crash the certified child), so there is no honest in-loop
point at which `_train_step_envelope` itself could attribute a step's
energy -- the training process has no live channel to the sidecar's
in-flight samples while a step is executing. The derivation is therefore a
post-pass over two already-closed artifacts, reopened and joined after both
producing processes have exited, the same "reopen, never construct forward"
discipline this document's liveness producer already follows for run
receipts and the charged-budget contract.
