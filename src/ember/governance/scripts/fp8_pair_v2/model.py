# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Finite-input CPU model of Ada FP8 K32 products and separate FP32 adds.

Independent equation transcription: MMA-Sim, arXiv:2511.10909v1, IV-C/D,
Table III. Not the official simulator; no tuning to the measured tensors.
Only finite E4M3/E5M2 inputs, E4M3 right operands, normal FP32 sums and
bounded work are accepted. Other cases refuse, not silently approximate.
"""
import numpy as np
import torch

_MODEL_FORMATS = {torch.float8_e4m3fn: -6, torch.float8_e5m2: -14}
MAX_PRODUCTS = 16_777_216


def _exponent(values, minimum):
    exponent = np.maximum(np.frexp(np.abs(values))[1] - 1, minimum)
    return np.where(values == 0, -126, exponent)


def _fda16(a, b, ea, eb, carried):
    # Product exponents are UNNORMALIZED sums of operand exponents.
    products = a[:, :, None] * b[None, :, :]
    pe = ea[:, :, None] + eb[None, :, :]
    pe = np.where(products == 0, -126, pe)
    ce = _exponent(carried, -126)
    maximum = np.maximum(pe.max(axis=1), ce)
    # Aligned significands fit exactly in float64 after truncation to 13 bits.
    aligned = np.trunc(np.ldexp(products, 13-maximum[:, None, :])).sum(axis=1)
    aligned += np.trunc(np.ldexp(carried, 13-maximum))
    total = np.ldexp(aligned, maximum-13)
    re = _exponent(total, -126)
    rounded = np.ldexp(np.trunc(np.ldexp(total, 13-re)), re-13)
    if not np.isfinite(rounded).all() or np.any((rounded != 0) & (np.abs(rounded) < 2.**-126)):
        raise ValueError('MODEL_DOMAIN: nonnormal accumulator outside finite model')
    return rounded.astype(np.float32).astype(np.float64)


def matmul(left, right, *, max_products=MAX_PRODUCTS):
    """Return CPU FP32 matrix output before scales/BF16 storage.

    Every K32 starts with a zero accumulator, runs two K16 FDA stages, then
    adds the partial to the running FP32 sum with round-to-nearest-even.
    This models the pinned promoted kernel, NOT the earlier carried version.
    """
    if (left.device.type != 'cpu' or right.device.type != 'cpu'
            or left.dtype not in _MODEL_FORMATS or right.dtype != torch.float8_e4m3fn
            or left.ndim != 2 or right.ndim != 2
            or min(*left.shape,*right.shape) <= 0 or left.shape[1] != right.shape[0]
            or left.shape[1] % 32):
        raise ValueError('MODEL_SCHEMA: CPU FP8 matrices with positive matching K multiple of 32 required')
    if type(max_products) is not int or max_products < 1 or left.shape[0]*left.shape[1]*right.shape[1] > max_products:
        raise ValueError('MODEL_BOUNDED: requested reference is too large')
    a=left.float().numpy().astype(np.float64)
    b=right.float().numpy().astype(np.float64)
    if not np.isfinite(a).all() or not np.isfinite(b).all():
        raise ValueError('MODEL_NONFINITE: finite quantized operands required')
    ea=_exponent(a,_MODEL_FORMATS[left.dtype]); eb=_exponent(b,_MODEL_FORMATS[right.dtype])
    acc=np.zeros((a.shape[0],b.shape[1]),dtype=np.float32)
    with np.errstate(over='raise',invalid='raise'):
        for k in range(0,a.shape[1],32):
            partial=np.zeros_like(acc,dtype=np.float64)
            for j in (k,k+16):
                partial=_fda16(a[:,j:j+16],b[j:j+16],ea[:,j:j+16],eb[j:j+16],partial)
            acc=np.add(acc,partial.astype(np.float32),dtype=np.float32)
    if not np.isfinite(acc).all(): raise ValueError('MODEL_NONFINITE: FP32 result')
    return torch.from_numpy(acc.copy())


def outputs(qx, qw, qe, activation_scales, weight_scales, gradient_scales):
    """Five named predictions; caller supplies already independently quantized data."""
    f=qw.shape[0]//2
    if qw.shape[0] % 2 or f % 32:
        raise ValueError('MODEL_SCHEMA: two equal projection branches, width divisible by 32')
    for scale,n in ((activation_scales,qx.shape[0]),(weight_scales,qw.shape[0]),(gradient_scales,qe.shape[0])):
        if (scale.device.type!='cpu' or scale.dtype!=torch.float32 or tuple(scale.shape)!=(n,)
                or not bool(torch.isfinite(scale).all()) or not bool((scale>0).all())):
            raise ValueError('MODEL_SCHEMA: positive finite CPU FP32 scales required')
    forward=((matmul(qx,qw.T)*activation_scales[:,None])*weight_scales[None,:]).to(torch.bfloat16)
    bundled=(matmul(qe,qw)*gradient_scales[:,None]).to(torch.bfloat16)
    separate=((matmul(qe[:,:f],qw[:f])+matmul(qe[:,f:],qw[f:]))*gradient_scales[:,None]).to(torch.bfloat16)
    return {'C_fprop_oracle':forward,'D_fprop_oracle':forward.clone(),
            'E_fprop_oracle':forward.clone(),'D_dgrad_oracle':bundled,'E_dgrad_oracle':separate}


def predict_fixture(fixture):
    """Replay the prior diagnostic tensor schema, without accessing a GPU."""
    qx=fixture['qx_bytes'].view(torch.float8_e4m3fn)
    qw=fixture['qw_bytes'].view(torch.float8_e4m3fn)
    qe=fixture['qe_bytes'].view(torch.float8_e5m2)
    if not torch.equal(qw.view(torch.uint8).T,fixture['qt_bytes']):
        raise ValueError('MODEL_SCHEMA: shadow transpose mismatch')
    return outputs(qx,qw,qe,fixture['activation_scales'],fixture['weight_scales'],fixture['gradient_scales'])
