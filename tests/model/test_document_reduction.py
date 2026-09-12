# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Document-shaped weight-gradient reduction: forward unchanged, backward reduced per document.

Goal binding: #1945. These tests hold the two halves of the repair apart, because conflating them
is the error the repair exists to correct: the forward must be IDENTICAL to a merged F.linear, and
the weight gradient must NOT be identical to a merged reduction.

The summation order is treated as a measured property of the reference throughout. No test here
asserts that ascending is correct; the tests assert that the order is required, that it is
resolvable against a saved actual gradient, and that an unresolvable case is reported rather than
rounded to the nearer candidate.
"""

import pytest
import torch
import torch.nn.functional as F

from ember.model.ember_v0_document_reduction import (
    ORDERS,
    document_boundaries,
    document_reduced_linear,
    document_spans,
    reduce_weight_gradient,
    resolve_order_against_reference,
)


def _operands(lengths, features=64, outputs=32, dtype=torch.float32):
    generator = torch.Generator().manual_seed(1945)
    rows = sum(lengths)
    values = torch.randn(rows, features, generator=generator, dtype=dtype, requires_grad=True)
    weight = torch.randn(outputs, features, generator=generator, dtype=dtype, requires_grad=True)
    upstream = torch.randn(rows, outputs, generator=generator, dtype=dtype)
    return values, weight, upstream


def _bf16_operands(lengths=(64, 64, 64, 64)):
    return list(lengths), *_operands(list(lengths), features=256, outputs=128,
                                     dtype=torch.bfloat16)


def test_boundaries_are_exclusive_ends_in_ascending_order():
    assert document_boundaries([3, 1, 4]) == (3, 4, 8)


def test_spans_run_both_ways_and_cover_the_same_rows():
    assert document_spans([3, 1, 4], "ascending") == [(0, 3), (3, 4), (4, 8)]
    assert document_spans([3, 1, 4], "descending") == [(4, 8), (3, 4), (0, 3)]


@pytest.mark.parametrize("lengths", [[4], [4, 4, 4, 4], [7, 1, 5]])
def test_forward_is_bit_identical_to_merged_linear(lengths):
    """The forward is the merged forward. Not close to it -- the same bytes."""
    values, weight, _ = _operands(lengths)
    assert torch.equal(document_reduced_linear(values, weight, lengths, "ascending"),
                       F.linear(values, weight))


def test_input_gradient_matches_the_merged_path():
    """Only the WEIGHT gradient is reshaped; the input gradient is untouched."""
    lengths = [4, 4, 4, 4]
    values, weight, upstream = _operands(lengths)

    reduced = document_reduced_linear(values, weight, lengths, "ascending")
    reduced_grad = torch.autograd.grad(reduced, values, upstream, retain_graph=True)[0]

    merged_grad = torch.autograd.grad(F.linear(values, weight), values, upstream)[0]

    assert torch.equal(reduced_grad, merged_grad)


@pytest.mark.parametrize("order", ORDERS)
def test_weight_gradient_is_the_per_document_sum_in_the_stated_order(order):
    lengths = [4, 3, 5]
    values, weight, upstream = _operands(lengths)

    produced = torch.autograd.grad(
        document_reduced_linear(values, weight, lengths, order), weight, upstream)[0]

    assert torch.equal(produced, reduce_weight_gradient(values, upstream, lengths, order))


def test_a_single_document_reduces_to_the_merged_gradient():
    """With one document there is nothing to reshape, so the two paths must coincide."""
    lengths = [12]
    values, weight, upstream = _operands(lengths)

    produced = torch.autograd.grad(
        document_reduced_linear(values, weight, lengths, "ascending"), weight, upstream)[0]
    merged = torch.autograd.grad(F.linear(values, weight), weight, upstream)[0]

    assert torch.equal(produced, merged)


def test_the_reduction_shape_actually_changes_the_gradient_in_bf16():
    """The deliberate red: if this passes trivially, the repair is a no-op.

    In bf16 -- the dtype the model trains in -- a merged reduction and a per-document reduction
    disagree, and that disagreement IS the mechanism behind the section-H tensor failure. A suite
    that never observes it would pass against an implementation that changed nothing.
    """
    lengths, values, weight, upstream = _bf16_operands()

    produced = torch.autograd.grad(
        document_reduced_linear(values, weight, lengths, "ascending"), weight, upstream)[0]
    merged = (upstream.transpose(0, 1) @ values).to(weight.dtype)

    assert not torch.equal(produced.float(), merged.float()), (
        "merged and per-document reductions agreed in bf16; the operands are too small or too "
        "well-conditioned to exercise the mechanism, so this test is not testing anything")


def test_order_is_required_and_never_defaulted():
    """A caller that does not state an order is refused, at both entry points."""
    values, weight, upstream = _operands([4, 4])
    with pytest.raises(ValueError, match="measured, not defaulted"):
        document_reduced_linear(values, weight, [4, 4], "whichever")
    with pytest.raises(ValueError, match="measured, not defaulted"):
        reduce_weight_gradient(values, upstream, [4, 4], None)


def test_order_resolves_against_a_saved_actual_gradient():
    """The order is chosen by reproducing a saved gradient bitwise, not by preference."""
    lengths, values, weight, upstream = _bf16_operands()

    for expected in ORDERS:
        actual = reduce_weight_gradient(values.detach(), upstream, lengths, expected,
                                        dtype=weight.dtype)
        report = resolve_order_against_reference(values.detach(), upstream, lengths, actual)
        assert report["order"] == expected
        assert report["candidates"][expected]["bit_equal"] is True


def test_an_unresolvable_reference_is_reported_rather_than_rounded():
    """When neither order reproduces the saved gradient, the answer is None, not the closer one.

    This is the case that matters: a reference that is not a per-document sum of these operands
    would otherwise have one of the two orders installed on a nearest-match basis, quietly
    introducing a third arithmetic that nothing measured.
    """
    lengths, values, weight, upstream = _bf16_operands()
    merged = (upstream.transpose(0, 1) @ values).to(weight.dtype)

    report = resolve_order_against_reference(values.detach(), upstream, lengths, merged)

    assert report["order"] is None
    assert not any(report["candidates"][order]["bit_equal"] for order in ORDERS)
    assert all(report["candidates"][order]["relative_l2"] > 0.0 for order in ORDERS)


def test_boundaries_must_cover_exactly_the_supplied_rows():
    values, weight, _ = _operands([4, 4])
    with pytest.raises(ValueError, match="cover exactly"):
        document_reduced_linear(values, weight, [4, 3], "ascending")


def test_a_zero_length_document_is_refused():
    with pytest.raises(ValueError, match="at least one row"):
        document_boundaries([4, 0, 4])
