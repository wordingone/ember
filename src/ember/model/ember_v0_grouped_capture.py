# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Explicit dynamic-offset grouped BF16 kernels for captured resident expert arithmetic.

Offsets are cumulative routed row counts produced and validated by ResidentExecution;
these internal kernels perform no host read of routing values. This numerical treatment
requires separate conformance evidence and does not change the native default.
"""
import atexit
import io
import json
import os

import torch
import triton
import triton.language as tl


_expert_counts = {'param_layout_db': 0, 'kernel_layout_db': 0}


def expert_dispatch_counts():
    return dict(_expert_counts)


def _param_layout_db():
    """Store the expert weight gradient in the PARAMETER layout instead of the kernel's.

    A pure layout treatment: the same accumulator is written to the same values in a
    different physical order, so it is bit-exact by construction and needs no licence pair.
    What it buys is downstream -- AccumulateGrad stops taking a strided operand.

    Counted at the launch site rather than read back from the environment, because a frozen
    manifest variable records that the flag reached the worker and only a count records that
    the branch Triton compiled is the branch that ran.
    """
    on = os.environ.get('EMBER_PARAM_LAYOUT_DB') == '1'
    _expert_counts['param_layout_db' if on else 'kernel_layout_db'] += 1
    return on


def _write_expert_receipt():
    path = os.environ.get('EMBER_FP16_EXPERTS_RECEIPT')
    if not path:
        return
    try:
        with io.open(path, 'w', encoding='utf-8') as handle:
            json.dump(dict(_expert_counts), handle)
    except OSError:
        pass


atexit.register(_write_expert_receipt)


@triton.jit
def _rows(A, B, O, C, M: tl.constexpr, K: tl.constexpr, N: tl.constexpr,
          AS0: tl.constexpr, AS1: tl.constexpr, BS0: tl.constexpr,
          BS1: tl.constexpr, BS2: tl.constexpr,
          BM: tl.constexpr = 32, BN: tl.constexpr = 64, BK: tl.constexpr = 32):
    group = tl.program_id(2)
    start = tl.load(O + group - 1, group > 0, other=0)
    end = tl.load(O + group)
    first = start + tl.program_id(0) * BM
    if first < end:
        rows = first + tl.arange(0, BM)
        cols = tl.program_id(1) * BN + tl.arange(0, BN)
        reduction = tl.arange(0, BK)
        acc = tl.full((BM, BN), 0, tl.float32)
        for block in range(tl.cdiv(K, BK)):
            kk = block * BK + reduction
            left = tl.load(A + rows[:, None] * AS0 + kk[None, :] * AS1,
                           (rows[:, None] < end) & (kk[None, :] < K), other=0)
            right = tl.load(B + group * BS0 + kk[:, None] * BS1 + cols[None, :] * BS2,
                            (kk[:, None] < K) & (cols[None, :] < N), other=0)
            acc += tl.dot(left, right)
        tl.store(C + rows[:, None] * N + cols[None, :], acc,
                 (rows[:, None] < end) & (cols[None, :] < N))


@triton.jit
def _weights(A, D, O, W, ENDS, K: tl.constexpr, N: tl.constexpr,
             AS0: tl.constexpr, AS1: tl.constexpr, DS0: tl.constexpr, DS1: tl.constexpr,
             BM: tl.constexpr = 32, BN: tl.constexpr = 64, BK: tl.constexpr = 32, NC: tl.constexpr = 0,
             TRANS_STORE: tl.constexpr = False):
    group = tl.program_id(2)
    start = tl.load(O + group - 1, group > 0, other=0)
    end = tl.load(O + group)
    rows = tl.program_id(0) * BM + tl.arange(0, BM)
    cols = tl.program_id(1) * BN + tl.arange(0, BN)
    reduction = tl.arange(0, BK)
    acc = tl.full((BM, BN), 0, tl.float32)
    if NC:
        previous = 0
        for chunk in range(NC):
            relative_end = tl.load(ENDS + group * NC + chunk)
            chunk_end = start + relative_end
            if relative_end > previous:
                partial = tl.full((BM, BN), 0, tl.float32)
                for block in range(tl.cdiv(relative_end - previous, BK)):
                    mm = start + previous + block * BK + reduction
                    left = tl.load(A + mm[None, :] * AS0 + rows[:, None] * AS1,
                                   (rows[:, None] < K) & (mm[None, :] < chunk_end), other=0)
                    right = tl.load(D + mm[:, None] * DS0 + cols[None, :] * DS1,
                                    (mm[:, None] < chunk_end) & (cols[None, :] < N), other=0)
                    partial += tl.dot(left, right)
                # Match the reference's BF16 partial and each BF16 accumulation boundary.
                rounded = partial.to(W.dtype.element_ty).to(tl.float32)
                acc = (acc + rounded).to(W.dtype.element_ty).to(tl.float32)
            previous = relative_end
    else:
        for block in range(tl.cdiv(end - start, BK)):
            mm = start + block * BK + reduction
            left = tl.load(A + mm[None, :] * AS0 + rows[:, None] * AS1,
                           (rows[:, None] < K) & (mm[None, :] < end), other=0)
            right = tl.load(D + mm[:, None] * DS0 + cols[None, :] * DS1,
                            (mm[:, None] < end) & (cols[None, :] < N), other=0)
            acc += tl.dot(left, right)
    if TRANS_STORE:
        # The destination is physically (groups, N, K), so K is its fast axis. Transposing
        # the accumulator in REGISTERS keeps this store coalesced, which a bare stride swap
        # does not. Storing in the PARAMETER layout is what lets AccumulateGrad take a
        # contiguous operand instead of the strided add the trace prices at 9,314 us/step.
        tl.store(W + group * K * N + cols[:, None] * K + rows[None, :] * 1, tl.trans(acc),
                 (rows[None, :] < K) & (cols[:, None] < N))
    else:
        tl.store(W + group * K * N + rows[:, None] * N + cols[None, :], acc,
                 (rows[:, None] < K) & (cols[None, :] < N))


def rows(a, b, offsets):
    if a.ndim != 2 or b.ndim != 3 or offsets.ndim != 1:
        raise ValueError('grouped capture requires matrices and one offset vector')
    m, k = a.shape
    groups, bk, n = b.shape
    if (not min(m, k, n, groups) > 0 or k != bk or offsets.shape != (groups,)
            or not a.is_cuda or b.device != a.device or offsets.device != a.device
            or a.dtype != torch.bfloat16 or b.dtype != a.dtype or offsets.dtype != torch.int32):
        raise ValueError('grouped capture requires aligned positive same-device BF16 geometry')
    out = torch.empty((m, n), device=a.device, dtype=a.dtype)
    _rows[(triton.cdiv(m, 64), triton.cdiv(n, 128), groups)](
        a, b, offsets, out, m, k, n, *a.stride(), *b.stride(),
        BM=64, BN=128, BK=32, num_warps=4)
    return out


class DynamicGrouped(torch.autograd.Function):
    @staticmethod
    def forward(ctx, a, b, offsets, chunk_ends):
        if chunk_ends is not None:
            if (chunk_ends.ndim != 2 or chunk_ends.shape[0] != b.shape[0]
                    or not 0 < chunk_ends.shape[1] <= a.shape[0]
                    or chunk_ends.dtype != torch.int32 or chunk_ends.device != a.device
                    or not chunk_ends.is_contiguous()):
                raise ValueError('chunk ends require a contiguous same-device int32 group-by-chunk matrix')
        ctx.save_for_backward(a, b, offsets, chunk_ends)
        return rows(a, b, offsets)

    @staticmethod
    def backward(ctx, gradient):
        a, b, offsets, chunk_ends = ctx.saved_tensors
        k, n = b.shape[1:]
        da = rows(gradient, b.transpose(1, 2), offsets)
        trans = _param_layout_db()
        if trans:
            # Physically (groups, n, k) -- the layout the resident Parameter actually owns,
            # since _grouped_swiglu reaches this kernel through gate/up/down.transpose(1, 2).
            # Returned as a transposed VIEW so autograd still sees b's logical (groups, k, n)
            # shape, which makes this a LAYOUT change and nothing else: not one arithmetic
            # operation differs.
            db = torch.empty((b.shape[0], n, k), device=b.device, dtype=b.dtype).transpose(1, 2)
        else:
            db = torch.empty(b.shape, device=b.device, dtype=b.dtype)
        _weights[(triton.cdiv(k, 64), triton.cdiv(n, 128), b.shape[0])](
            a, gradient, offsets, db, offsets if chunk_ends is None else chunk_ends,
            k, n, *a.stride(), *gradient.stride(),
            BM=64, BN=128, BK=32, NC=0 if chunk_ends is None else chunk_ends.shape[1], num_warps=4,
            TRANS_STORE=trans)
        return da, db, None, None


def grouped_mm(a, b, offsets, *, chunk_ends=None):
    """Optional cumulative per-group chunk ends preserve reference dW rounding.

    The resident caller constructs and validates these device boundaries from its
    bound document geometry and routes. Omission preserves the original reduction.
    """
    return DynamicGrouped.apply(a, b, offsets, chunk_ends)
