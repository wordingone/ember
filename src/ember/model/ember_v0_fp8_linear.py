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

Against a 330.4 ms step that leaves 202.6 ms, or 20,217 tok/s at 4,096 tokens per step. Measured
realization at the governed precision configuration is 120.1 ms of that 127.766 ms, or 94%. It is the
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

import atexit
import collections
import json
import os

import torch
import torch.nn.functional as F

E4M3_MAX = 448.0

#: Smallest amax we will divide by. Below this the tensor is all-but-zero and the scale would be
#: enormous; falling back keeps a degenerate batch from producing infinities in a training step.
_MIN_AMAX = 1e-12

#: One counter per exit of :func:`linear`, so that "the arm was selected" and "the arm ran" are
#: separately observable. They are not the same claim, and treating them as one is how an inert
#: treatment gets published as a gain. Incremented by whichever thread executes the forward, under
#: the interpreter's own lock; the counts are a diagnostic and never a control input, so a torn
#: read costs nothing.
_DISPATCH_COUNTS = {
    "fp8": 0,
    "not_selected": 0,
    "unsupported_device": 0,
    "full_precision": 0,
}


def dispatch_counts() -> dict[str, int]:
    """A snapshot of the per-exit counts. A copy, so a caller cannot mutate the live tally."""
    return dict(_DISPATCH_COUNTS)


def reset_dispatch_counts() -> None:
    """Zero every counter, so a measurement window starts from a known state.

    A run that reports counts without resetting first is reporting the process's whole history, and
    a warmup's dispatches would be indistinguishable from the measured region's.
    """
    for key in _DISPATCH_COUNTS:
        _DISPATCH_COUNTS[key] = 0

def _write_dispatch_receipt() -> None:
    # The counters above are correct and, until this function existed, unreachable: nothing in the
    # repository read dispatch_counts(), so every fp8 arm was scored on a configuration field that
    # records what was REQUESTED. A governed run therefore could not distinguish a treatment that
    # ran from one that was merely selected -- which is the defect the block above is written
    # against, reproduced one layer out by having no consumer.
    #
    # MERGE, never overwrite. EMBER_FP8_RECEIPT is exported by the dispatching shell and is
    # inherited by every descendant, so a process that imports this module and does no work can
    # reach the same path and clobber a real tally with its own zeros. Taking the per-key maximum
    # makes write ORDER irrelevant; the custody is fresh per run, so there are no stale counts.
    path = os.environ.get("EMBER_FP8_RECEIPT")
    if not path:
        return
    counts = dict(_DISPATCH_COUNTS)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            prior = json.load(handle).get("counts", {})
        for key, value in prior.items():
            if isinstance(value, int) and value > counts.get(key, 0):
                counts[key] = value
    except (OSError, ValueError):
        pass
    payload = {
        "schema": "ember-1945-fp8-dispatch-counts-v1",
        "claim_boundary": "asserts which exits of linear() EXECUTED in this process; licenses no duration and no learning result",
        "counts": counts,
        "pid": os.getpid(),
        "enabled_requested": os.environ.get("EMBER_FP8_LINEAR"),
        "delayed_scale_requested": os.environ.get("EMBER_FP8_DELAYED_SCALE"),
    }
    try:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=1, sort_keys=True)
    except OSError:
        pass


atexit.register(_write_dispatch_receipt)



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
#: writing down because it is what identified the last remaining cost. The three materialized
#: transposes in the backward had been sized as copies -- a few milliseconds -- and dismissed. Under
#: the corrected model they are full passes too, so they were measured instead: 81.0 ms/step at the
#: model's real routed shapes, against 81.5 ms of ceiling the arm had not collected. They were not
#: part of the remaining gap; they were essentially all of it. Removing them recovered 85.2 ms and
#: took the realized saving to 120.1 ms of the 127.766 ms ceiling. See ``_quantize_pair_eager``.
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


