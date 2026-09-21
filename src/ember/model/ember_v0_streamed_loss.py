# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""K4 full-vocabulary document loss, with one external tied classifier owner.

The eager loss boundary is intentional. Each document's CCE backward produces
one BF16 classifier partial; those partials are added in descending document
order. This is a declared numerical function, not native BF16-logit equivalence.
No filtering, ignored targets, vocabulary truncation or implicit denominator.
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
    def forward(ctx, hidden, classifier, targets, lengths, denominator, operator):
        parts, start = [], 0
        # Local graphs keep only the streaming primitive's saved tensors. They
        # end at detached operands; the outer Function returns the owner union.
        with torch.enable_grad():
            for length in lengths:
                end = start + length
                e = hidden[start:end].detach().requires_grad_(hidden.requires_grad)
                c = classifier.detach().requires_grad_(classifier.requires_grad)
                part = operator(e, c, targets[start:end])
                parts.append((start, end, e, c, part))
                start = end
        ctx.parts = parts
        ctx.denominator = denominator
        ctx.hidden_shape = hidden.shape
        result = sum(part.detach() for _, _, _, _, part in parts) / denominator
        return result

    @staticmethod
    @once_differentiable
    def backward(ctx, upstream):
        grad_hidden = grad_classifier = None
        scale = upstream / ctx.denominator
        for start, end, e, c, part in reversed(ctx.parts):
            inputs = tuple(x for x in (e, c) if x.requires_grad)
            gradients = iter(torch.autograd.grad(part, inputs, scale))
            if e.requires_grad:
                partial = next(gradients)
                if grad_hidden is None:
                    grad_hidden = torch.empty(ctx.hidden_shape, dtype=e.dtype, device=e.device)
                grad_hidden[start:end].copy_(partial)
            if c.requires_grad:
                partial = next(gradients)
                grad_classifier = partial if grad_classifier is None else grad_classifier + partial
        ctx.parts = None
        return grad_hidden, grad_classifier, None, None, None, None


def document_streamed_loss(hidden, classifier, targets, lengths, denominator, *, operator=None):
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
    if (not lengths or any(type(n) is not int or n <= 0 for n in lengths)
            or sum(lengths) != len(hidden) or type(denominator) is not int
            or denominator < len(hidden)):
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
    return _DocumentStreamedLoss.apply(hidden, classifier, targets, lengths, denominator, operator)
