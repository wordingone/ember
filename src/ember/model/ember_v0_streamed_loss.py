# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""K4 full-vocabulary document loss, with one external tied classifier owner.

The eager loss boundary is intentional. Each document's CCE backward produces
one BF16 classifier partial; those partials are added in descending document
order. This is a declared numerical function, not native BF16-logit equivalence.
No filtering, ignored targets, vocabulary truncation or implicit denominator. A document may
declare an explicit loss-bearing row selection (mixture amendment A1: caption
rows of an image-text document); unselected rows carry no loss and receive a
zero hidden gradient, and the caller states the denominator.

Two declared heads live here and are never mixed:

cce-document-v1 (_DocumentStreamedLoss, document_streamed_loss): the function
above. An answer-target weight is PHYSICAL: the caller repeats each answer row
(weight - 1) extra times inside its selection, and repeated rows accumulate by
index_add_.

cce-document-v2 (_WeightedDocumentStreamedLoss, weighted_document_streamed_loss):
ONE CCE call per update over every document's loss-bearing rows, in document
order. Each row appears once and carries an FP32 multiplier (the answer weight
at an answer-letter row, 1 elsewhere); the operator returns sum(nll * weight).
The classifier gradient is accumulated in FP32 inside the kernel and cast to
BF16 once (no BF16 partial adds); the hidden gradient is copied into contiguous
document slices and index_copy_'d into unique selected rows. The caller's
denominator equals the weight total, so the loss value is v1's up to floating
point. This is a different declared numerical function from v1.
"""
from functools import lru_cache
import importlib.util
from pathlib import Path

import torch
from torch.autograd.function import once_differentiable


@lru_cache(maxsize=1)
def _cce_operator():
    # The optional implementation must be source-bound by the run manifest.
    # Import only when selected; native training and CPU inference need no CCE.
    expected = Path(__file__).resolve().parents[2] / 'cut_cross_entropy' / '__init__.py'
    found = importlib.util.find_spec('cut_cross_entropy')
    if found is None or found.origin is None or Path(found.origin).resolve() != expected:
        raise ValueError('Streamed loss requires the source-bound CCE package in this checkout')
    from cut_cross_entropy.cce import CCEParams, linear_cross_entropy_apply

    def operation(hidden, classifier, targets, weights=None):
        # weights None: the v1 call (reduction='sum'), unchanged. weights an FP32 [rows]
        # vector (v2): reduction='none' and the per-row multiplier enters the kernel's upstream.
        params = CCEParams(targets=targets, valids=None, softcap=None,
            reduction='sum' if weights is None else 'none', filter_eps=None, shift=0,
            batch_shape=torch.Size([len(targets)]), accum_e_fp32=True,
            accum_c_fp32=True, filter_e_grad=False, filter_c_grad=False,
            vocab_parallel_options=None, return_lse=False)
        result, _ = linear_cross_entropy_apply(hidden, classifier, None, params)
        return result if weights is None else (result * weights).sum()
    return operation


class _DocumentStreamedLoss(torch.autograd.Function):
    @staticmethod
    def forward(ctx, hidden, classifier, targets, lengths, denominator, operator, selections=None):
        parts, start = [], 0
        # Local graphs keep only the streaming primitive's saved tensors. They
        # end at detached operands; the outer Function returns the owner union.
        with torch.enable_grad():
            for index, length in enumerate(lengths):
                end = start + length
                rows = None if selections is None else selections[index]
                if rows is None:
                    e = hidden[start:end].detach().requires_grad_(hidden.requires_grad)
                    t = targets[start:end]
                else:
                    e = hidden.index_select(0, rows).detach().requires_grad_(hidden.requires_grad)
                    t = targets.index_select(0, rows)
                c = classifier.detach().requires_grad_(classifier.requires_grad)
                part = operator(e, c, t)
                parts.append((start, end, rows, e, c, part))
                start = end
        ctx.parts = parts
        ctx.denominator = denominator
        ctx.hidden_shape = hidden.shape
        result = sum(part.detach() for *_, part in parts) / denominator
        return result

    @staticmethod
    @once_differentiable
    def backward(ctx, upstream):
        grad_hidden = grad_classifier = None
        scale = upstream / ctx.denominator
        selected = any(rows is not None for _, _, rows, *_ in ctx.parts)
        for start, end, rows, e, c, part in reversed(ctx.parts):
            inputs = tuple(x for x in (e, c) if x.requires_grad)
            gradients = iter(torch.autograd.grad(part, inputs, scale))
            if e.requires_grad:
                partial = next(gradients)
                if grad_hidden is None:
                    grad_hidden = (torch.zeros if selected else torch.empty)(
                        ctx.hidden_shape, dtype=e.dtype, device=e.device)
                if rows is None:
                    grad_hidden[start:end].copy_(partial)
                else:
                    grad_hidden.index_add_(0, rows, partial)  # repeated rows accumulate; unique rows equal copy
            if c.requires_grad:
                partial = next(gradients)
                grad_classifier = partial if grad_classifier is None else grad_classifier + partial
        ctx.parts = None
        return grad_hidden, grad_classifier, None, None, None, None, None


def document_streamed_loss(hidden, classifier, targets, lengths, denominator, *, operator=None, selections=None):
    """Return summed full-vocabulary NLL divided by the whole update exposure.

    An injected operator is for derivative conformance only. Production selects
    the pinned CCE implementation and refuses non-CUDA or non-BF16 operands.
    Targets are range-checked before submission; CUDA assertion is asynchronous
    and any failed assertion prevents an accepted optimizer update.
    """
    lengths = tuple(lengths)
    if (hidden.ndim != 2 or classifier.ndim != 2 or targets.ndim != 1
            or hidden.shape[1] != classifier.shape[1] or len(targets) != len(hidden)
            or targets.dtype != torch.int64 or hidden.dtype != classifier.dtype
            or hidden.device != classifier.device or hidden.device != targets.device):
        raise ValueError('Incompatible hidden, classifier or target tensors')
    if selections is not None:
        # Each entry: None (every row of the document) or (row LongTensor on the hidden device, its host count).
        selections = tuple(selections)
        if len(selections) != len(lengths):
            raise ValueError('One selection per document is required')
        counted, rows = 0, []
        for length, entry in zip(lengths, selections):
            if entry is None:
                counted += length
                rows.append(None)
                continue
            index, count = entry
            # count may exceed length only by repeated rows (an answer-target weight, EMBER_ANSWER_WEIGHT).
            if (type(count) is not int or count <= 0 or index.ndim != 1 or len(index) != count
                    or index.dtype != torch.int64 or index.device != hidden.device):
                raise ValueError('Document row selection is invalid')
            counted += count
            rows.append(index)
        selections, exposure = tuple(rows), counted
    else:
        exposure = len(hidden)
    if (not lengths or any(type(n) is not int or n <= 0 for n in lengths)
            or sum(lengths) != len(hidden) or type(denominator) is not int
            or denominator < exposure):
        raise ValueError('Document exposure or whole-update denominator is invalid')
    valid = ((targets >= 0) & (targets < len(classifier))).all()
    if targets.device.type == 'cuda':
        torch._assert_async(valid, 'Streamed loss requires every target in vocabulary')
    elif not bool(valid):
        raise ValueError('Streamed loss requires every target in vocabulary')
    if operator is None:
        if hidden.device.type != 'cuda' or hidden.dtype != torch.bfloat16:
            raise ValueError('Production streamed loss requires CUDA BF16 operands')
        operator = _cce_operator()
    if not callable(operator):
        raise ValueError('Streamed loss operator must be callable')
    return _DocumentStreamedLoss.apply(hidden, classifier, targets, lengths, denominator, operator, selections)


# cce-document-v2 executed receipt, attached to the returned loss tensor as `cce_executed` and written by the
# forward AFTER its operator call returns, from the operands the operator actually received:
#   cce_calls, cce_rows  counted at operator entry (calls, and the merged operand's row count);
#   cce_weight_total     the sum of the weight vector the operator received, reduced ON THE DEVICE and copied to
#                        a pinned host scalar without blocking (never the selection's declared count). With no
#                        weight vector (every document whole) every weight is 1 and the total is the row count.
# Per call, so a forward pre-launched inside the previous update carries its own receipt. Read it with
# executed_values() only after the update has synchronized; the copy is queued before that update's backward.
_LAST_EXECUTED = {}
EXECUTED_FIELDS = frozenset({'cce_calls', 'cce_rows', 'cce_weight_total'})


def require_executed(receipt):
    """Structural check of one call's receipt, safe BEFORE any synchronization (no device value is read).
    Raises ValueError unless the loss reported at least one operator call over at least one row."""
    if (type(receipt) is not dict or set(receipt) != EXECUTED_FIELDS
            or type(receipt['cce_calls']) is not int or receipt['cce_calls'] < 1
            or type(receipt['cce_rows']) is not int or receipt['cce_rows'] < 1
            or not (type(receipt['cce_weight_total']) is int or (
                isinstance(receipt['cce_weight_total'], torch.Tensor)
                and receipt['cce_weight_total'].device.type == 'cpu'
                and receipt['cce_weight_total'].ndim == 0))):
        raise ValueError('weighted document loss did not report its execution')
    return receipt


def executed_values(receipt):
    """One call's receipt as integers. Call only after the update has synchronized."""
    require_executed(receipt)
    total = receipt['cce_weight_total']
    if isinstance(total, torch.Tensor):
        value = float(total)
        if value != round(value):
            raise ValueError('executed weight total is not an integer')
        total = int(round(value))
    return {'cce_calls': receipt['cce_calls'], 'cce_rows': receipt['cce_rows'], 'cce_weight_total': total}


