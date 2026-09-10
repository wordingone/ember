# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""CPU/CUDA selection for CIA3-R1-N61, with explicit causal cutoffs.

Selection alone is not a residency lease, immutable serving transaction or
production-performance result. CUDA uses an explicit selector identity and
same-device checks; detached receipt hashing incurs a host transfer whose cost
must be included in the complete execution measurement.
Inputs must be re-embedded under the supplied generation by the caller.
"""
# goal_id: EMBER-02
# workstream_id: EMBER-02A
from dataclasses import dataclass
import hashlib
import math
import torch
import torch.nn.functional as F
from .ember_v0_contract import history_window

SELECTOR_VERSION = "CIA3-R1-N61-cpu-greedy-v1"
CUDA_SELECTOR_VERSION = "CIA3-R1-N61-cuda-greedy-v1"


def _global_scores(summary, query_weight, keys):
    query = F.normalize(F.linear(summary.detach().float(), query_weight.float()), dim=0)
    mean_keys = F.normalize(keys.float().mean(0), dim=-1)
    return F.log_softmax(mean_keys @ query, dim=0)


def _local_scores(summary, query_weight, keys, log_prior):
    query = F.normalize(F.linear(summary.float(), query_weight.float()), dim=0)
    return math.sqrt(1024) * (F.normalize(keys.float(), dim=-1) @ query) + log_prior


def unit_task_gate(logits, selected_slot):
    """Unit forward residual scale with the selected softmax derivative.

    The selected index is discrete, not differentiable top-k. Meta inputs only
    establish shape/graph behavior; physical inputs receive finite checks.
    """
    if not isinstance(logits, torch.Tensor) or tuple(logits.shape) != (2,) or not logits.is_floating_point():
        raise ValueError("two floating local logits required")
    if logits.device.type not in {"cpu", "cuda", "meta"}:
        raise ValueError("gate supports CPU, CUDA or meta only")
    if type(selected_slot) is not int or selected_slot not in (0, 1):
        raise ValueError("selected slot must be zero or one")
    if logits.device.type != "meta":
        _finite(logits, "local logits")
    # Preserve the finite range of double-precision fixed-tensor callers.
    working = logits if logits.dtype == torch.float64 else logits.float()
    probability = working.softmax(0)[selected_slot]
    return (probability - probability.detach()) + 1.0


def _digest(value):
    value = value.detach().cpu().contiguous()
    metadata = f"{value.dtype}:{tuple(value.shape)}:".encode()
    return hashlib.sha256(metadata + value.view(torch.uint8).numpy().tobytes()).hexdigest()


def _tensor(value, shape, name):
    if not isinstance(value, torch.Tensor) or tuple(value.shape) != shape:
        raise ValueError(f"{name} shape must be {shape}")
    if value.device.type not in {'cpu', 'cuda'} or not value.is_floating_point():
        raise ValueError(f"{name} requires CPU or CUDA floating tensors")


def _finite(value, name):
    if not torch.isfinite(value).all():
        raise ValueError(f"{name} contains nonfinite values")


def _inputs(values, weight, keys, generation, request):
    if not isinstance(values, torch.Tensor) or values.ndim != 2:
        raise ValueError("history must belong to exactly one request, shaped [positions,1024]")
    _tensor(values, (len(values), 1024), "history")
    _tensor(weight, (1024, 1024), "query projection")
    _tensor(keys, (12, 25, 1024), "expert keys")
    if values.device != weight.device or values.device != keys.device:
        raise ValueError('routing inputs must share the exact device')
    for identity in (generation, request):
        if not isinstance(identity, str) or not identity:
            raise ValueError("nonempty generation and request identities required")
    _finite(weight, "query projection")
    _finite(keys, "expert keys")


@dataclass(frozen=True)
class GlobalSelection:
    generation: str
    request: str
    document_start: int
    epoch_start: int
    history_digest: str
    keys_digest: str
    prior_digest: str
    experts: tuple[int, int]
    log_prior: torch.Tensor
    selector_version: str = SELECTOR_VERSION


@dataclass(frozen=True)
class LocalSelection:
    expert: int
    logits: torch.Tensor
    segment_start: int
    history_cutoff: int
    history_digest: str
    # Capture is opt-in and defaults to absent. The same selection call runs inside the measured
    # optimizer step, whose phase decomposition is a bound observation, so measurement material is
    # never allocated unless a caller asks for it.
    candidates: tuple[int, int] | None = None
    summary: torch.Tensor | None = None
    keys_slice: torch.Tensor | None = None
    prior_slice: torch.Tensor | None = None


@dataclass(frozen=True)
class GlobalObservation:
    """One global selection, as measured, with its inputs on the host."""
    document: int
    epoch_start: int
    experts: tuple[int, int]
    log_prior: torch.Tensor
    history_digest: str
    keys_digest: str
    prior_digest: str
    selector_version: str


@dataclass(frozen=True)
class LocalObservation:
    """One free local selection, with the exact inputs its two scores came from.

    `margin` is signed in ascending candidate-ID order, so its SIGN carries which candidate won and
    its magnitude carries how close the decision was. A backend that selects the other candidate
    flips the sign, which is why the pair of signed margins -- not a pair of winners -- is what the
    admissibility bound is written against.

    Exactly zero is a tie, and it does occur on the fixed fixture. A tie is resolved by argmax over
    ID-sorted candidates, so a zero margin means the LOWER candidate ID won. Reading the winner
    from a strict `> 0` therefore names the wrong candidate at exactly the closest decisions there
    are, which is where a routing comparison most needs to be right.
    """
    document: int
    layer: int
    segment_start: int
    candidates: tuple[int, int]
    chosen: int
    logits: tuple[float, float]
    margin: float
    summary: torch.Tensor
    keys_slice: torch.Tensor
    prior_slice: torch.Tensor
    history_digest: str

    @property
    def key(self):
        return (self.document, self.layer, self.segment_start)


def _host(value):
    """Float32 on the host: the two backends' records must be comparable without a second copy."""
    return value.detach().to(device='cpu', dtype=torch.float32).clone()


