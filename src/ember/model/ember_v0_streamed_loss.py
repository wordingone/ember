# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""K4 full-vocabulary document loss, with one external tied classifier owner.

The eager loss boundary is intentional. Each document's CCE backward produces
one BF16 classifier partial; those partials are added in descending document
order. This is a declared numerical function, not native BF16-logit equivalence.
No filtering, vocabulary truncation or implicit denominator. A document may
declare an explicit loss-bearing row selection (mixture amendment A1: caption
rows of an image-text document); unselected rows carry no loss and receive a
zero hidden gradient, and the caller states the denominator.
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

    def operation(hidden, classifier, targets):
        params = CCEParams(targets=targets, valids=None, softcap=None,
            reduction='sum', filter_eps=None, shift=0,
            batch_shape=torch.Size([len(targets)]), accum_e_fp32=True,
            accum_c_fp32=True, filter_e_grad=False, filter_c_grad=False,
            vocab_parallel_options=None, return_lse=False)
        result, _ = linear_cross_entropy_apply(hidden, classifier, None, params)
        return result
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
                    grad_hidden.index_copy_(0, rows, partial)
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
            if (type(count) is not int or not 0 < count <= length or index.ndim != 1 or len(index) != count
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
