# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""V2 native conversion repair. Matrix kernels and v1 files remain frozen.

Use PTX SM89 conversion instead of the installed software cast that shares
one value's tie bit with two other values. No quantization or timing margin
is changed. This module is imported only inside the runner's GPU lock.
"""
import torch
import triton
import triton.language as tl
from fp8_pair_v1 import kernels as original
from fp8_pair_v1 import contract as c
from .quantization_checks import check_direct_ptx


@triton.jit
def _encode_fp32(value, DTYPE: tl.constexpr):
    # PTX packs operand a high and b low. Preserve the order of all four values.
    # The final operation is an 8-bit reinterpretation, not numeric conversion.
    if DTYPE == tl.float8e4nv:
        encoded = tl.inline_asm_elementwise(
            asm="""{
                .reg .b16 lo, hi;
                cvt.rn.satfinite.e4m3x2.f32 lo, $2, $1;
                cvt.rn.satfinite.e4m3x2.f32 hi, $4, $3;
                mov.b32 $0, {lo, hi};
            }""", constraints='=r,f,f,f,f', args=[value], dtype=tl.uint8,
            is_pure=True, pack=4)
    else:
        tl.static_assert(DTYPE == tl.float8e5, 'only declared FP8 formats')
        encoded = tl.inline_asm_elementwise(
            asm="""{
                .reg .b16 lo, hi;
                cvt.rn.satfinite.e5m2x2.f32 lo, $2, $1;
                cvt.rn.satfinite.e5m2x2.f32 hi, $4, $3;
                mov.b32 $0, {lo, hi};
            }""", constraints='=r,f,f,f,f', args=[value], dtype=tl.uint8,
            is_pure=True, pack=4)
    return encoded.to(DTYPE, bitcast=True)


@triton.jit
def _row_quant(X, Q, S, BAD, R: tl.constexpr, C: tl.constexpr,
               X0: tl.constexpr, X1: tl.constexpr, LIMIT: tl.constexpr,
               BLOCK: tl.constexpr):
    row = tl.program_id(0)
    j = tl.arange(0, BLOCK)
    v = tl.load(X + row * X0 + j * X1, j < C, other=0).to(tl.float32)
    invalid = (v != v) | (tl.abs(v) > 3.4028234663852886e38)
    if tl.sum(invalid.to(tl.int32), 0) > 0:
        tl.atomic_or(BAD, 1)
    maximum = tl.max(tl.abs(v), 0)
    scale = tl.where(maximum > 0, tl.maximum(tl.div_rn(maximum, LIMIT), 1.1754943508222875e-38), 1.)
    q = tl.minimum(tl.maximum(tl.div_rn(v, scale), -LIMIT), LIMIT)
    tl.store(Q + row * C + j, _encode_fp32(q, Q.dtype.element_ty), j < C)
    tl.store(S + row, scale)


@triton.jit
def _weight_quant(WU, WG, Q, S, BAD, F: tl.constexpr, H: tl.constexpr,
                  U0: tl.constexpr, U1: tl.constexpr, G0: tl.constexpr, G1: tl.constexpr,
                  BLOCK: tl.constexpr):
    row = tl.program_id(0)
    j = tl.arange(0, BLOCK)
    if row < F:
        v = tl.load(WU + row * U0 + j * U1, j < H, other=0).to(tl.float32)
    else:
        v = tl.load(WG + (row-F) * G0 + j * G1, j < H, other=0).to(tl.float32)
    invalid = (v != v) | (tl.abs(v) > 3.4028234663852886e38)
    if tl.sum(invalid.to(tl.int32), 0) > 0:
        tl.atomic_or(BAD, 1)
    maximum = tl.max(tl.abs(v), 0)
    scale = tl.where(maximum > 0, tl.maximum(tl.div_rn(maximum, 448.), 1.1754943508222875e-38), 1.)
    q = tl.minimum(tl.maximum(tl.div_rn(v, scale), -448.), 448.)
    tl.store(Q + row * H + j, _encode_fp32(q, Q.dtype.element_ty), j < H)
    tl.store(S + row, scale)


@triton.jit
def _gradient_quant(DU, DG, W_SCALE, QE, C_SCALE, BAD,
                    M: tl.constexpr, F: tl.constexpr,
                    U0: tl.constexpr, U1: tl.constexpr, G0: tl.constexpr, G1: tl.constexpr,
                    BLOCK: tl.constexpr):
    row = tl.program_id(0)
    j = tl.arange(0, BLOCK)
    u = tl.load(DU + row*U0 + j*U1, j < F, other=0).to(tl.float32)
    g = tl.load(DG + row*G0 + (j-F)*G1, (j >= F) & (j < 2*F), other=0).to(tl.float32)
    b = tl.load(W_SCALE+j, j < 2*F, other=0)
    v = tl.where(j < F, u, g) * b
    invalid = (v != v) | (tl.abs(v) > 3.4028234663852886e38)
    if tl.sum(invalid.to(tl.int32), 0) > 0:
        tl.atomic_or(BAD, 1)
    maximum = tl.max(tl.abs(v), 0)
    scale = tl.where(maximum > 0, tl.maximum(tl.div_rn(maximum, 57344.), 1.1754943508222875e-38), 1.)
    q = tl.minimum(tl.maximum(tl.div_rn(v, scale), -57344.), 57344.)
    tl.store(QE + row*(2*F)+j, _encode_fp32(q, QE.dtype.element_ty), j < 2*F)
    tl.store(C_SCALE+row, scale)


class NativeOps(original.NativeOps):
    """Only the three quantizer call paths differ; refresh is still fully charged."""
    def quantize(self,x,fmt):
        dtype,limit=c.FORMATS[fmt]
        q=torch.empty(x.shape,device=x.device,dtype=dtype)
        s=torch.empty(x.shape[0],device=x.device,dtype=torch.float32)
        k=_row_quant[(x.shape[0],)](x,q,s,self.bad,*x.shape,*x.stride(),limit,triton.next_power_of_2(x.shape[1]),
                                  num_warps=4,enable_fp_fusion=False)
        self._record('quant_'+fmt,k)
        return q,s

    def prepare(self,mode,wu,wg):
        c.validate_pair(wu,wg)
        if mode=='B':
            return {'packed':torch.cat((wu,wg),0)}
        if mode not in ('C','D','E'):
            raise ValueError('MODE: unknown native FP8 arm')
        f,h=wu.shape
        q=torch.empty((2*f,h),device=wu.device,dtype=torch.float8_e4m3fn)
        s=torch.empty(2*f,device=wu.device,dtype=torch.float32)
        k=_weight_quant[(2*f,)](wu,wg,q,s,self.bad,f,h,*wu.stride(),*wg.stride(),triton.next_power_of_2(h),
                                num_warps=4,enable_fp_fusion=False)
        self._record('weight_quant',k)
        result=dict(q=q,scales=s)
        if mode=='C':
            result['packed']=torch.cat((wu,wg),0)
        else:
            qt=torch.empty((h,2*f),device=wu.device,dtype=q.dtype)
            k=original._transpose[(triton.cdiv(2*f,32),triton.cdiv(h,32))](q,qt,2*f,h,32,num_warps=4)
            self._record('weight_transpose',k)
            result['qt']=qt
        return result

    def grad_quant(self,du,dg,scales):
        m,f=du.shape
        qe=torch.empty((m,2*f),device=du.device,dtype=torch.float8_e5m2)
        s=torch.empty(m,device=du.device,dtype=torch.float32)
        k=_gradient_quant[(m,)](du,dg,scales,qe,s,self.bad,m,f,*du.stride(),*dg.stride(),triton.next_power_of_2(2*f),
                               num_warps=4,enable_fp_fusion=False)
        self._record('gradient_quant',k)
        return qe,s

    def quantization_report(self):
        observed={}
        for name,kernel in self.compiled.items():
            family=name.split(':',1)[0]
            if family not in ('quant_e4m3','quant_e5m2','weight_quant','gradient_quant'):
                continue
            fmt='e5m2' if family in ('quant_e5m2','gradient_quant') else 'e4m3'
            observed[name]=check_direct_ptx(kernel.asm['ptx'],fmt)
        families={name.split(':',1)[0] for name in observed}
        if not {'quant_e4m3','quant_e5m2','weight_quant','gradient_quant'} <= families:
            raise ValueError('DIRECT_FP8_REQUIRED: not all quantizers exercised')
        return observed