def observe_local(selection, *, document, layer):
    """Build the record for a captured selection; refuses an uncaptured one rather than guessing."""
    if type(selection) is not LocalSelection:
        raise ValueError("local selection required")
    if selection.candidates is None or selection.summary is None:
        raise ValueError("selection was not captured; call select_local(capture=True)")
    logits = _host(selection.logits)
    # One arithmetic, in double, over the two scores this record publishes. Subtracting in float32
    # and widening afterwards gives a different number -- measured -3.2118711471557617 against
    # -3.211871027946472 on the fixed fixture -- so a reader recomputing the margin from the
    # published pair would disagree with the margin the admissibility bound was applied to. The
    # two float32 scores are exact in double, so their double difference is exact as well.
    scores = (float(logits[0]), float(logits[1]))
    return LocalObservation(document=document, layer=layer, segment_start=selection.segment_start,
                            candidates=selection.candidates, chosen=selection.expert,
                            logits=scores,
                            margin=scores[0] - scores[1],
                            summary=_host(selection.summary),
                            keys_slice=_host(selection.keys_slice),
                            prior_slice=_host(selection.prior_slice),
                            history_digest=selection.history_digest)


def observe_global(selection, *, document):
    if type(selection) is not GlobalSelection:
        raise ValueError("global selection required")
    return GlobalObservation(document=document, epoch_start=selection.epoch_start,
                             experts=selection.experts, log_prior=_host(selection.log_prior),
                             history_digest=selection.history_digest,
                             keys_digest=selection.keys_digest, prior_digest=selection.prior_digest,
                             selector_version=selection.selector_version)


