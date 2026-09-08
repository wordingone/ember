# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Per-tensor e4m3 GEMM for the decoder's linear projections (issue #1945).

Why this exists, and what it deliberately does not change.

The learning contract is untouched: which examples are applied at step N, which experts route, the
optimizer state, the RNG and data cursor, and the observable step boundary all behave exactly as
before. What changes is the arithmetic the projection GEMMs are executed in. That distinction is the
governing law for this campaign -- the contract is preserved, the implementation underneath it is
replaceable.

Sizing, measured before this file was written, at the model's real executed shapes with the backward
counted as its true two additional GEMMs:

    bf16 GEMMs   271.303 ms/step
    e4m3 GEMMs   143.537 ms/step
    ceiling      127.766 ms/step

Against a 330.4 ms step that leaves 202.6 ms, or 20,217 tok/s at 4,096 tokens per step. It is the
first treatment in this campaign whose ceiling contains the terminal: the captured-step lane acted on
33.1 ms of launch overhead, and the earlier per-site lane acted on a forward that is 21.6% of the
step. This one acts on 82% of it.

Numerics. e4m3 carries three mantissa bits, so the maximum relative step is 2^-4 and the measured
representation error is flat at 3.77e-02 across dynamic ranges from 7.5 to 96. Flat across range is
what identifies it as format resolution rather than scale selection, and it is why the scaling policy
here is per-tensor: per-row/column scaling was measured at 1.00x against it and buys nothing for the
cost of a reduction per row. A paired loss comparison over 60 steps -- both arms from bit-identical
weights, the same batch in the same order, the same optimizer and seed, with the backward quantized
too because a forward-only emulation understates the error -- put the achieved loss floor at 0.001318
for bf16 against 0.001604 for e4m3, a ratio of 1.22x with both arms descending on the same
trajectory. That refutes harm cheaply; it does not establish the loss bar, which is a governed run's
job.

