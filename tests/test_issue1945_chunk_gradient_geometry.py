# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Original ragged chunk boundaries survive stable grouping and empty experts."""
from types import SimpleNamespace
from unittest.mock import patch
import torch
import pytest
from ember.model import ember_v0_residency as residency


def test_grouped_block_preserves_ragged_chunk_boundaries():
    sizes = (3, 1, 2, 4)
    chunk_slots = torch.tensor([2, 0, 2, 0])
    slots = chunk_slots.repeat_interleave(torch.tensor(sizes))
    weights = {f'experts__{g}__layers__1__{p}__weight': object()
               for p in ('up', 'gate', 'down') for g in range(4)}
    state = SimpleNamespace(check=lambda: None, device=torch.device('cpu'),
        validate_routed=lambda experts: experts, slot_tensor=torch.arange(4),
        model=SimpleNamespace(weights=weights), ids=tuple(range(4)),
        _geometry_sizes=sizes, _geometry_repeats=torch.tensor(sizes),
        require_valid=lambda predicate, reason: (_ for _ in ()).throw(ValueError(reason)) if not predicate else None)
    values = torch.arange(10, dtype=torch.bfloat16)[:, None].expand(-1, 1024).contiguous()
    with patch.object(residency._ResidentGroupedSwiGLU, 'apply', side_effect=lambda ordered, *args: ordered) as call:
        actual = residency.ResidentExecution.grouped_block(state, values, slots, 1, backend='dynamic')
    assert torch.equal(actual, values)
    args = call.call_args.args
    assert torch.equal(args[1], torch.tensor([5, 5, 10, 10], dtype=torch.int32))
    assert torch.equal(args[5], torch.tensor([[0, 1, 1, 5], [0, 0, 0, 0],
                                            [3, 3, 5, 5], [0, 0, 0, 0]], dtype=torch.int32))
    assert args[5].dtype == torch.int32 and args[5].is_contiguous()
    wrong_slots = slots.clone()
    wrong_slots[1] = 1
    with pytest.raises(ValueError, match='routing'):
        residency.ResidentExecution.grouped_block(state, values, wrong_slots, 1, backend='dynamic')


@pytest.mark.skipif(__import__('os').environ.get('EMBER_CIA_CAPTURE_CUDA') != '1', reason='explicit governed CUDA test required')
def test_chunk_weight_gradient_replays_dynamic_boundaries():
    from ember.model.ember_v0_grouped_capture import grouped_mm
    torch.manual_seed(1945)
    # Dyadic inputs make each FP32 partial exact regardless of reduction tree,
    # while BF16 partial/sum rounding still distinguishes chunked from merged dW.
    a = (torch.randint(-16, 17, (256, 128), device='cuda').bfloat16() / 16).requires_grad_()
    b = torch.randn(4, 128, 64, device='cuda', dtype=torch.bfloat16).requires_grad_()
    dy = torch.randint(-16, 17, (256, 64), device='cuda').bfloat16() / 16
    counts = torch.tensor([[64, 64, 0, 0], [0, 0, 64, 64], [0, 0, 0, 0], [0, 0, 0, 0]], device='cuda', dtype=torch.int32)
    ends = counts.cumsum(1, dtype=torch.int32)
    offsets = counts.sum(1).cumsum(0, dtype=torch.int32)
    def execute():
        out = grouped_mm(a, b, offsets, chunk_ends=ends)
        return out, *torch.autograd.grad(out, (a, b), dy)
    stream = torch.cuda.Stream()
    stream.wait_stream(torch.cuda.current_stream())
    with torch.cuda.stream(stream):
        execute()
        execute()
    torch.cuda.current_stream().wait_stream(stream)
    graph = torch.cuda.CUDAGraph()
    with torch.cuda.graph(graph):
        actual = execute()
    saw_chunk_rounding = False
    for rows in ([[64,64,0,0],[0,0,64,64],[0,0,0,0],[0,0,0,0]],
                 [[0,0,0,0],[1,0,0,0],[0,31,0,0],[0,0,65,159]]):
        counts.copy_(torch.tensor(rows, device='cuda', dtype=torch.int32))
        ends.copy_(counts.cumsum(1, dtype=torch.int32))
        offsets.copy_(counts.sum(1).cumsum(0, dtype=torch.int32))
        graph.replay()
        eager = execute()
        assert torch.equal(actual[2], eager[2]), 'capture differs from eager kernel'
        start = 0
        for group, chunks in enumerate(rows):
            expected = torch.zeros_like(b[group])
            for length in chunks:
                if length:
                    # Independent oracle for FP32 chunk reduction followed by BF16
                    # partial/sum rounding. Small cuBLAS BF16 GEMMs can use different
                    # internal precision; actual expert-shape parity is checked separately.
                    partial = (dy[start:start+length].float().T @ a[start:start+length].detach().float()).T.bfloat16()
                    expected = expected + partial
                    start += length
            assert torch.equal(actual[2][group], expected)
            lo = start - sum(chunks)
            merged = (dy[lo:start].float().T @ a[lo:start].detach().float()).T.bfloat16()
            saw_chunk_rounding |= not torch.equal(expected, merged)
        saved = actual[2].clone()
        graph.replay()
        assert torch.equal(actual[2], saved)
    assert saw_chunk_rounding, 'fixture must distinguish chunk rounding from a merged reduction'