def _quantize_pair_eager(tensor: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """Quantize, and write the transposed copy from the same scaled tensor.

    The backward needs both layouts of every quantized activation and gradient: one operand of each
    of its two GEMMs is the transpose of a tensor the other GEMM uses row-major. Materializing that
    transpose afterwards reads the fp8 result and writes a second fp8 tensor -- a full extra pass
    over each tensor, at every routed site, every step. Producing it here instead means both writes
    come off ``scaled``, which the cast is already reading, so the separate read disappears.

    That this is worth doing at all was measured rather than reasoned. Sized by an isolated-shape
    probe at the model's real routed shapes, the three materialized transposes cost 81.0 ms/step
    against 81.5 ms of ceiling that the arm had not yet collected -- so they were not part of the
    remaining gap, they were essentially all of it.
    """
    amax = tensor.detach().abs().amax().float().clamp_min(_MIN_AMAX)
    scale = E4M3_MAX / amax
    factor = scale.to(tensor.dtype) if tensor.dtype in (torch.bfloat16, torch.float16) else scale
    scaled = (tensor * factor).clamp(-E4M3_MAX, E4M3_MAX)
    quantized = scaled.to(torch.float8_e4m3fn)
    transposed = scaled.t().contiguous().to(torch.float8_e4m3fn)
    return quantized, transposed, (1.0 / scale).to(torch.float32)


_COMPILED_QUANTIZE_PAIR = torch.compile(_quantize_pair_eager, dynamic=True)
_COMPILE_PAIR_TRUSTED = True


def _quantize_pair(tensor: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """``_quantize_pair_eager`` through the compiled path, falling back permanently if it refuses."""
    global _COMPILE_PAIR_TRUSTED
    if _COMPILE_PAIR_TRUSTED:
        try:
            return _COMPILED_QUANTIZE_PAIR(tensor)
        except Exception:
            _COMPILE_PAIR_TRUSTED = False
    return _quantize_pair_eager(tensor)


# --- delayed scaling ---------------------------------------------------------------------
#
# Ported from the same module at head 59ae9bb5, where it was implemented and then lost when the
# document-reduction refactor rewrote this file. Single-tensor form: the CIA chokepoint keeps its
# weight gradient in bf16, so there is no transposed cast to build here.
#
# The scale stops being a function of THIS tensor and becomes a resident scalar that a few early
# calls establish and every later call reuses. That is a DECLARED NUMERICAL TREATMENT on top of the
# format change: a tensor whose values later exceed the calibrated range is CLAMPED at e4m3's 448
# rather than rescaled, losing magnitude rather than producing infinities, and one far below it
# loses mantissa. This measures DURATION and licenses nothing.
#
# Why it is worth porting, from today's captured pair rather than from an isolated probe: the amax
# is TWO of the three kernels Inductor emits per quantize, and inside the governed captured step
# they cost 4,334.0 us per trace half-step against 3,414.6 for the cast that survives. Removing the
# reduction removes a full pass over every quantized tensor, not merely two launches.
#
# CAPTURE. The factor and dequant tensors are allocated once and written IN PLACE, so the tensor a
# captured graph recorded is the tensor a later calibration would update -- there is no second
# allocation for a replay to miss. Calibration must FINISH before capture or the graph records the
# calibrating branch, amax and all, for the life of the replay; the probe runs three warm steps
# before capture, so EMBER_FP8_CALIBRATION_CALLS=1 is sufficient and is the default here.


def delayed_scaling_enabled() -> bool:
    # Read per call, for the reason `fp8_enabled` is: the governed runner sets its environment
    # after this module is imported, and a module-level constant makes the treatment inert inside
    # the very path it is meant to measure.
    return os.environ.get("EMBER_FP8_DELAYED_SCALE") == "1"


def _calibration_calls() -> int:
    try:
        return max(1, int(os.environ.get("EMBER_FP8_CALIBRATION_CALLS", "1")))
    except ValueError:
        return 1


#: Per site and role: [calls seen, running amax, multiply factor in the tensor dtype, dequant fp32].
_SCALE_STATE: dict = {}


def _resident_factors(tensor, key):
    """The multiply factor and dequant scale for this site, calibrating only on the first calls."""
    state = _SCALE_STATE.get(key)
    if state is None:
        state = [0, None, torch.ones((), device=tensor.device, dtype=tensor.dtype),
                 torch.ones((), device=tensor.device, dtype=torch.float32)]
        _SCALE_STATE[key] = state
    if state[0] < _calibration_calls():
        # The running max ACROSS calibration calls, not the last one, so a single quiet batch
        # cannot set a scale that later batches overflow.
        amax = tensor.detach().abs().amax().float().clamp_min(_MIN_AMAX)
        state[1] = amax if state[1] is None else torch.maximum(state[1], amax)
        scale = E4M3_MAX / state[1]
        state[2].copy_(scale.to(tensor.dtype))
        state[3].copy_((1.0 / scale).to(torch.float32))
        state[0] += 1
        _DISPATCH_COUNTS["quantize_calibrating"] = _DISPATCH_COUNTS.get("quantize_calibrating", 0) + 1
    else:
        _DISPATCH_COUNTS["quantize_resident"] = _DISPATCH_COUNTS.get("quantize_resident", 0) + 1
    return state[2], state[3]


def _quantize_resident_eager(tensor, factor):
    """The quantize with no reduction in it at all: multiply, clamp, cast."""
    return (tensor * factor).clamp(-E4M3_MAX, E4M3_MAX).to(torch.float8_e4m3fn)


_COMPILED_QUANTIZE_RESIDENT = torch.compile(_quantize_resident_eager, dynamic=True)
_COMPILE_RESIDENT_TRUSTED = True


def _quantize_delayed(tensor, key):
    """`_quantize`'s return, with the amax reduction removed after calibration."""
    global _COMPILE_RESIDENT_TRUSTED
    factor, dequant = _resident_factors(tensor, key)
    if _COMPILE_RESIDENT_TRUSTED:
        try:
            return _COMPILED_QUANTIZE_RESIDENT(tensor, factor), dequant
        except Exception:
            _COMPILE_RESIDENT_TRUSTED = False
    return _quantize_resident_eager(tensor, factor), dequant


#: Activations quantized this step, keyed by the input tensor's identity.
#:
#: Several projections consume ONE activation: the shared SwiGLU up and gate both read the block
#: input, and q, k and v all read the attention input. Under a per-site key each of them quantized
#: the same bytes again, which is why the delayed-scale arm still pays 241 casts per step for far
#: fewer distinct tensors.
#:
#: The entry holds a STRONG reference to the source tensor. That is not an accident: CPython
#: recycles ``id`` the moment an object is freed, so a cache keyed on ``id`` alone can hand a new
#: tensor the previous occupant's bytes. Holding the source keeps the id reserved for as long as
#: the entry lives, and the ``is`` check below then cannot be satisfied by an impostor. The
#: ``_version`` check catches an in-place write to a tensor we are still holding.
#:
#: The cache is small and FIFO. The sites that share a tensor are adjacent calls, so a few entries
#: catch all of them, and a short cache is what keeps the strong references from pinning a
#: meaningful amount of activation memory.
_ACT_CACHE: "collections.OrderedDict[int, tuple]" = collections.OrderedDict()
_ACT_CACHE_MAX = 4


def quantize_activation(tensor, key):
    """`quantize_for`, deduplicated across the sites that consume one activation."""
    ident = id(tensor)
    entry = _ACT_CACHE.get(ident)
    if entry is not None and entry[0] is tensor and entry[1] == tensor._version:
        _DISPATCH_COUNTS["quantize_act_reused"] = _DISPATCH_COUNTS.get("quantize_act_reused", 0) + 1
        return entry[2], entry[3]
    quantized, dequant = quantize_for(tensor, key)
    _ACT_CACHE[ident] = (tensor, tensor._version, quantized, dequant)
    _ACT_CACHE.move_to_end(ident)
    while len(_ACT_CACHE) > _ACT_CACHE_MAX:
        _ACT_CACHE.popitem(last=False)
    return quantized, dequant


def clear_activation_cache() -> None:
    """Drop every cached activation, releasing the strong references it holds."""
    _ACT_CACHE.clear()


def quantize_for(tensor, key):
    """One entry point, so the forward and backward legs cannot disagree about the policy."""
    if delayed_scaling_enabled():
        return _quantize_delayed(tensor, key)
    _DISPATCH_COUNTS["quantize_dynamic"] = _DISPATCH_COUNTS.get("quantize_dynamic", 0) + 1
    return _quantize(tensor)


def clear_scale_state() -> None:
    """Drop every resident scale. For teardown and for tests that rebuild a model in place."""
    _SCALE_STATE.clear()
    clear_activation_cache()


#: Quantized weights, keyed by the parameter's identity and its version counter.
#:
#: A weight changes only when the optimizer writes it, and an in-place write bumps ``_version``. So
#: the counter is an exact key: a hit means these bytes are the bytes this entry was built from, and
#: an optimizer step invalidates every entry it touched without anyone having to remember to. This
#: is the difference between quantizing most of the model once per optimizer step and quantizing it
#: once per projection call, and the second one costs more than the GEMMs it was meant to accelerate.
#:
#: The entry carries both layouts. The backward's grad_activation GEMM needs the weight column-major
#: and no copy-free view of a row-major (out, in) tensor has that layout, so a transpose has to be
#: materialized somewhere. Building it here makes it once per optimizer step instead of once per
#: projection call, which at 14 to 28 calls per site per step is the whole of its 23 ms cost.
_WEIGHT_CACHE: dict[int, tuple[int, torch.Tensor, torch.Tensor, torch.Tensor]] = {}


def _quantize_weight(weight: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """``_quantize`` for a parameter, memoized on (identity, version), in both layouts."""
    key = id(weight)
    version = weight._version
    cached = _WEIGHT_CACHE.get(key)
    if cached is not None and cached[0] == version:
        return cached[1], cached[2], cached[3]
    quantized, dequant_scale = _quantize(weight)
    column_major = quantized.t().contiguous().t()
    _WEIGHT_CACHE[key] = (version, quantized, column_major, dequant_scale)
    return quantized, column_major, dequant_scale


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

        flat8, flat8_transposed, flat_scale = _quantize_pair(flat)
        weight8, weight8_column_major, weight_scale = _quantize_weight(weight)

        # ``weight`` is (out, in) and contiguous, so ``weight8.t()`` is (in, out) column-major --
        # exactly the layout the scaled GEMM wants, obtained without a copy.
        output = _scaled_matmul(flat8, flat_scale, weight8.t(), weight_scale, activation.dtype)

        # Only the transposed activation is saved: the row-major form has no backward consumer, so
        # keeping it would cost residency for nothing.
        ctx.save_for_backward(flat8_transposed, flat_scale, weight8_column_major, weight_scale)
        ctx.original_shape = original_shape
        ctx.activation_dtype = activation.dtype
        ctx.weight_dtype = weight.dtype
        return output.reshape(*original_shape[:-1], weight.shape[0])

    @staticmethod
    @torch.amp.custom_bwd(device_type="cuda")
    def backward(ctx, grad_output: torch.Tensor):
        flat8_transposed, flat_scale, weight8_column_major, weight_scale = ctx.saved_tensors
        grad_flat = grad_output.reshape(-1, grad_output.shape[-1])
        grad8, grad8_transposed, grad_scale = _quantize_pair(grad_flat)

        # grad_activation = grad_output @ W, needing W as (out, in) column-major. That form comes
        # from the weight cache, built once per optimizer step rather than once per call here.
        grad_activation = _scaled_matmul(
            grad8, grad_scale, weight8_column_major, weight_scale, ctx.activation_dtype
        )

        # grad_weight = grad_output^T @ x, which is (out, tokens) @ (tokens, in). ``grad8_transposed``
        # is (out, tokens) row-major and ``flat8_transposed`` is (in, tokens) row-major, so its
        # ``.t()`` is the (tokens, in) column-major operand the scaled GEMM wants -- a view, not a
        # copy. Both operands therefore arrive already in the layout this GEMM needs.
        #
        # The right operand being ``x`` and not its transpose was a shape error once, and it only
        # surfaced at the widest site where (32000, 4096) met (2048, 4096); the narrower sites would
        # have multiplied wrong shapes silently had they happened to be square.
        grad_weight = _scaled_matmul(
            grad8_transposed,
            grad_scale,
            flat8_transposed.t(),
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
    if not fp8_enabled():
        _DISPATCH_COUNTS["not_selected"] += 1
        return F.linear(activation, weight)
    if not fp8_supported(activation):
        _DISPATCH_COUNTS["unsupported_device"] += 1
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
        _DISPATCH_COUNTS["full_precision"] += 1
        return F.linear(activation, weight)
    _DISPATCH_COUNTS["fp8"] += 1
    return _Fp8Linear.apply(activation, weight)
