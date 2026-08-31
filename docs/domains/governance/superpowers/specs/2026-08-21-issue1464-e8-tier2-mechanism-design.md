# Issue 1464 E8 Tier-2 Mechanism Design

## Goal

Add an owned, certified A1 Tier-2 optimizer that changes dense-training state
cost while preserving the existing BF16 3.839B model, data, seed, schedule, and
capability identity.

## Authority and invariants

- Mechanism: `OWNED_Q_GALORE_PROJECTED_GRADIENT`.
- Dense BF16 model weights are never INT4/INT8 replicated or replaced.
- No vendored optimizer, bitsandbytes, GaLore, or Q-GaLore package is used.
- All persistent optimizer and projection state resides on the selected CUDA
  device. The candidate may create bounded per-parameter compute transients but
  may not maintain a full-model gradient or FP32 master-weight copy.
- Learning rate `0.00001`, betas `[0.9, 0.999]`, epsilon `1e-8`, and weight decay
  `0.01` match Tier-1.
- Rank is `min(512, min(parameter.shape))`; projection refresh gap is 200
  optimizer steps; projection scale is 0.25.
- Projection basis uses signed symmetric INT4 with 256-value blocks. First
  moments use signed symmetric INT8 with 256-value blocks. Nonnegative second
  moments use unsigned UINT8 with 256-value blocks. Every block stores an FP32
  scale on CUDA; zero blocks use scale 1 and all-zero payload.
- Stochastic rounding is forbidden. Parameter registration order, parameter
  names, seed, and refresh ordinal are receipt-bound.

## Optimizer structure

`a1_tier2_optimizer.py` owns the mechanism. It implements a
`ProjectedQuantizedAdamWCUDA` optimizer with the same fused-backward lifecycle as
Tier-1.

For a 2-D gradient `G` with shape `(m, n)`, the optimizer projects along the
smaller dimension:

- If `m >= n`, store a right basis `P` with shape `(r, n)`, compute `G_r = G P^T`,
  update quantized moments shaped `(m, r)`, reconstruct `U = U_r P`, and apply
  `scale * U` to the BF16 weight.
- If `m < n`, store a left basis `P` with shape `(m, r)`, compute `G_r = P^T G`,
  update moments shaped `(r, n)`, reconstruct `U = P U_r`, and apply
  `scale * U`.

At step 1 and every 200th optimizer step, the basis is refreshed from the current
full gradient using a top-rank SVD computed in FP32. CUDA deterministic
algorithms are required. Singular-vector sign ambiguity is canonicalized by
forcing the largest-magnitude element in each vector positive before
quantization. A refresh that cannot execute under deterministic mode refuses the
run; it never silently falls back to a random or stale basis. A seeded-random
basis is a different mechanism class and is forbidden without a separately
reviewed authority amendment.

One-dimensional parameters and matrices whose smaller dimension is no greater
than rank use an unprojected block-quantized AdamW state on CUDA. This avoids
inventing a projection that cannot reduce state. Weight decay is decoupled and
applied directly to the BF16 parameter before the Adam update, matching Tier-1's
ordering.

The shared full-gradient norm set is exactly every registered model parameter
that receives a gradient in the text step, including all 1-D parameters and
excluding only parameters whose gradient is `None`. Both tiers traverse that
same canonical parameter registration order. The accumulator runs before
projection. The hook then
projects, dequantizes only the current parameter's moment blocks to FP32,
performs AdamW arithmetic, requantizes the moments, updates the BF16 parameter,
and clears the full gradient. No full-model gradient set coexists.

## Contract and admission

A new closed JSON contract `ember-restart-3b-a1-tier2.json` records mechanism,
state placement, projection rank/gap/scale/direction policy, quantization formats
and block sizes, hyperparameters, deterministic policy, and lineage. Its SHA is
part of the input-identity and training-dependency closure.

The certified run spec explicitly declares:

- `a1_family`
- `a1_tier = TIER_2`
- `a1_mechanism = OWNED_Q_GALORE_PROJECTED_GRADIENT`
- Tier-2 contract path and SHA
- corrected liveness receipt path and SHA
- the existing dense token, comparison, step, checkpoint, write-budget,
  telemetry, and resource fields

The certificate authorizes the exact family/tier/mechanism tuple. Validation
reopens the liveness receipt and requires `FALLBACK_REQUIRED`, exact threshold
binding, and a valid self digest before it can build runner argv. Tier-1 remains
valid without Tier-2-only fields; partial cross-tier shapes refuse.

`run_vertical_slice.py` receives a distinct `a1-dense-tier2` command. It shares
the dense model/data runner but selects the Tier-2 contract, optimizer,
preflight, checkpoint writer, and finalizer. No alias from Tier-2 to the Tier-1
command is admitted.

## Resource preflight

Tier-2 preflight derives, without allocating model state:

- BF16 model bytes;
- maximum single full-gradient transient;
- projected first/second moment payload bytes;
- moment scale bytes;
- packed projector bytes and scale bytes;
- worst-case current-parameter dequantization and SVD workspace reserve;
- checkpoint payload and transient write bytes;
- CUDA free-margin and B: custody floor.

It requires every projected-state byte to fit on CUDA with the configured margin
and records the exact inventory in the run core. Host full-state fields are zero
and cannot masquerade as Tier-1 admission.

## Checkpoint and final receipt

Tier-2 uses a separate closed checkpoint schema. Each shard stores BF16 model
weights plus, for every parameter, step, projection direction/rank/refresh
ordinal, packed basis payload and scales where applicable, packed moment payloads
and scales, original shapes, and quantization metadata. The verifier reopens
every shard with CPU mapping, checks raw hashes and tensor metadata, and proves
the optimizer inventory covers every registered parameter.

The terminal run receipt uses the existing R1-E8 run schema but truthfully emits
`tier=TIER2`, the owned mechanism, `cpu_offload=false`, full parameter coverage,
the unchanged dense architecture revision and parameter count, and the Tier-2
checkpoint hash. It remains identity-equal to the fresh Tier-1 reference except
for tier/mechanism and certified-launch identity.

## Failure behavior

- Missing corrected liveness binding: refuse before argv construction.
- CUDA or deterministic SVD unavailable: refuse before training update.
- Sparse/non-finite gradient or quantization scale: refuse and retain custody.
- Incomplete optimizer inventory: refuse checkpoint and terminal receipt.
- Any CPU-resident persistent Tier-2 state: inventory failure.
- Any attempt to load a Tier-1 checkpoint as Tier-2, or the reverse: schema and
  tier/mechanism refusal.

## Testing

- Quantization round-trip, block boundary, zero block, signed/unsigned range, and
  deterministic byte tests.
- Projection direction/shape and reconstruction tests for tall, wide, square,
  1-D, and small matrices.
- Fixed-seed deterministic basis and sign-canonicalization tests.
- Three-step small-model tests proving all parameters update, state remains on
  CUDA when available, gradients are freed, and the shared pre-projection norm
  matches the Tier-1 measurement helper.
- Closed contract, resource preflight, checkpoint round-trip/tamper, launcher
  admission/refusal, argv route, finalizer, and run-receipt identity tests.
- Existing Tier-1 tests must remain byte-identical except for the deliberate new
  telemetry field.

## Operational sequence

Merge parity plumbing first, rebase this carrier, remint input identity and
dependency closure, obtain exact-head review and green checks, then merge. Mint
fresh launch authority from merged public source. Execute a fresh Tier-1 reference
and Tier-2 candidate serially with the same frozen identity under the runner's
250-GiB B: floor and single-GPU law. Publish parity only after both chains are
terminal and independently reopened. The parity packet and final adjudication
record the named residual risk that T-09 is 100 steps while the certified refresh
gap is 200: initial SVD construction is exercised, but the steady-state refresh
path is not. The gap is not shortened for the test because parity must execute
the certified mechanism unchanged.
