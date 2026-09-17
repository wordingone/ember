# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Custom autograd boundary for the experimental pair, not installed in a trainer."""
from __future__ import annotations
import torch


class _Pair(torch.autograd.Function):
    @staticmethod
    def forward(ctx, x, wu, wg, mode, ops, shadow, lengths, wgrad):
        if (not lengths or any(type(n) is not int or n <= 0 for n in lengths)
                or x.ndim != 2 or wu.ndim != 2 or wu.shape != wg.shape
                or x.shape[1] != wu.shape[1] or sum(lengths) != x.shape[0]
                or any(t.dtype != torch.bfloat16 for t in (x, wu, wg))
                or any(t.device != x.device for t in (wu, wg))):
            raise ValueError('PAIR_SCHEMA: inputs/weights/documents do not align')
        if mode not in ('B','C','D','E'):
            raise ValueError('MODE: invalid experiment arm')
        ctx.save_for_backward(x, wu, wg)
        ctx.mode, ctx.ops, ctx.shadow = mode, ops, shadow
        ctx.lengths, ctx.wgrad = tuple(lengths), wgrad
        ctx.set_materialize_grads(True)
        return ops.forward(mode, x, wu, wg, shadow)

    @staticmethod
    def backward(ctx, du, dg):
        x, wu, wg = ctx.saved_tensors
        # Unquantized upstreams enter the original document-wise weight reduction.
        dx = ctx.ops.dgrad(ctx.mode, du, dg, wu, wg, ctx.shadow) if ctx.needs_input_grad[0] else None
        dwu = ctx.wgrad(x, du, ctx.lengths, 'descending', dtype=wu.dtype) if ctx.needs_input_grad[1] else None
        dwg = ctx.wgrad(x, dg, ctx.lengths, 'descending', dtype=wg.dtype) if ctx.needs_input_grad[2] else None
        return dx, dwu, dwg, None, None, None, None, None


def pair(x, wu, wg, mode, ops, shadow, lengths, wgrad):
    return _Pair.apply(x, wu, wg, mode, ops, shadow, lengths, wgrad)
