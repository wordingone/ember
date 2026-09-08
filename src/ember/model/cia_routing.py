# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""CPU reference selection for CIA3-R1-N61, with explicit causal cutoffs.

This is a selection oracle, not a decoder, residency lease, immutable serving
transaction or production-performance path. A unit task-gradient gate is provided
as a separate tested operation, not a complete training integration.
Inputs must be re-embedded under the supplied generation by the caller.
"""
# goal_id: EMBER-02
# workstream_id: EMBER-02A
from dataclasses import dataclass
import hashlib
import math
import torch
import torch.nn.functional as F
from .cia_contract import history_window

SELECTOR_VERSION = "CIA3-R1-N61-cpu-greedy-v1"


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
    establish shape/graph behavior; numerical finite checks apply on CPU.
    """
    if not isinstance(logits, torch.Tensor) or tuple(logits.shape) != (2,) or not logits.is_floating_point():
        raise ValueError("two floating local logits required")
    if logits.device.type not in {"cpu", "meta"}:
        raise ValueError("gate oracle supports CPU or meta only")
    if type(selected_slot) is not int or selected_slot not in (0, 1):
        raise ValueError("selected slot must be zero or one")
    if logits.device.type == "cpu":
        _finite(logits, "local logits")
    # Preserve the finite range of double-precision fixed-tensor callers.
    working = logits if logits.dtype == torch.float64 else logits.float()
    probability = working.softmax(0)[selected_slot]
    return (probability - probability.detach()) + 1.0


def _digest(value):
    value = value.detach().contiguous()
    metadata = f"{value.dtype}:{tuple(value.shape)}:".encode()
    return hashlib.sha256(metadata + value.view(torch.uint8).numpy().tobytes()).hexdigest()


def _tensor(value, shape, name):
    if not isinstance(value, torch.Tensor) or tuple(value.shape) != shape:
        raise ValueError(f"{name} shape must be {shape}")
    if value.device.type != "cpu" or not value.is_floating_point():
        raise ValueError(f"{name} requires CPU floating tensors for this reference oracle")


def _finite(value, name):
    if not torch.isfinite(value).all():
        raise ValueError(f"{name} contains nonfinite values")


def _inputs(values, weight, keys, generation, request):
    if not isinstance(values, torch.Tensor) or values.ndim != 2:
        raise ValueError("history must belong to exactly one request, shaped [positions,1024]")
    _tensor(values, (len(values), 1024), "history")
    _tensor(weight, (1024, 1024), "query projection")
    _tensor(keys, (12, 25, 1024), "expert keys")
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


def select_global(embeddings, query_weight, keys, *, position, document_start, generation, request):
    """Choose two experts from the preceding epoch; first epoch uses zero BOS."""
    _inputs(embeddings, query_weight, keys, generation, request)
    lo, hi = history_window(position=position, document_start=document_start, period=1024)
    if hi > len(embeddings):
        raise ValueError("required preceding epoch is not available")
    history = embeddings[lo:hi].detach()
    _finite(history, "visible embeddings")
    summary = history.float().mean(0) if hi > lo else torch.zeros(1024)
    # The first reference uses temperature 1, deterministic ID-ordered ties.
    log_prior = _global_scores(summary, query_weight, keys)
    _finite(log_prior, "global prior")
    experts = tuple(torch.argsort(log_prior, descending=True, stable=True)[:2].tolist())
    return GlobalSelection(generation, request, document_start, hi, _digest(history),
                           _digest(keys), _digest(log_prior), experts, log_prior)


def select_local(hidden, query_weight, keys, selection, *, position, document_start,
                 generation, request, sparse_depth):
    """Use ONLY the shared-path vector at segment_start-1, before its expert residual."""
    _inputs(hidden, query_weight, keys, generation, request)
    if type(selection) is not GlobalSelection:
        raise ValueError("global selection required")
    if selection.selector_version != SELECTOR_VERSION:
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
    summary = visible[0].float() if len(visible) else torch.zeros(1024)
    # Sort by global ID before argmax so ties do not depend on resident-slot order.
    _tensor(selection.log_prior, (25,), "global log prior")
    _finite(selection.log_prior, "global log prior")
    if _digest(selection.log_prior) != selection.prior_digest:
        raise ValueError("global prior changed after selection")
    expected = tuple(torch.argsort(selection.log_prior, descending=True, stable=True)[:2].tolist())
    if type(selection.experts) is not tuple or selection.experts != expected or any(type(i) is not int for i in selection.experts):
        raise ValueError("invalid global expert identities for this prior")
    ids = tuple(sorted(selection.experts))
    logits = _local_scores(summary, query_weight, keys[sparse_depth, list(ids)], selection.log_prior[list(ids)])
    _finite(logits, "local logits")
    chosen = ids[int(torch.argmax(logits))]
    return LocalSelection(chosen, logits, segment_start, segment_start, _digest(visible))