This path is OPT-IN. Changing the arithmetic of every CUDA run by default would be a contract change
made by a probe rather than by the governed run that is entitled to make it.
"""
from __future__ import annotations

import os

import torch
import torch.nn.functional as F

E4M3_MAX = 448.0

#: Smallest amax we will divide by. Below this the tensor is all-but-zero and the scale would be
#: enormous; falling back keeps a degenerate batch from producing infinities in a training step.
_MIN_AMAX = 1e-12


def fp8_enabled() -> bool:
    """Whether the e4m3 projection path is selected for this process.

    Opt-in by environment so a governed arm turns it on explicitly and every other run -- tests,
    evaluation, recovery, the control side of any comparison -- keeps the arithmetic it was
    certified with.
    """
    return os.environ.get("EMBER_FP8_LINEAR", "").strip().lower() in {"1", "true", "on"}


def fp8_supported(tensor: torch.Tensor) -> bool:
    """Whether this device can execute the scaled GEMM at all.

    e4m3 ``_scaled_mm`` needs sm89 or newer. On anything else the answer is no, and the caller runs
    the ordinary path rather than emulating -- an emulation would carry the format's error with none
    of its speed, which is the worst of both.
    """
    if tensor.device.type != "cuda" or not hasattr(torch, "_scaled_mm"):
        return False
    return torch.cuda.get_device_capability(tensor.device) >= (8, 9)


def _quantize_eager(tensor: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
    """The whole quantization -- reduction, scale, clamp, rounding cast -- as one function.

    Written as one function so it can be compiled as one region. Splitting the reduction out and
    compiling only the elementwise tail leaves the reduction reading the entire tensor on its own,
    and then the cast reads it again.
    """
    amax = tensor.detach().abs().amax().float().clamp_min(_MIN_AMAX)
    scale = E4M3_MAX / amax
    factor = scale.to(tensor.dtype) if tensor.dtype in (torch.bfloat16, torch.float16) else scale
    quantized = (tensor * factor).clamp(-E4M3_MAX, E4M3_MAX).to(torch.float8_e4m3fn)
    return quantized, (1.0 / scale).to(torch.float32)


#: Compiled form of the whole quantization, and whether it is still trusted.
#:
#: Fusing matters here for a reason particular to this model. The step is dominated by fixed
#: per-call dispatch -- 66.8% of it by the campaign's own attribution -- and this path adds kernels
#: at each of roughly 120 routed sites, twice per site per step. Against a GEMM saving of 127.8 ms
#: that the unfused arm was measured spending in full, collapsing those kernels is where the saving
#: is recovered, and it has been recovered in two measured steps: 36 ms from fusing the scale, clamp
#: and cast, then a further 40.7 ms from pulling the amax reduction into the same region.
#:
#: That second number was PREDICTED at 15 to 20 ms and came in at double. The prediction was built
#: on launch count alone -- the amax removes about one kernel per tensor against the previous
#: change's two -- and launch count turned out to be only part of what was being paid. An amax is a
#: reduction over the whole tensor, so as a separate kernel it reads every byte and the cast then
#: reads every byte again. Fusing removes an entire pass over each quantized tensor, not merely a
#: launch. The corrected model of the remaining gap is dispatch AND redundant passes, which is worth
#: writing down because it changes what the last named successor is worth: the three materialized
#: transposes in the backward are also full passes, and were sized as copies alone.
_COMPILED_QUANTIZE = torch.compile(_quantize_eager, dynamic=True)
_COMPILE_TRUSTED = True


def _quantize(tensor: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
    """``_quantize_eager`` through the compiled path, falling back permanently if it refuses.

    A compile failure must not take the training step with it, and it must not be retried once per
    call either -- a path that raises and recovers at every projection would cost far more than the
    fusion saves. One failure disables the compiled form for the life of the process.

    The returned scale is what ``_scaled_mm`` multiplies back in, so it is the reciprocal of the
    factor applied inside.
    """
    global _COMPILE_TRUSTED
    if _COMPILE_TRUSTED:
        try:
            return _COMPILED_QUANTIZE(tensor)
        except Exception:
            _COMPILE_TRUSTED = False
    return _quantize_eager(tensor)


#: Quantized weights, keyed by the parameter's identity and its version counter.
#:
#: A weight changes only when the optimizer writes it, and an in-place write bumps ``_version``. So
#: the counter is an exact key: a hit means these bytes are the bytes this entry was built from, and
#: an optimizer step invalidates every entry it touched without anyone having to remember to. This
#: is the difference between quantizing most of the model once per optimizer step and quantizing it
#: once per projection call, and the second one costs more than the GEMMs it was meant to accelerate.
_WEIGHT_CACHE: dict[int, tuple[int, torch.Tensor, torch.Tensor]] = {}


def _quantize_weight(weight: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
    """``_quantize`` for a parameter, memoized on (identity, version)."""
    key = id(weight)
    version = weight._version
    cached = _WEIGHT_CACHE.get(key)
    if cached is not None and cached[0] == version:
        return cached[1], cached[2]
    quantized, dequant_scale = _quantize(weight)
    _WEIGHT_CACHE[key] = (version, quantized, dequant_scale)
    return quantized, dequant_scale


def clear_weight_cache() -> None:
    """Drop every memoized weight. For teardown and for tests that rebuild a model in place."""
    _WEIGHT_CACHE.clear()


def _scaled_matmul(
    left: torch.Tensor,
    left_scale: torch.Tensor,
    right: torch.Tensor,
    right_scale: torch.Tensor,
    out_dtype: torch.dtype,
) -> torch.Tensor:
    """``left @ right`` in e4m3, where ``right`` must already be column-major.

    ``_scaled_mm`` requires the second operand in column-major layout. Callers arrange that by
    transposing a contiguous tensor wherever a copy-free view exists, because a transpose-copy per
    GEMM spends part of the very saving this path exists to collect.
    """
    return torch._scaled_mm(
        left, right, scale_a=left_scale, scale_b=right_scale, out_dtype=out_dtype
    )


class _Fp8Linear(torch.autograd.Function):
    """``y = x @ W^T`` with all three GEMMs executed in e4m3.

    The backward's two GEMMs are quantized as well. A forward-only treatment would report a smaller
    numerical error than the shipped path actually produces, and understating error is the wrong
    direction for a change whose safety argument rests on that error being small.

    ``custom_fwd`` with ``cast_inputs`` is load-bearing and was added after a measurement caught its
    absence. The governed training path runs inside ``torch.autocast(dtype=bfloat16)``, which casts
    inputs for the ops it knows about -- and a custom autograd Function is not one of those. Without
    this decorator the activation arrives here in fp32, the dtype guard below sends it straight back
    to ``F.linear``, and the arm silently does nothing while appearing to be enabled. The symptom was
    a treatment loss bit-identical to the reference, which is impossible for a real format change
    and is the only reason the defect was noticed at all.
    """

    @staticmethod
    @torch.amp.custom_fwd(device_type="cuda", cast_inputs=torch.bfloat16)
    def forward(ctx, activation: torch.Tensor, weight: torch.Tensor) -> torch.Tensor:
        original_shape = activation.shape
        flat = activation.reshape(-1, original_shape[-1])

        flat8, flat_scale = _quantize(flat)
        weight8, weight_scale = _quantize_weight(weight)

        # ``weight`` is (out, in) and contiguous, so ``weight8.t()`` is (in, out) column-major --
        # exactly the layout the scaled GEMM wants, obtained without a copy.
        output = _scaled_matmul(flat8, flat_scale, weight8.t(), weight_scale, activation.dtype)

        ctx.save_for_backward(flat8, flat_scale, weight8, weight_scale)
        ctx.original_shape = original_shape
        ctx.activation_dtype = activation.dtype
        ctx.weight_dtype = weight.dtype
        return output.reshape(*original_shape[:-1], weight.shape[0])

    @staticmethod
    @torch.amp.custom_bwd(device_type="cuda")
    def backward(ctx, grad_output: torch.Tensor):
        flat8, flat_scale, weight8, weight_scale = ctx.saved_tensors
        grad_flat = grad_output.reshape(-1, grad_output.shape[-1])
        grad8, grad_scale = _quantize(grad_flat)

        # grad_activation = grad_output @ W, needing W as (out, in) in column-major layout.
        # ``weight8`` is (out, in) row-major and no copy-free view of it has that layout, so this
        # one transpose is materialized. It is the unavoidable copy on this path, and it is why the
        # realized saving will land below the isolated-GEMM ceiling quoted above.
        weight_column_major = weight8.t().contiguous().t()
        grad_activation = _scaled_matmul(
            grad8, grad_scale, weight_column_major, weight_scale, ctx.activation_dtype
        )

        # grad_weight = grad_output^T @ x, which is (out, tokens) @ (tokens, in). The second
        # operand is therefore ``flat8`` itself and not its transpose -- writing ``flat8.t()`` here
        # was a shape error that only surfaced at the widest site, where (32000, 4096) met
        # (2048, 4096) and the mismatch became impossible to miss. The narrower sites would have
        # multiplied wrong shapes silently if they had happened to be square.
        #
        # Both backward operands need a materialized transpose: the left because ``grad8`` is
        # (tokens, out) row-major, the right because ``flat8`` is (tokens, in) row-major and the
        # scaled GEMM wants column-major. Two copies per site per step is the honest cost of this
        # path today, and it is the main reason the realized saving will sit below the
        # isolated-GEMM ceiling. Saving the activation in both layouts at forward time would trade
        # them for fp8 memory equal to one bf16 copy; that is the next optimization, not this one.
        grad_weight = _scaled_matmul(
            grad8.t().contiguous(),
            grad_scale,
            flat8.t().contiguous().t(),
            flat_scale,
            ctx.weight_dtype,
        )

        return grad_activation.reshape(ctx.original_shape), grad_weight


def linear(activation: torch.Tensor, weight: torch.Tensor) -> torch.Tensor:
    """The projection GEMM: e4m3 when selected and supported, otherwise exactly ``F.linear``.

    Every refusal falls back rather than raising. A device that cannot execute the scaled GEMM, a
    process that did not opt in, or a dtype this path does not cover all produce the same numbers
    the model produced before this file existed.
    """
    if not fp8_enabled() or not fp8_supported(activation):
        return F.linear(activation, weight)
    # Under autocast the activation is still fp32 here -- ``custom_fwd`` casts it on the way in --
    # so this guard asks whether the arithmetic will be reduced precision, which is true if the
    # tensor is already half or if autocast is about to make it so. Testing the incoming dtype
    # alone was the defect that made the arm inert inside the governed path.
    reduced_precision = activation.dtype in (torch.bfloat16, torch.float16) or (
        torch.is_autocast_enabled("cuda")
        and torch.get_autocast_dtype("cuda") in (torch.bfloat16, torch.float16)
    )
    if not reduced_precision:
        return F.linear(activation, weight)
    return _Fp8Linear.apply(activation, weight)
