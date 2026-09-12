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


def _local_scores_rows(summaries, query_weight, keys, log_prior):
    """Row-batched `_local_scores`: one launch set for every chunk of a sparse layer (#1945 batched local router).

    Per row the arithmetic is `_local_scores(summaries[i], query_weight, keys[i], log_prior[i])`: the query is the
    normalized projection of that row's own summary, each candidate key is normalized along its last axis, and the two
    scores are scaled by sqrt(1024) and shifted by that row's log prior. The projection runs as ONE [rows,1024]x[1024,1024]
    GEMM instead of one vector GEMM per chunk, so fp32 accumulation order differs from the per-chunk reference — this is a
    DECLARED numerical treatment of the router, adjudicated by winner identity over a governed arm, never assumed neutral.
    """
    if summaries.ndim != 2 or keys.shape != (len(summaries), 2, summaries.shape[1]) or log_prior.shape != (len(summaries), 2):
        raise ValueError('batched local scores need [rows,1024] summaries, [rows,2,1024] keys and [rows,2] priors')
    query = F.normalize(F.linear(summaries.float(), query_weight.float()), dim=-1)
    scores = torch.bmm(F.normalize(keys.float(), dim=-1), query[:, :, None])[:, :, 0]
    return math.sqrt(1024) * scores + log_prior


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


# The scalar selectors above remain the reference. This per-forward API batches
# materialization, retaining their individual score/softmax operation shapes.
class _RoutingPayload:
    """One device-to-host byte transfer, including all validation flags.

    Capture bytes travel in this same transfer. Host reconstruction never reads
    a live device tensor, including when locals() is requested later.
    """

    def __init__(self, device):
        self.device = device
        self._parts = []
        self._fields = []
        self._size = 0
        self._host = None

    def add(self, value):
        frozen = value.detach().contiguous().clone()
        raw = frozen.reshape(-1).view(torch.uint8)
        field = (self._size, raw.numel(), frozen.dtype, tuple(frozen.shape))
        self._parts.append(raw)
        self._fields.append(field)
        self._size += raw.numel()
        return len(self._fields) - 1

    def drain(self):
        if self._host is not None:
            raise ValueError("routing payload already materialized")
        packed = torch.cat(self._parts) if self._parts else torch.empty(0, dtype=torch.uint8, device=self.device)
        self._host = packed.to(device="cpu").numpy().tobytes()
        self._parts.clear()

    def raw(self, index):
        if self._host is None:
            raise ValueError("routing payload not materialized")
        offset, size, _, _ = self._fields[index]
        return self._host[offset:offset + size]

    def tensor(self, index):
        _, size, dtype, shape = self._fields[index]
        if not size:
            return torch.empty(shape, dtype=dtype)
        # Each reconstruction owns its bytes; mutation cannot alter the packet.
        return torch.frombuffer(bytearray(self.raw(index)), dtype=dtype).reshape(shape)

    def digest(self, index):
        _, _, dtype, shape = self._fields[index]
        return hashlib.sha256(f"{dtype}:{shape}:".encode() + self.raw(index)).hexdigest()


class _RoutingSnapshot:
    """Private original-byte snapshot; tensor version counters are insufficient."""

    def __init__(self, value):
        self.value = value
        self.metadata = (tuple(value.shape), value.dtype, value.device, value.layout)
        self.bytes = value.detach().contiguous().reshape(-1).view(torch.uint8).clone()

    def unchanged(self):
        value = self.value
        if (tuple(value.shape), value.dtype, value.device, value.layout) != self.metadata:
            raise ValueError("routing tensor metadata changed within the forward")
        return (value.detach().contiguous().reshape(-1).view(torch.uint8) == self.bytes).all()


def _routing_metadata(value, shape, device, name):
    _tensor(value, shape, name)
    if value.layout != torch.strided or value.device != device:
        raise ValueError(f"{name} must share the exact strided routing device")


def _routing_flags(payload, flags):
    return payload.add(torch.stack(flags).to(dtype=torch.uint8))


def _routing_require_flags(payload, field):
    if any(value != 1 for value in payload.raw(field)):
        raise ValueError("routing finite or exact-byte custody check failed")


def _unit_task_gate_rows(logits, slots):
    # Preserve the scalar helper's softmax kernel shape and arithmetic order.
    working = logits if logits.dtype == torch.float64 else logits.float()
    probabilities = torch.stack([row.softmax(0).gather(0, slot.reshape(1))[0]
                                 for row, slot in zip(working.unbind(0), slots.unbind(0))])
    return (probabilities - probabilities.detach()) + 1.0


def unit_task_gate_batch(logits, slots):
    """Checked native-slot gates with the same row-wise derivative as the reference."""
    if (not isinstance(logits, torch.Tensor) or logits.ndim != 2 or logits.shape[1] != 2
            or not len(logits) or not logits.is_floating_point()
            or logits.device.type not in {"cpu", "cuda", "meta"}):
        raise ValueError("nonempty floating local logits shaped [n,2] required")
    if (not isinstance(slots, torch.Tensor) or tuple(slots.shape) != (len(logits),)
            or slots.dtype != torch.long or slots.device != logits.device):
        raise ValueError("one same-device integer slot per logits row required")
    if logits.device.type != "meta":
        payload = _RoutingPayload(logits.device)
        flags = _routing_flags(payload, [torch.isfinite(logits).all(),
                                         ((slots >= 0) & (slots < 2)).all()])
        payload.drain()
        _routing_require_flags(payload, flags)
    return _unit_task_gate_rows(logits, slots)


