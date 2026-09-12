# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Per-document weight-gradient reduction with the forward left merged.

CONTRACT. `document_reduced_linear(values, weight, lengths, order)`:
  forward         F.linear(values, weight) on the merged rows, byte-identical.
  input gradient  grad_output @ weight, merged, unchanged.
  weight gradient sum of per-document partials, each dY_i^T @ X_i at that document's own row
                  count, summed sequentially in `order` and cast to the weight dtype. No wider
                  accumulator: matching the reference means matching its rounding.

`order` is REQUIRED and has no default. In bf16 a per-document sum is not associative, so the
order is part of the reference rather than a design choice, and a default would decide it by
omission. `resolve_order_against_reference` picks it by reproducing a saved actual gradient
bitwise and returns order=None when neither candidate does -- refusing rather than installing the
nearer one, which would be a third arithmetic nothing measured.

MEASURED SCOPE (real captured first-pack operands, four documents of 1024 rows, bf16, cuda:0,
2026-09-12; receipts state/issue1945-receipts/core-dw-order-resolution-cuda.json and
shared-dw-order-resolution.json):
  order = descending, bitwise exact on 24 of 24 weights -- attention q/k/v/o at layers 1/2/3 and
  shared up/gate/down at layers 0/2/13/22. Ascending reproduces none of them.
  Merged and per-document forwards are bit-equal for q, o and shared up/gate/down at this
  geometry; k and v differ merged (relative L2 .00283-.00289). This module changes no forward.

DEVICE IS PART OF THE MEASUREMENT. The same resolution on CPU returns "neither order" for every
weight, so a CPU answer here is wrong rather than weak. The receipts record the device.

CLAIM BOUNDARY. A component reduction change measured on one captured pack. Not a treatment
effect, not an accumulation claim over 64 updates, not throughput, not the hour, not held-out, not
Evaluation, not terminal acceptance of #1945. The frozen section-H criterion is untouched.
"""

from __future__ import annotations

import torch
import torch.nn.functional as F

__all__ = [
    "document_boundaries",
    "document_spans",
    "document_reduced_linear",
    "reduce_weight_gradient",
    "resolve_order_against_reference",
]

ORDERS = ("ascending", "descending")


def document_boundaries(lengths):
    """Exclusive row ends per document, ascending. `lengths` is the per-document row count."""
    bounds, offset = [], 0
    for length in lengths:
        length = int(length)
        if length <= 0:
            raise ValueError("every document contributes at least one row")
        offset += length
        bounds.append(offset)
    return tuple(bounds)


def document_spans(lengths, order):
    """(start, end) row spans per document, emitted in the requested summation order.

    `order` is required. There is no default, because in bf16 the order is part of the reference
    and a silent default would decide a measured question by omission.
    """
    if order not in ORDERS:
        raise ValueError(f"order must be one of {ORDERS}; it is measured, not defaulted")
    spans, start = [], 0
    for end in document_boundaries(lengths):
        spans.append((start, end))
        start = end
    return spans if order == "ascending" else list(reversed(spans))


def reduce_weight_gradient(values, upstream, lengths, order, dtype=None):
    """Sum the per-document weight-gradient partials in the stated order.

    Each partial is one document's dY^T @ X at that document's own row count -- the serial path's
    GEMM shape and its accumulation -- and the partials are summed sequentially. Nothing here is
    promoted to a wider accumulator: matching the reference means matching its rounding, and a
    more accurate reduction is still a different one.
    """
    total = None
    for start, end in document_spans(lengths, order):
        partial = upstream[start:end].transpose(0, 1) @ values[start:end]
        total = partial if total is None else total + partial
    return total if dtype is None else total.to(dtype)


class _DocumentReducedLinear(torch.autograd.Function):
    """Merged forward; weight gradient reduced per document in the measured reference order."""

    @staticmethod
    def forward(ctx, values, weight, lengths, order):
        if values.ndim != 2:
            raise ValueError("expected [rows,features]")
        if document_boundaries(lengths)[-1] != values.shape[0]:
            raise ValueError("document boundaries do not cover exactly the supplied rows")
        if order not in ORDERS:
            raise ValueError(f"order must be one of {ORDERS}; it is measured, not defaulted")
        ctx.save_for_backward(values, weight)
        ctx.lengths, ctx.order = tuple(int(length) for length in lengths), order
        return F.linear(values, weight)

    @staticmethod
    def backward(ctx, grad_output):
        values, weight = ctx.saved_tensors
        grad_input = grad_output @ weight if ctx.needs_input_grad[0] else None
        grad_weight = None
        if ctx.needs_input_grad[1]:
            grad_weight = reduce_weight_gradient(
                values, grad_output, ctx.lengths, ctx.order, dtype=weight.dtype)
        return grad_input, grad_weight, None, None


def document_reduced_linear(values, weight, lengths, order):
    """F.linear on the merged rows, with the weight gradient reduced per document.

    The forward is byte-identical to F.linear. The backward weight gradient differs from a merged
    reduction by design: it restores the per-document reduction shape the reference path has.
    `order` is required and comes from resolve_order_against_reference, never from a guess.
    """
    return _DocumentReducedLinear.apply(values, weight, lengths, order)


def resolve_order_against_reference(values, upstream, lengths, actual_gradient):
    """Choose the summation order by reproducing a SAVED ACTUAL gradient bitwise.

    Returns a dict carrying the resolved order, or `order=None` when neither candidate reproduces
    the saved gradient. A non-answer is reported rather than rounded off to the nearer candidate:
    if neither order is bitwise exact, the reference is not a per-document sum of these operands
    and wiring either one in would silently install a third arithmetic.
    """
    report, resolved = {}, None
    for candidate in ORDERS:
        produced = reduce_weight_gradient(
            values, upstream, lengths, candidate, dtype=actual_gradient.dtype)
        reference = actual_gradient.detach().float()
        exact = bool(torch.equal(produced.detach().float(), reference))
        difference = produced.detach().float() - reference
        report[candidate] = dict(
            bit_equal=exact,
            relative_l2=float(difference.norm()) / max(float(reference.norm()), 1e-30),
            unequal=int(torch.count_nonzero(difference != 0)))
        if exact and resolved is None:
            resolved = candidate
    return dict(order=resolved,
                order_is_load_bearing=report["ascending"]["bit_equal"] != report["descending"]["bit_equal"],
                candidates=report,
                elements=int(actual_gradient.numel()))
