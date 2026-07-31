# Update-survival preflight v1

## Purpose

Any training leg that stores trainable parameters below FP32 must refuse launch
unless a CPU-safe update-survival preflight proves that configured optimizer
steps survive the realized storage dtype. Total parameter delta is not signal
survival: decoupled weight decay can move a parameter while the gradient-caused
update is completely rounded away.

## Inputs

The reusable Python API receives deduplicated named tensors after parameter-group
construction, their tensor class, realized initial bytes, one captured or
synthetic gradient per tensor, required-survival assertions, a closed optimizer
family/configuration, optional existing optimizer state, treatment dtype,
increasing positive step counts, and one survival floor per tensor class.
Gradient-source identity is nonempty and is content-addressed together with every
gradient tensor.

Supported optimizer adapters are explicit SGD, AdamW, and PyTorch Adafactor.
Every optimizer keyword is required and unknown keywords are rejected.
Adafactor `eps` scalars must be resolved before cloning; `eps1=None` is
`PREFLIGHT_INVALID_REFERENCE`, because BF16 and FP32 would otherwise execute
different algorithms.

## Live optimizer binding

`run_live_optimizer_update_survival_preflight` consumes the realized
`torch.optim.Optimizer`, an exact deduplicated name-to-`Parameter` binding, and
the gradients currently stored on those parameters. Every optimizer slot must
be named exactly once, every captured gradient must be a tensor, parameter
storage must equal the declared treatment dtype, and every realized parameter
group option is closed and receipted. Existing optimizer state and counters are
cloned into every branch; group-option drift and pre-step state/dtype-mapping
drift are `PREFLIGHT_INVALID_REFERENCE`.

The current live adapters are exact PyTorch SGD, AdamW, and Adafactor classes.
Unknown subclasses, repository-historical Muon implementations, and
`bitsandbytes.AdamW8bit` fail closed. Adding an optimizer is a new adapter with
its own exact-class/source binding and causal-twin fixtures; family names or
lookalike update equations do not authorize reuse.

## Current integration boundary

This v1 library and CPU selftest do not yet authorize a BF16 production launch.
The active governed 3B path uses GPU-only `bitsandbytes.AdamW8bit`, and the
historical #702/FACTOR-1/BitNet runners are not modified or re-enabled by this
increment. Issue #718 therefore remains open until validated Muon and
AdamW8bit adapters exist, the named consumer paths bind and verify a PASS
receipt before launch, and real captured-gradient integration receipts are
reviewed. A synthetic selftest PASS is never a launch receipt.
## Gradient-causal measurement

For every sampled step count, four fresh branches start from identical parameter
and optimizer state:

1. treatment storage with the actual gradient;
2. treatment storage with an explicit zero tensor gradient;
3. algorithm-identical FP32 reference with the actual gradient;
4. algorithm-identical FP32 reference with an explicit zero tensor gradient.

`actual - zero` is the gradient-causal delta. `zero - before` is reported
separately as decay contribution. `grad=None` is forbidden as a zero twin.
The receipt reports per-class causal/total changed fractions, causal and decay
RMS, FP32 algorithmic causal RMS, the FP32 result cast to treatment storage,
realized/reference RMS ratio, cosine, optimizer-state dtypes, frozen required
tensors, and failed class floors. Every requested multi-step sample is a fresh
fork; branch state never contaminates a later comparison.

## Verdict and receipt

The closed top-level schema is `ember-update-survival-preflight/v1`.

- `PREFLIGHT_PASS`: every class floor and required tensor survives every sampled
  step count.
- `PREFLIGHT_FAIL`: measurements are valid, but at least one floor or required
  tensor fails.
- `PREFLIGHT_INVALID`: inputs or the algorithm-identical reference cannot be
  established. `invalid_code` distinguishes `PREFLIGHT_INVALID_INPUT` from
  `PREFLIGHT_INVALID_REFERENCE`.

The path-free receipt binds the optimizer implementation source SHA-256, explicit
optimizer configuration, optimizer-state projection, gradient-source projection,
treatment dtype, measurements, and canonical receipt SHA-256. Non-finite values,
missing gradients, duplicate names, incomplete class floors, unvalidated
optimizer families, implicit dtype-dependent defaults, or unclonable optimizer
state fail closed.

## Mandatory CPU selftest

`python -B scripts/preflight/update_survival.py --selftest --receipt <path>`
must prove:

1. AdamW `param=1, lr=.01, wd=1, grad=1e-12` has a perfect-looking total delta
   but zero gradient-causal BF16 survival and therefore fails;
2. a 24-tensor BitNet-shaped BF16 fixture changes exactly 15 tensors and freezes
   all nine required norm/scale tensors;
3. the same fixture with FP32 master storage passes;
4. Adafactor with implicit dtype-dependent `eps1` is invalid.

This gate proves update-storage survival only. It does not prove loss improvement,
training sufficiency, optimizer superiority, model capability, or any milestone.