@dataclass(frozen=True)
class ChunkSpec:
    document_offset: int
    start: int
    selection: GlobalSelection
    request: str


class LocalBatch:
    """Native decisions and gates; optional records use selection-time host bytes."""

    def __init__(self, experts, logits, gates, payload, capture_fields):
        self.experts = tuple(experts)
        self.logits = logits
        self.gates = gates
        self._payload = payload
        self._capture_fields = capture_fields

    def locals(self):
        if self._capture_fields is None:
            raise ValueError("local records require capture=True at selection time")
        records = []
        for expert, start, ids, logits, visible, summary, keys, prior in self._capture_fields:
            records.append(LocalSelection(
                expert, self._payload.tensor(logits), start, start, self._payload.digest(visible),
                candidates=ids, summary=self._payload.tensor(summary),
                keys_slice=self._payload.tensor(keys), prior_slice=self._payload.tensor(prior)))
        return tuple(records)


class StepRouting:
    """One forward's routing cache; no residency, optimizer or admission authority.

    Register every document epoch before select_local_batch. Chunk order is
    document offset then segment start and covers every registered request.
    Four 1024-token documents use four global and twelve local host transfers;
    this is a routing subtotal, not a measured whole-step transfer count.
    """

    def __init__(self, global_query, local_query, keys, generation):
        _tensor(keys, (12, 25, 1024), "expert keys")
        self._device = keys.device
        _routing_metadata(keys, (12, 25, 1024), self._device, "expert keys")
        _routing_metadata(global_query, (1024, 1024), self._device, "global query projection")
        _routing_metadata(local_query, (1024, 1024), self._device, "local query projection")
        if not isinstance(generation, str) or not generation:
            raise ValueError("nonempty generation identity required")
        self._global_query, self._local_query, self._keys = global_query, local_query, keys
        self._generation = generation
        self._snapshots = tuple(_RoutingSnapshot(value) for value in (global_query, local_query, keys))
        self._keys_digest = None
        self._documents = {}
        self._selections = {}
        self._closed = False

    def close(self):
        self._closed = True
        self._snapshots = ()
        self._selections.clear()
        self._documents.clear()
        self._global_query = self._local_query = self._keys = None

    def _check_open(self):
        if self._closed:
            raise ValueError("routing forward is closed")

    def _source_flags(self):
        return [flag for snapshot in self._snapshots
                for flag in (snapshot.unchanged(), torch.isfinite(snapshot.value).all())]

    @staticmethod
    def _selection_identity(selection):
        return (selection.generation, selection.request, selection.document_start,
                selection.epoch_start, selection.history_digest, selection.keys_digest,
                selection.prior_digest, selection.experts, selection.selector_version)

    def select_global(self, embedded, *, position, document_start, request):
        self._check_open()
        if type(document_start) is not int or document_start != 0:
            raise ValueError("batched routing document_start must be zero")
        if not isinstance(embedded, torch.Tensor) or embedded.ndim != 2:
            raise ValueError("one document shaped [positions,1024] required")
        _routing_metadata(embedded, (len(embedded), 1024), self._device, "embeddings")
        if not isinstance(request, str) or not request:
            raise ValueError("nonempty request identity required")
        lo, hi = history_window(position=position, document_start=document_start, period=1024)
        if position >= len(embedded) or hi > len(embedded):
            raise ValueError("global position must belong to the bound document")
        document = (len(embedded), document_start)
        if request in self._documents and self._documents[request] != document:
            raise ValueError("request document length or start changed")
        if (request, hi) in self._selections:
            raise ValueError("request epoch already selected in this forward")
        flags = self._source_flags()
        history = embedded[lo:hi].detach()
        flags.append(torch.isfinite(history).all())
        summary = history.float().mean(0) if hi > lo else torch.zeros(1024, device=self._device)
        prior = _global_scores(summary, self._global_query, self._keys)
        flags.append(torch.isfinite(prior).all())
        ranked = torch.argsort(prior, descending=True, stable=True)[:2]
        payload = _RoutingPayload(self._device)
        check_field = _routing_flags(payload, flags)
        ranked_field = payload.add(ranked)
        history_field = payload.add(history)
        prior_field = payload.add(prior)
        keys_field = payload.add(self._keys) if self._keys_digest is None else None
        # Snapshot before releasing the public tensor, independently of its version counter.
        prior_snapshot = _RoutingSnapshot(prior)
        payload.drain()
        _routing_require_flags(payload, check_field)
        experts = tuple(payload.tensor(ranked_field).tolist())
        keys_digest = payload.digest(keys_field) if keys_field is not None else self._keys_digest
        selection = GlobalSelection(
            self._generation, request, document_start, hi, payload.digest(history_field),
            keys_digest, payload.digest(prior_field), experts, prior,
            CUDA_SELECTOR_VERSION if self._device.type == "cuda" else SELECTOR_VERSION)
        self._keys_digest = keys_digest
        self._documents[request] = document
        self._selections[(request, hi)] = (selection, prior_snapshot, self._selection_identity(selection))
        return selection

    def _bound_chunks(self, hidden, chunks, sparse_depth, capture):
        self._check_open()
        if type(sparse_depth) is not int or not 0 <= sparse_depth < 12:
            raise ValueError("sparse_depth must be an integer in [0,12)")
        if type(capture) is not bool:
            raise ValueError("capture must be a bool")
        if not isinstance(hidden, torch.Tensor) or hidden.ndim != 2:
            raise ValueError("concatenated hidden state shaped [positions,1024] required")
        _routing_metadata(hidden, (len(hidden), 1024), self._device, "hidden state")
        if not isinstance(chunks, (tuple, list)) or not chunks or not self._documents:
            raise ValueError("nonempty complete chunk sequence required")
        offsets = {}
        for chunk in chunks:
            if (type(chunk) is not ChunkSpec or type(chunk.document_offset) is not int
                    or chunk.document_offset < 0 or type(chunk.start) is not int
                    or not isinstance(chunk.request, str) or chunk.request not in self._documents):
                raise ValueError("chunk has an unbound document or invalid integer geometry")
            if chunk.request in offsets and offsets[chunk.request] != chunk.document_offset:
                raise ValueError("one offset required per document")
            offsets[chunk.request] = chunk.document_offset
        if offsets.keys() != self._documents.keys():
            raise ValueError("batch must contain every registered document")
        expected, end = [], 0
        for request, offset in sorted(offsets.items(), key=lambda item: item[1]):
            length, document_start = self._documents[request]
            if offset != end:
                raise ValueError("document offsets must exactly partition hidden state")
            expected.extend((offset, start, request) for start in range(document_start, length, 256))
            end += length
        if end != len(hidden) or [(c.document_offset, c.start, c.request) for c in chunks] != expected:
            raise ValueError("complete ordered nonoverlapping segment partition required")
        owned = []
        for chunk in chunks:
            _, document_start = self._documents[chunk.request]
            _, epoch = history_window(position=chunk.start, document_start=document_start, period=1024)
            binding = self._selections.get((chunk.request, epoch))
            if binding is None or binding[0] is not chunk.selection:
                raise ValueError("global selection is not owned by this request epoch and forward")
            selection, snapshot, identity = binding
            if (type(selection) is not GlobalSelection or selection.log_prior is not snapshot.value
                    or self._selection_identity(selection) != identity):
                raise ValueError("global selection identity changed after selection")
            _routing_metadata(selection.log_prior, (25,), self._device, "global log prior")
            owned.append(binding)
        return owned

    def select_local_batch(self, hidden, chunks, *, sparse_depth, capture=False):
        owned = self._bound_chunks(hidden, chunks, sparse_depth, capture)
        flags = self._source_flags()
        # Each prior is checked once per layer, even when several chunks use it.
        seen = set()
        for selection, snapshot, _ in owned:
            if id(selection) not in seen:
                flags.extend((snapshot.unchanged(), torch.isfinite(selection.log_prior).all()))
                seen.add(id(selection))
        logits_rows, candidates, captures = [], [], []
        payload = _RoutingPayload(self._device)
        for chunk in chunks:
            _, document_start = self._documents[chunk.request]
            visible = (hidden[chunk.document_offset + chunk.start - 1:
                              chunk.document_offset + chunk.start]
                       if chunk.start > document_start else hidden[:0])
            flags.append(torch.isfinite(visible).all())
            summary = visible[0].float() if len(visible) else torch.zeros(1024, device=self._device)
            ids = tuple(sorted(chunk.selection.experts))
            keys_slice = self._keys[sparse_depth, list(ids)]
            prior_slice = chunk.selection.log_prior[list(ids)]
            # The individual score reduction shape/order is exactly the reference.
            logits = _local_scores(summary, self._local_query, keys_slice, prior_slice)
            flags.append(torch.isfinite(logits).all())
            logits_rows.append(logits)
            candidates.append(ids)
            if capture:
                captures.append((chunk.start, ids, payload.add(logits), payload.add(visible),
                                 payload.add(summary), payload.add(keys_slice), payload.add(prior_slice)))
        logits = torch.stack(logits_rows)
        slots = torch.argmax(logits, dim=1)
        # Private logits/native slots produce gates before public mutable logits are released.
        gates = _unit_task_gate_rows(logits, slots)
        flags.append(torch.isfinite(gates).all())
        check_field = _routing_flags(payload, flags)
        slot_field = payload.add(slots)
        payload.drain()
        _routing_require_flags(payload, check_field)
        winners = payload.tensor(slot_field).tolist()
        experts = tuple(ids[slot] for ids, slot in zip(candidates, winners))
        records = (tuple((expert,) + fields for expert, fields in zip(experts, captures))
                   if capture else None)
        return LocalBatch(experts, logits, gates, payload if capture else None, records)
