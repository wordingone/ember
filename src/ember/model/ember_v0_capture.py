# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Segmented CUDA-graph capture of the resident CIA step (#1945, G1).

The resident decoder forward is a fixed sequence of 13 segments (accepted carry contract, 2026-09-11): S0 takes
(embedded, positions) and returns a ten-slot carry; S1..S11 take and return the same ten slots with slot 1 holding the
normed expert input; the decoder's eager grouped expert block runs BETWEEN segments and replaces slot 1 with the expert
residual (its shapes depend on the step's winners, so it is the one region that stays eager); S12 returns
(logits, ranked, winner_history). The decoder never computes a loss: the runner owns it, either as a captured tail
segment or as an eager callback on the logits.

`SegmentedStep` owns the capture. Every segment is graphed forward AND backward through torch.cuda.make_graphed_callables
against sample inputs RECORDED from one real eager step (the exemplar), so an ordinary loss.backward() flows from the
runner's loss through the graphed S12, the eager grouped blocks, and the graphed S11..S0 into the owner parameters'
`.grad`. Grad mode 'static-accumulate': owner grads keep their storage across steps (`zero_grad(set_to_none=False)`),
so accumulation is in place and the replayed backward allocates nothing.

Refusal, never fallback: a later call whose inputs differ from the exemplar in shape, dtype, device or grad role refuses
before touching the graphs; a segment recorded under one geometry is invalidated by `bind_geometry`; the capture's own
warm-up replays are proven to leave parameters, optimizer state and the RNG exactly as they were and to leave every
owner grad zero. On a non-CUDA device the same object runs the segments eagerly with the same validation, which is what
the CPU tests exercise; the graphs themselves are exercised only on CUDA.

Caller requirements proven by the CUDA fixture (2026-09-11): every `static_state` tensor and every carry slot lives on
the capture device (a host tensor touched inside a segment invalidates the stream capture); the exemplar step's autograd
graph is released (its outputs and loss dropped) before `capture()`, since a live AccumulateGrad node bound to the
default stream breaks the side-stream capture; the execution's `capture_region()` is entered for the synthetic calls.
"""
import contextlib
import dataclasses
import hashlib

import torch

GRAD_MODES = ("static-accumulate",)
ROLE_OWNER = "owner-param"
ROLE_CARRY_GRAD = "carry-requires-grad"
ROLE_CARRY_STATIC = "carry-static"


class ExemplarMismatch(RuntimeError):
    """A segment was run with inputs that differ from its recorded exemplar."""


class CaptureStateError(RuntimeError):
    """The capture's warm-up would have changed state that must survive it, or the object is misused."""


@dataclasses.dataclass(frozen=True)
class SegmentSpec:
    """One captured segment: `fn(*carry_in) -> tuple(carry_out)`; `params` are the owner parameters whose gradients
    this segment produces; `static_state` are tensors fn reads without carrying (fixed under one geometry)."""
    index: int
    fn: object
    params: tuple = ()
    static_state: tuple = ()
    name: str = ""

    def __post_init__(self):
        if type(self.index) is not int or self.index < 0:
            raise ValueError("segment index must be a non-negative int")
        if not callable(self.fn):
            raise ValueError("segment fn must be callable")
        for parameter in self.params:
            if not isinstance(parameter, torch.nn.Parameter):
                raise ValueError("segment params must be nn.Parameters")


@dataclasses.dataclass(frozen=True)
class TensorSignature:
    shape: tuple
    dtype: torch.dtype
    device: str
    role: str

    @staticmethod
    def of(value, *, owner=False):
        if not isinstance(value, torch.Tensor):
            raise ExemplarMismatch("carry slots must be tensors, got " + type(value).__name__)
        role = ROLE_OWNER if owner else (ROLE_CARRY_GRAD if value.requires_grad else ROLE_CARRY_STATIC)
        return TensorSignature(tuple(value.shape), value.dtype, value.device.type, role)


@dataclasses.dataclass
class _Recorded:
    inputs: tuple            # detached clones of the exemplar inputs (requires_grad preserved)
    signature: tuple         # TensorSignature per input
    outputs: tuple           # TensorSignature per output


def _digest(tensors):
    digest = hashlib.sha256()
    for value in tensors:
        digest.update(str((tuple(value.shape), str(value.dtype))).encode())
        host = value.detach().to("cpu", copy=True).contiguous().reshape(-1)
        digest.update((host if host.dtype == torch.bool else host.view(torch.uint8)).numpy().tobytes())
    return digest.hexdigest()


class _SegmentModule(torch.nn.Module):
    """Presents one segment to make_graphed_callables as a Module whose parameters are the EXACT owner Parameter
    objects (registered, not copied), so the graphed backward's static input surface includes them and the captured
    owner gradients land in the owners' `.grad`. A plain function has no parameter surface there (torch.cuda.graphs
    per_callable_module_params = () for non-Modules) and its owner grads would silently vanish under capture."""

    def __init__(self, segment):
        super().__init__()
        self.segment = segment
        for position, parameter in enumerate(segment.params):
            self.register_parameter("owner_%d" % position, parameter)

    def forward(self, *carry_in):
        return self.segment.fn(*carry_in)


class SegmentedStep:
    def __init__(self, segments, *, device, warmup_steps=2, grad_mode="static-accumulate"):
        segments = tuple(segments)
        if [segment.index for segment in segments] != list(range(len(segments))) or not segments:
            raise ValueError("segments must be SegmentSpec 0..N-1 in order")
        if grad_mode not in GRAD_MODES:
            raise ValueError("unknown grad mode " + repr(grad_mode))
        if type(warmup_steps) is not int or warmup_steps < 1:
            raise ValueError("warmup_steps must be a positive int")
        self.segments = segments
        self.device = torch.device(device)
        self.warmup_steps = warmup_steps
        self.grad_mode = grad_mode
        self.execution = None
        self.loss_fn = None
        self._recorded = {}
        self._graphed = None
        self._recording = False
        self.captures = 0
        for value in self.static_state:
            if not isinstance(value, torch.Tensor) or value.requires_grad:
                raise ValueError("static_state entries must be tensors that do not require grad")

    # ---- lifecycle -------------------------------------------------------------------------------------------------
    @property
    def captured(self):
        return self._graphed is not None

    @property
    def params(self):
        seen, out = set(), []
        for segment in self.segments:
            for parameter in segment.params:
                if id(parameter) not in seen:
                    seen.add(id(parameter))
                    out.append(parameter)
        return tuple(out)

    @property
    def static_state(self):
        out = []
        for segment in self.segments:
            for value in segment.static_state:
                if not any(value is seen for seen in out):
                    out.append(value)
        return tuple(out)

    def bind(self, execution, *, loss_fn=None):
        """Bind the resident execution whose geometry the segments close over. Any capture is invalidated."""
        self.execution = execution
        self.loss_fn = loss_fn
        self.invalidate()
        return self

    def invalidate(self):
        self._graphed = None
        self._recorded = {}

    def record(self):
        """Context manager: the next step's `run()` calls execute eagerly and record each segment's exemplar."""
        return _Recording(self)

    # ---- the step ---------------------------------------------------------------------------------------------------
    def run(self, index, *carry_in):
        segment = self.segments[index]
        if self._recording:
            return self._record(segment, carry_in)
        recorded = self._recorded.get(index)
        if recorded is None:
            raise CaptureStateError("segment %d has no exemplar; run one step under record() first" % index)
        self._check(segment, carry_in, recorded)
        if self._graphed is None:
            return self._eager(segment, carry_in)
        return self._restore_output_roles(segment, self._graphed[index](*carry_in), recorded)

    @staticmethod
    def _restore_output_roles(segment, outputs, recorded):
        """The graphed callable is a custom autograd Function: every floating output requires grad when any input does,
        so a slot the exemplar produced carry-static (a frozen-support float carry) must be detached again or the next
        segment refuses it. Only the recorded-static slots are detached; a recorded-grad slot that comes back static is
        a defect of the graph and is refused rather than repaired."""
        if len(outputs) != len(recorded.outputs):
            raise ExemplarMismatch("segment %d produced %d outputs, exemplar produced %d"
                                   % (segment.index, len(outputs), len(recorded.outputs)))
        restored = []
        for slot, (value, expected) in enumerate(zip(outputs, recorded.outputs)):
            if expected.role == ROLE_CARRY_STATIC and value.requires_grad:
                value = value.detach()
            elif expected.role == ROLE_CARRY_GRAD and not value.requires_grad:
                raise ExemplarMismatch("segment %d output %d lost its gradient role under capture" % (segment.index, slot))
            restored.append(value)
        return tuple(restored)

    def _record(self, segment, carry_in):
        signature = tuple(TensorSignature.of(value) for value in carry_in)
        outputs = self._eager(segment, carry_in)
        samples = tuple(value.detach().clone().requires_grad_(value.requires_grad) for value in carry_in)
        self._recorded[segment.index] = _Recorded(samples, signature, tuple(TensorSignature.of(o) for o in outputs))
        return outputs

    @staticmethod
    def _eager(segment, carry_in):
        outputs = segment.fn(*carry_in)
        if not isinstance(outputs, tuple):
            raise ExemplarMismatch("segment %d must return a tuple of tensors" % segment.index)
        return outputs

    @staticmethod
    def _check(segment, carry_in, recorded):
        if len(carry_in) != len(recorded.signature):
            raise ExemplarMismatch("segment %d: %d inputs, exemplar has %d"
                                   % (segment.index, len(carry_in), len(recorded.signature)))
        for slot, (value, expected) in enumerate(zip(carry_in, recorded.signature)):
            actual = TensorSignature.of(value)
            if actual != expected:
                raise ExemplarMismatch("segment %d slot %d: %s differs from exemplar %s"
                                       % (segment.index, slot, actual, expected))

    # ---- capture ----------------------------------------------------------------------------------------------------
    def capture(self, *, optimizer=None):
        """Graph every segment (forward and backward) against the recorded exemplars.

        The warm-up replays inside make_graphed_callables run real forwards and backwards on the sample inputs; this
        method proves they left parameters, optimizer state and the RNG untouched and zeroes the synthetic owner
        grads (in place: static-accumulate keeps the grad storage). On a non-CUDA device the segments stay eager and
        only the state proof runs, so the CPU path exercises the contract without graphs.
        """
        if self.execution is None:
            raise CaptureStateError("bind(execution) before capture()")
        missing = [segment.index for segment in self.segments if segment.index not in self._recorded]
        if missing:
            raise CaptureStateError("segments without an exemplar: %r" % missing)
        params = self.params
        for parameter in params:
            if parameter.grad is None:
                parameter.grad = torch.zeros_like(parameter)
        state = self._snapshot(params, optimizer)
        # The resident execution's checks require an ACTIVE step; the synthetic warm-up/capture calls run inside the
        # execution's scoped capture region (quiescent entry, owner identity bound, step_id/validity/routing metadata
        # preserved and restored on exit, no optimizer or cursor advance). Absent that method (CPU stand-ins), no-op.
        region = getattr(self.execution, "capture_region", None)
        with (region() if callable(region) else contextlib.nullcontext()):
            self._graph(params)
        for parameter in params:
            parameter.grad.zero_()
        self._restore_and_prove(params, optimizer, state)
        self.captures += 1
        return self

    def _graph(self, params):
        if self.device.type == "cuda":
            callables = tuple(_SegmentModule(segment) for segment in self.segments)
            for module, segment in zip(callables, self.segments):
                if tuple(module.parameters()) != tuple(segment.params):
                    raise CaptureStateError("segment %d owner surface mismatch" % segment.index)
            samples = tuple(self._recorded[segment.index].inputs for segment in self.segments)
            graphed = torch.cuda.make_graphed_callables(callables, samples, num_warmup_iters=self.warmup_steps,
                                                        allow_unused_input=True)
            self._graphed = tuple(graphed)
        else:
            for _ in range(self.warmup_steps):  # the same synthetic warm-up, eagerly, so the state proof is real
                for segment in self.segments:
                    outputs = self._eager(segment, self._recorded[segment.index].inputs)
                    leaves = [o for o in outputs if o.requires_grad]
                    if leaves:
                        torch.autograd.backward([o.sum() for o in leaves])
            self._graphed = None

    def _snapshot(self, params, optimizer):
        rng = {"cpu": torch.get_rng_state()}
        if self.device.type == "cuda":
            rng["cuda"] = torch.cuda.get_rng_state(self.device)
        optimizer_digest = None
        if optimizer is not None:
            optimizer_digest = _digest([v for row in optimizer.state.values() for v in row.values()
                                        if isinstance(v, torch.Tensor)])
        return {"params": _digest(params), "rng": rng, "optimizer": optimizer_digest,
                "grad_storage": tuple(p.grad.data_ptr() for p in params),
                "static_state": tuple(value.detach().clone() for value in self.static_state)}

    def _restore_and_prove(self, params, optimizer, state):
        torch.set_rng_state(state["rng"]["cpu"])
        if "cuda" in state["rng"]:
            torch.cuda.set_rng_state(state["rng"]["cuda"], self.device)
        if _digest(params) != state["params"]:
            raise CaptureStateError("capture warm-up changed a parameter")
        if optimizer is not None:
            after = _digest([v for row in optimizer.state.values() for v in row.values() if isinstance(v, torch.Tensor)])
            if after != state["optimizer"]:
                raise CaptureStateError("capture warm-up changed optimizer state")
        with torch.no_grad():  # segments may mutate static state in place (e.g. a validity accumulator); restore it
            for value, saved in zip(self.static_state, state["static_state"]):
                value.copy_(saved)
        if tuple(p.grad.data_ptr() for p in params) != state["grad_storage"]:
            raise CaptureStateError("capture warm-up replaced an owner grad storage (static-accumulate broken)")
        for parameter in params:
            if bool(parameter.grad.count_nonzero()):
                raise CaptureStateError("owner grad not zero after capture")

    # ---- runner helpers ---------------------------------------------------------------------------------------------
    def zero_grad(self):
        """Static-accumulate: zero in place, never set_to_none, so the captured backward keeps its grad storage."""
        for parameter in self.params:
            if parameter.grad is not None:
                parameter.grad.zero_()

    def loss(self, logits, targets):
        if self.loss_fn is None:
            raise CaptureStateError("no loss_fn bound; the runner owns the loss")
        return self.loss_fn(logits, targets)

    def receipt(self):
        return {"segments": len(self.segments), "device": self.device.type, "captured": self.captured,
                "captures": self.captures, "warmup_steps": self.warmup_steps, "grad_mode": self.grad_mode,
                "exemplar": {index: [dataclasses.asdict(s) | {"dtype": str(s.dtype)} for s in rec.signature]
                             for index, rec in sorted(self._recorded.items())}}


class _Recording:
    def __init__(self, step):
        self.step = step

    def __enter__(self):
        if self.step._recording:
            raise CaptureStateError("already recording")
        self.step.invalidate()
        self.step._recording = True
        return self.step

    def __exit__(self, *exc):
        self.step._recording = False
        return False