def _device_clause(valid, message):
    """One validation clause. CPU: raise ValueError(message). CUDA: torch._assert_async, which this build reports
    with no message; under CUDA_LAUNCH_BLOCKING=1 the failure surfaces at this call and is re-raised naming the
    clause. Without launch blocking it surfaces, unnamed, at the update's next synchronization."""
    if valid.device.type != 'cuda':
        if not bool(valid):
            raise ValueError(message)
        return
    try:
        torch._assert_async(valid, message)
    except RuntimeError as exc:
        raise RuntimeError('device assertion failed: ' + message) from exc


class _WeightedDocumentStreamedLoss(torch.autograd.Function):
    @staticmethod
    def forward(ctx, hidden, classifier, targets, lengths, denominator, operator, selections=None):
        # pieces: (start, end, rows, offset, n) in document order; rows None = contiguous slice.
        pieces, start, offset = [], 0, 0
        e_parts, t_parts, w_parts = [], [], []
        for index, length in enumerate(lengths):
            end = start + length
            entry = None if selections is None else selections[index]
            if entry is None:
                rows, n = None, length
                e_parts.append(hidden[start:end])
                t_parts.append(targets[start:end])
                w_parts.append(None)
            else:
                rows, weights, _ = entry
                n = len(rows)
                e_parts.append(hidden.index_select(0, rows))
                t_parts.append(targets.index_select(0, rows))
                w_parts.append(weights)
            pieces.append((start, end, rows, offset, n))
            offset += n
            start = end
        # Every document whole and unweighted: the merged operand IS hidden, no copy and no multiplier.
        whole = selections is None or all(entry is None for entry in selections)
        if whole:
            e_all, t_all, w_all = hidden, targets, None
        else:
            e_all, t_all = torch.cat(e_parts), torch.cat(t_parts)
            w_all = torch.cat([torch.ones(n, dtype=torch.float32, device=hidden.device) if w is None else w
                               for w, (*_, n) in zip(w_parts, pieces)])
        calls = []

        def counted(*operands):
            # cce_calls is the number of times the operator was actually entered, not a constant.
            calls.append(int(operands[0].shape[0]))
            return operator(*operands)
        with torch.enable_grad():
            e = e_all.detach().requires_grad_(hidden.requires_grad)
            c = classifier.detach().requires_grad_(classifier.requires_grad)
            part = counted(e, c, t_all) if w_all is None else counted(e, c, t_all, w_all)
        if w_all is None:
            weight_total = sum(calls)  # no weight vector: every weight is 1
        else:
            reduced = w_all.detach().sum(dtype=torch.float64)
            if reduced.device.type == 'cuda':
                weight_total = torch.empty((), dtype=torch.float64, pin_memory=True)
                weight_total.copy_(reduced, non_blocking=True)
            else:
                weight_total = reduced
        _LAST_EXECUTED.update(cce_calls=len(calls), cce_rows=sum(calls), cce_weight_total=weight_total)
        ctx.state = (pieces, e, c, part, whole)
        ctx.denominator = denominator
        ctx.hidden_shape = hidden.shape
        return part.detach() / denominator

    @staticmethod
    @once_differentiable
    def backward(ctx, upstream):
        pieces, e, c, part, whole = ctx.state
        grad_hidden = grad_classifier = None
        inputs = tuple(x for x in (e, c) if x.requires_grad)
        gradients = iter(torch.autograd.grad(part, inputs, upstream / ctx.denominator))
        if e.requires_grad:
            partial = next(gradients)
            if whole:
                grad_hidden = partial
            else:
                grad_hidden = torch.zeros(ctx.hidden_shape, dtype=partial.dtype, device=partial.device)
                for start, end, rows, offset, n in pieces:
                    if rows is None:
                        grad_hidden[start:end].copy_(partial[offset:offset + n])
                    else:
                        grad_hidden.index_copy_(0, rows, partial[offset:offset + n])  # rows unique: validated
        if c.requires_grad:
            grad_classifier = next(gradients)
        ctx.state = None
        return grad_hidden, grad_classifier, None, None, None, None, None


