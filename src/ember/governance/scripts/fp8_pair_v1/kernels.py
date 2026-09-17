# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Native SM89 FP8 primitives. No BF16 fallback and no autotuning sweep.

All multiplies use explicit FP8 operands and FP32 dot outputs. PTX validation
is performed after warmup by the probe. CUDA compilation is a native test,
not something the CPU suite can certify.
"""
import torch
import triton
import triton.language as tl
from . import contract as c


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
    tl.store(Q + row * C + j, q.to(Q.dtype.element_ty, fp_downcast_rounding='rtne'), j < C)
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
    tl.store(Q + row * H + j, q.to(Q.dtype.element_ty, fp_downcast_rounding='rtne'), j < H)
    tl.store(S + row, scale)


@triton.jit
def _transpose(Q, QT, R: tl.constexpr, C: tl.constexpr, BLOCK: tl.constexpr):
    rr = tl.program_id(0) * BLOCK + tl.arange(0, BLOCK)
    cc = tl.program_id(1) * BLOCK + tl.arange(0, BLOCK)
    # No numeric conversion: load/store the same FP8 type in a tiled transpose.
    x = tl.load(Q + rr[:, None] * C + cc[None, :], (rr[:, None] < R) & (cc[None, :] < C), other=0.0)
    tl.store(QT + cc[None, :] * R + rr[:, None], x, (rr[:, None] < R) & (cc[None, :] < C))


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
    tl.store(QE + row*(2*F)+j, q.to(QE.dtype.element_ty, fp_downcast_rounding='rtne'), j < 2*F)
    tl.store(C_SCALE+row, scale)


@triton.jit
def _fprop(QX, QW, A, B, U, G, M: tl.constexpr, H: tl.constexpr,
           N: tl.constexpr, F: tl.constexpr, SPLIT: tl.constexpr,
           W0: tl.constexpr, W1: tl.constexpr,
           BM: tl.constexpr=32, BN: tl.constexpr=128, BK: tl.constexpr=32):
    rr = tl.program_id(0)*BM + tl.arange(0,BM)
    jj = tl.program_id(1)*BN + tl.arange(0,BN)
    kk = tl.arange(0,BK)
    acc = tl.full((BM,BN),0,tl.float32)
    for block in range(tl.cdiv(H,BK)):
        h = block*BK + kk
        left = tl.load(QX + rr[:,None]*H+h[None,:], (rr[:,None]<M)&(h[None,:]<H), other=0.0)
        right = tl.load(QW + jj[None,:]*W0+h[:,None]*W1, (jj[None,:]<N)&(h[:,None]<H), other=0.0)
        partial = tl.dot(left,right,out_dtype=tl.float32,max_num_imprecise_acc=0)
        # A plain add is fused into the dot accumulator by Triton CombineDotAdd.
        # Keep each 32-term FP8 dot independent; sum its result using FP32 ALUs.
        acc = tl.inline_asm_elementwise(
            asm='add.rn.f32 $0, $1, $2;', constraints='=f,f,f',
            args=[acc, partial], dtype=tl.float32, is_pure=True, pack=1)
    a = tl.load(A+rr,rr<M,other=0)
    b = tl.load(B+jj,jj<N,other=0)
    result = (acc*a[:,None])*b[None,:]
    if SPLIT:
        tl.store(U+rr[:,None]*F+jj[None,:],result,(rr[:,None]<M)&(jj[None,:]<F))
        tl.store(G+rr[:,None]*F+jj[None,:]-F,result,(rr[:,None]<M)&(jj[None,:]>=F)&(jj[None,:]<N))
    else:
        tl.store(U+rr[:,None]*N+jj[None,:],result,(rr[:,None]<M)&(jj[None,:]<N))


@triton.jit
def _dgrad(QE, QT, S, OUT, M: tl.constexpr, K: tl.constexpr, N: tl.constexpr,
           E0: tl.constexpr,E1: tl.constexpr,T0: tl.constexpr,T1: tl.constexpr,
           PARTIAL: tl.constexpr,
           BM: tl.constexpr=32, BN: tl.constexpr=128, BK: tl.constexpr=32):
    rr=tl.program_id(0)*BM+tl.arange(0,BM)
    jj=tl.program_id(1)*BN+tl.arange(0,BN)
    kk=tl.arange(0,BK)
    acc=tl.full((BM,BN),0,tl.float32)
    for block in range(tl.cdiv(K,BK)):
        k=block*BK+kk
        left=tl.load(QE+rr[:,None]*E0+k[None,:]*E1,(rr[:,None]<M)&(k[None,:]<K),other=0.0)
        right=tl.load(QT+jj[None,:]*T0+k[:,None]*T1,(jj[None,:]<N)&(k[:,None]<K),other=0.0)
        partial=tl.dot(left,right,out_dtype=tl.float32,max_num_imprecise_acc=0)
        # A plain add is fused into the dot accumulator by Triton CombineDotAdd.
        # Keep each 32-term FP8 dot independent; sum its result using FP32 ALUs.
        acc = tl.inline_asm_elementwise(
            asm='add.rn.f32 $0, $1, $2;', constraints='=f,f,f',
            args=[acc, partial], dtype=tl.float32, is_pure=True, pack=1)
    if not PARTIAL:
        scale=tl.load(S+rr,rr<M,other=0)
        acc=acc*scale[:,None]
    tl.store(OUT+rr[:,None]*N+jj[None,:],acc,(rr[:,None]<M)&(jj[None,:]<N))


@triton.jit
def _combine(A,B,S,Y,M:tl.constexpr,H:tl.constexpr,BLOCK:tl.constexpr):
    i=tl.program_id(0)*BLOCK+tl.arange(0,BLOCK)
    a=tl.load(A+i,i<M*H,other=0)
    b=tl.load(B+i,i<M*H,other=0)
    s=tl.load(S+i//H,i<M*H,other=0)
    tl.store(Y+i,(a+b)*s,i<M*H)


class NativeOps:
    """No training install. Preparation is INSIDE every measured invocation."""
    def __init__(self, device):
        if str(device) not in ('cuda','cuda:0'):
            raise ValueError('DEVICE: this prototype requires cuda:0')
        self.bad = torch.zeros((),device=device,dtype=torch.int32)
        self.compiled = {}

    def _record(self,name,kernel):
        key=name+':'+kernel.hash
        if key not in self.compiled:
            self.compiled[key]=kernel

    def require_valid(self):
        if int(self.bad):
            raise ValueError('NONFINITE: native quantization flagged an invalid input')

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
            k=_transpose[(triton.cdiv(2*f,32),triton.cdiv(h,32))](q,qt,2*f,h,32,num_warps=4)
            self._record('weight_transpose',k)
            result['qt']=qt
        return result

    def forward(self,mode,x,wu,wg,shadow):
        f,h=wu.shape; m=x.shape[0]
        if mode=='B':
            y=x@shadow['packed'].T
            return y[:,:f].contiguous(),y[:,f:].contiguous()
        qx,a=self.quantize(x,'e4m3')
        u=torch.empty((m,f),device=x.device,dtype=torch.bfloat16); g=torch.empty_like(u)
        if mode=='E':
            for i,out in ((0,u),(f,g)):
                w=shadow['q'][i:i+f]; b=shadow['scales'][i:i+f]
                k=_fprop[(triton.cdiv(m,32),triton.cdiv(f,128))](qx,w,a,b,out,out,m,h,f,f,False,*w.stride(),
                    num_warps=4,num_stages=3,enable_fp_fusion=False)
                self._record('fprop_separate',k)
        else:
            w=shadow['q']
            k=_fprop[(triton.cdiv(m,32),triton.cdiv(2*f,128))](qx,w,a,shadow['scales'],u,g,m,h,2*f,f,True,*w.stride(),
                num_warps=4,num_stages=3,enable_fp_fusion=False)
            self._record('fprop_bundle',k)
        return u,g

    def grad_quant(self,du,dg,scales):
        m,f=du.shape
        qe=torch.empty((m,2*f),device=du.device,dtype=torch.float8_e5m2)
        s=torch.empty(m,device=du.device,dtype=torch.float32)
        k=_gradient_quant[(m,)](du,dg,scales,qe,s,self.bad,m,f,*du.stride(),*dg.stride(),triton.next_power_of_2(2*f),
                               num_warps=4,enable_fp_fusion=False)
        self._record('gradient_quant',k)
        return qe,s

    def dgrad(self,mode,du,dg,wu,wg,shadow):
        if mode in ('B','C'):
            return torch.cat((du,dg),1)@shadow['packed']
        qe,s=self.grad_quant(du,dg,shadow['scales'])
        m=du.shape[0]; f,h=wu.shape; qt=shadow['qt']
        out=torch.empty((m,h),device=du.device,dtype=torch.bfloat16)
        if mode=='E':
            parts=[]
            for i in (0,f):
                e=qe[:,i:i+f]; w=qt[:,i:i+f]
                partial=torch.empty((m,h),device=du.device,dtype=torch.float32)
                k=_dgrad[(triton.cdiv(m,32),triton.cdiv(h,128))](e,w,s,partial,m,f,h,*e.stride(),*w.stride(),True,
                    num_warps=4,num_stages=3,enable_fp_fusion=False)
                self._record('dgrad_separate',k); parts.append(partial)
            k=_combine[(triton.cdiv(m*h,256),)](parts[0],parts[1],s,out,m,h,256)
            self._record('combine_dgrad',k)
        else:
            k=_dgrad[(triton.cdiv(m,32),triton.cdiv(h,128))](qe,qt,s,out,m,2*f,h,*qe.stride(),*qt.stride(),False,
                num_warps=4,num_stages=3,enable_fp_fusion=False)
            self._record('dgrad_bundle',k)
        return out

    def instruction_report(self):
        result={}
        for name,kernel in self.compiled.items():
            if name.startswith(('fprop','dgrad')):
                ptx=kernel.asm['ptx']
                native=c.has_fp8_mma(ptx,name.startswith('dgrad'))
                promotion=c.fp32_promotion_report(kernel.asm.get('ttir',''),ptx)
                result[name]=dict(native_fp8_mma=native,fp32_promotion=promotion,ptx_sha256=c.logical_sha(ptx.encode()),
                                  mma_instructions=sorted(set(line.strip().split(' ')[0] for line in ptx.splitlines()
                                      if line.strip().startswith('mma.sync.aligned.'))))
                if not native:
                    raise ValueError('NATIVE_FP8_REQUIRED: '+name)
        required={'fprop_bundle','fprop_separate','dgrad_bundle','dgrad_separate'}
        if not required <= {name.split(':',1)[0] for name in result}:
            raise ValueError('NATIVE_FP8_REQUIRED: not all four matrix kernels executed')
        return result