def select_global(embeddings, query_weight, keys, *, position, document_start, generation, request):
    """Choose two experts from the preceding epoch; first epoch uses zero BOS."""
    _inputs(embeddings, query_weight, keys, generation, request)
    lo, hi = history_window(position=position, document_start=document_start, period=1024)
    if hi > len(embeddings):
        raise ValueError("required preceding epoch is not available")
    history = embeddings[lo:hi].detach()
    _finite(history, "visible embeddings")
    summary = history.float().mean(0) if hi > lo else torch.zeros(1024, device=embeddings.device)
    # The first reference uses temperature 1, deterministic ID-ordered ties.
    log_prior = _global_scores(summary, query_weight, keys)
    _finite(log_prior, "global prior")
    experts = tuple(torch.argsort(log_prior, descending=True, stable=True)[:2].tolist())
    return GlobalSelection(generation, request, document_start, hi, _digest(history),
                           _digest(keys), _digest(log_prior), experts, log_prior,
                           CUDA_SELECTOR_VERSION if embeddings.device.type == 'cuda' else SELECTOR_VERSION)


def select_local(hidden, query_weight, keys, selection, *, position, document_start,
                 generation, request, sparse_depth, capture=False):
    """Use ONLY the shared-path vector at segment_start-1, before its expert residual."""
    _inputs(hidden, query_weight, keys, generation, request)
    if type(selection) is not GlobalSelection:
        raise ValueError("global selection required")
    if selection.selector_version != (CUDA_SELECTOR_VERSION if hidden.device.type == 'cuda' else SELECTOR_VERSION):
        raise ValueError("incompatible selector version")
    if type(sparse_depth) is not int or not 0 <= sparse_depth < 12:
        raise ValueError("sparse_depth must be an integer in [0,12)")
    _, epoch_start = history_window(position=position, document_start=document_start, period=1024)
    _, segment_start = history_window(position=position, document_start=document_start, period=256)
    if (selection.generation, selection.request, selection.document_start, selection.epoch_start) != (
            generation, request, document_start, epoch_start):
        raise ValueError("global selection belongs to a different generation/request/document/epoch")
    if selection.keys_digest != _digest(keys):
        raise ValueError("expert keys changed after global selection")
    if segment_start > len(hidden):
        raise ValueError("preceding shared-path vector is unavailable")
    visible = hidden[segment_start - 1:segment_start] if segment_start > document_start else hidden[:0]
    _finite(visible, "visible hidden state")
    summary = visible[0].float() if len(visible) else torch.zeros(1024, device=hidden.device)
    # Sort by global ID before argmax so ties do not depend on resident-slot order.
    _tensor(selection.log_prior, (25,), "global log prior")
    if selection.log_prior.device != hidden.device:
        raise ValueError('global prior must share the exact routing device')
    _finite(selection.log_prior, "global log prior")
    if _digest(selection.log_prior) != selection.prior_digest:
        raise ValueError("global prior changed after selection")
    expected = tuple(torch.argsort(selection.log_prior, descending=True, stable=True)[:2].tolist())
    if type(selection.experts) is not tuple or selection.experts != expected or any(type(i) is not int for i in selection.experts):
        raise ValueError("invalid global expert identities for this prior")
    ids = tuple(sorted(selection.experts))
    keys_slice = keys[sparse_depth, list(ids)]
    prior_slice = selection.log_prior[list(ids)]
    logits = _local_scores(summary, query_weight, keys_slice, prior_slice)
    _finite(logits, "local logits")
    chosen = ids[int(torch.argmax(logits))]
    if type(capture) is not bool:
        raise ValueError("capture must be a bool")
    if not capture:
        return LocalSelection(chosen, logits, segment_start, segment_start, _digest(visible))
    # Detached copies: the captured material is evidence, and evidence that keeps the autograd
    # graph alive would both retain the forward and let a later backward change what was recorded.
    return LocalSelection(chosen, logits, segment_start, segment_start, _digest(visible),
                          candidates=ids, summary=summary.detach().clone(),
                          keys_slice=keys_slice.detach().clone(),
                          prior_slice=prior_slice.detach().clone())
