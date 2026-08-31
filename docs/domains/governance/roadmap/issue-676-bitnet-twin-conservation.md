# Issue #676 terminal conservation ruling

Status: `SUPERSEDED_NOT_PLANNED` for the prohibited historical 102M model and
50M-token exact-twin GPU vehicle. BitNet remains a conserved research variable
under canonical EMBER-02 issue #1116 and may only be tested on an admissible
current network with at least 3B parameters.

Source master: `87f9669c537715ff0008080c22002eff04040bba`.

## Authority and credit boundary

- `completion_credit=false`
- `result_credit=false`
- `gpu_credit=false`
- `training_credit=false`
- `checkpoint_credit=false`
- `capability_credit=false`
- `milestone_credit=false`

The exact 102M dimensions remain historical preregistration provenance. No
50M smoke pair or full run is credited.

## Lossless current-scale twin contract

A retained BitNet comparison must use an exact architecture-identical current
3B-or-larger twin with GQA, per-head QK RMSNorm, tied embedding and output
head, `MTP=0`, no linear bias, and identical realized parameter counts. Only
attention and FFN linears differ by their effective operand: the treatment
uses ternary absmean `{-1,0,+1}` forward quantization with STE while the dense
arm is plain BF16 and refuses any attached quantizer. Embedding, output head
and norms stay non-ternary; latent parameters and optimizer state remain high
precision.

Every run must bind source, config, seed, token order, evaluation manifest,
exact dtype and optimizer inventory, and refuse any mismatch. It must receipt
realized ternary fractions, dense-path absence by active refusal, peak VRAM,
host commit, finite loss and paced throughput on identical batches.

Execution binding remains mandatory: hash the actual matmul operand; require
all-zero and sign-flipped intervention fixtures; detect latent bypass; prove
finite nonzero STE gradients; enumerate every intended attention/FFN linear
as an instrumented member; and refuse any unbound instance.

L3 remains binding: no external model may generate, filter, rank, select,
order or stop any training token. Full-run authorization remains blocked until
the bounded matched pricing leg projects no more than seven sequential GPU
days for all four registered runs and the standing greater-than-one-hour
efficiency-proof gate passes.

## Lossless transfer

Canonical transfer URL placeholder:

- EMBER-02 / #1116: https://github.com/wordingone/ember/issues/1116#issuecomment-5224552660

## Reopen and falsifier

Reopen if the accepted transfer drops GQA, per-head QK norm, tied head,
`MTP=0`, no-bias identity, attention/FFN-only treatment, architecture-identical
dense arm, execution binding, L3, seven-day projection, efficiency proof,
identity/receipt negatives or rollback. Any sub-3B learned execution is
constitutionally inadmissible.

`NO_NEW_PARALLEL_AUTHORITY`