def weighted_document_streamed_loss(hidden, classifier, targets, lengths, denominator, *, operator=None,
                                    selections=None):
    """cce-document-v2: weighted full-vocabulary NLL over all documents in ONE operator call, / denominator.

    selections: None (every row of every document, weight 1) or one entry per document, each None (every row of
    that document, weight 1) or (rows, weights, count): rows a strictly ascending int64 index inside the document
    on the hidden device (so every row is unique), weights an FP32 vector of the same length with every value
    >= 1, and count the host integer total of those weights (count == int(weights.sum())). The denominator must
    be at least the summed weight total. An injected operator takes (e, c, targets) when unweighted and
    (e, c, targets, weights) when weighted.
    """
    lengths = tuple(lengths)
    if (hidden.ndim != 2 or classifier.ndim != 2 or targets.ndim != 1
            or hidden.shape[1] != classifier.shape[1] or len(targets) != len(hidden)
            or targets.dtype != torch.int64 or hidden.dtype != classifier.dtype
            or hidden.device != classifier.device or hidden.device != targets.device):
        raise ValueError('Incompatible hidden, classifier or target tensors')
    if not lengths or any(type(n) is not int or n <= 0 for n in lengths) or sum(lengths) != len(hidden):
        raise ValueError('Document exposure or whole-update denominator is invalid')
    checks = []
    if selections is not None:
        selections = tuple(selections)
        if len(selections) != len(lengths):
            raise ValueError('One selection per document is required')
        exposure, start = 0, 0
        for length, entry in zip(lengths, selections):
            if entry is None:
                exposure += length
            else:
                if type(entry) is not tuple or len(entry) != 3:
                    raise ValueError('Weighted document selection is (rows, weights, count)')
                index, weights, count = entry
                if (type(count) is not int or index.ndim != 1 or weights.ndim != 1 or len(index) == 0
                        or len(weights) != len(index) or count < len(index)
                        or index.dtype != torch.int64 or weights.dtype != torch.float32
                        or index.device != hidden.device or weights.device != hidden.device):
                    raise ValueError('Document row selection is invalid')
                # Four clauses, each with its own name; on CUDA each is an _assert_async (no host read).
                checks.append((weights.sum() == count, 'Weighted selection count differs from its weight total'))
                checks.append(((weights >= 1).all(), 'Weighted selection weight is below one'))
                checks.append(((index[1:] > index[:-1]).all(), 'Weighted selection rows are not unique and ascending'))
                checks.append(((index[0] >= start) & (index[-1] < start + length),
                               'Weighted selection row is outside its document'))
                exposure += count
            start += length
    else:
        exposure = len(hidden)
    if type(denominator) is not int or denominator < exposure:
        raise ValueError('Document exposure or whole-update denominator is invalid')
    checks.append((((targets >= 0) & (targets < len(classifier))).all(),
                   'Streamed loss requires every target in vocabulary'))
    for valid, message in checks:
        _device_clause(valid, message)
    if operator is None:
        if hidden.device.type != 'cuda' or hidden.dtype != torch.bfloat16:
            raise ValueError('Production streamed loss requires CUDA BF16 operands')
        operator = _cce_operator()
    if not callable(operator):
        raise ValueError('Streamed loss operator must be callable')
    _LAST_EXECUTED.clear()
    loss = _WeightedDocumentStreamedLoss.apply(hidden, classifier, targets, lengths, denominator, operator, selections)
    loss.cce_executed = dict(_LAST_EXECUTED)
    return loss
