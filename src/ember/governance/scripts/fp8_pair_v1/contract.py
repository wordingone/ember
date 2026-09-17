# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""CPU arithmetic oracle and fixed experiment contract; no Triton dependency.

The oracle establishes declared quantization/arithmetic, not GPU bitwise
agreement with historical BF16 reductions and not learning non-inferiority.
"""
from __future__ import annotations
import hashlib
import math
import re
from dataclasses import dataclass
import torch

BASE = 'edc200bef9e459cb41aea0ac6a1016a8b07211e4'
OPERAND_SHA256 = 'e49ad84192da8f1f82b759e9360cba18b39eca2a716550048b08d2aa1197dc76'
LAYERS = (0, 2, 13, 22)
LENGTHS = (1024, 1024, 1024, 1024)
LABELS = ('A', 'A2', 'B', 'C', 'D', 'E')
ROUNDS = 24
CALLS = 2
MIN_REGION_GAIN = .20
MAX_BASELINE_DRIFT = .02
FORMATS = {'e4m3': (torch.float8_e4m3fn, 448.), 'e5m2': (torch.float8_e5m2, 57344.)}
SCALE_FLOOR = 2. ** -126
CLAIM = ('Saved-operand component experiment only: zero optimizer updates, zero applied tokens, '
         'no whole-step speedup, learning qualification or trainer-installation authority.')


def logical_sha(raw: bytes) -> str:
    return hashlib.sha256(raw.replace(b'\r\n', b'\n')).hexdigest()


def quantize_rows(x: torch.Tensor, fmt: str):
    if fmt not in FORMATS:
        raise ValueError('FORMAT: expected e4m3 or e5m2')
    if x.ndim != 2 or min(x.shape) < 1 or not x.is_floating_point():
        raise ValueError('SCHEMA: a nonempty floating matrix is required')
    work = x.detach().float()
    if not bool(torch.isfinite(work).all()):
        raise ValueError('NONFINITE: quantization input')
    dtype, limit = FORMATS[fmt]
    maximum = work.abs().amax(dim=1)
    scale = torch.where(maximum > 0, (maximum / limit).clamp_min(SCALE_FLOOR),
                        torch.ones_like(maximum))
    q = (work / scale[:, None]).clamp(-limit, limit).to(dtype).contiguous()
    return q, scale


def validate_pair(wu, wg):
    if (wu.ndim != 2 or wu.shape != wg.shape or min(wu.shape) < 1
            or wu.dtype != torch.bfloat16 or wg.dtype != torch.bfloat16
            or wu.device != wg.device):
        raise ValueError('PAIR_SCHEMA: aligned BF16 up/gate weights required')


def weight_shadow(wu, wg):
    validate_pair(wu, wg)
    q, scales = quantize_rows(torch.cat((wu.detach(), wg.detach()), 0), 'e4m3')
    # Transpose the bytes, not the dequantized values or an independently rounded copy.
    qt = q.view(torch.uint8).T.contiguous().view(torch.float8_e4m3fn)
    return q, qt, scales


def absorbed_gradient(du, dg, scales):
    if du.ndim != 2 or du.shape != dg.shape or scales.shape != (2 * du.shape[1],):
        raise ValueError('GRAD_SCHEMA: pair gradients and channel scales differ')
    return quantize_rows(torch.cat((du.detach(), dg.detach()), 1).float() * scales, 'e5m2')


def document_wgrad(x, dy, lengths, order, dtype=None):
    """Test-only CPU counterpart of the unchanged source reduction callback."""
    if order not in ('ascending', 'descending') or not lengths or min(lengths) <= 0:
        raise ValueError('DOCUMENTS: explicit order and positive lengths required')
    if x.ndim != 2 or dy.ndim != 2 or x.shape[0] != dy.shape[0] or sum(lengths) != x.shape[0]:
        raise ValueError('DOCUMENTS: rows differ')
    spans, start = [], 0
    for count in lengths:
        spans.append((start, start + count)); start += count
    if order == 'descending':
        spans.reverse()
    total = None
    for start, end in spans:
        partial = dy[start:end].T @ x[start:end]
        total = partial if total is None else total + partial
    return total if dtype is None else total.to(dtype)


@dataclass
class ShadowLease:
    """Host boundary guard. A captured replay must be bracketed by its caller.

    Python is not executed on replay. This does NOT detect an optimizer update
    that a caller hides by failing to advance the explicit generation number.
    The standalone probe has no optimizer and separately tests changed weights.
    """
    generation: int = -1
    active: bool = False

    def refreshed(self, generation):
        if self.active:
            raise ValueError('SHADOW_INFLIGHT: refresh during forward/backward lifetime')
        if type(generation) is not int or generation < 0 or generation < self.generation:
            raise ValueError('SHADOW_GENERATION: invalid or decreasing generation')
        self.generation = generation

    def begin(self, generation):
        if self.active:
            raise ValueError('SHADOW_INFLIGHT: duplicate begin')
        self.require(generation)
        self.active = True

    def require(self, generation):
        if generation != self.generation or self.generation < 0:
            raise ValueError('SHADOW_STALE: generation mismatch')

    def finish(self, generation):
        self.require(generation)
        if not self.active:
            raise ValueError('SHADOW_INFLIGHT: no active lifetime')
        self.active = False


def metrics(actual, expected):
    if actual.shape != expected.shape:
        raise ValueError('METRIC_SCHEMA: shapes differ')
    a, b = actual.detach().double(), expected.detach().double()
    finite = bool(torch.isfinite(a).all() & torch.isfinite(b).all())
    if not finite:
        return dict(finite=False, relative_l2=None, max_abs=None, cosine=None)
    delta = a - b
    an, bn = float(a.norm()), float(b.norm())
    cosine = float((a.flatten() @ b.flatten()) / (an * bn)) if an and bn else None
    return dict(finite=True, relative_l2=float(delta.norm()) / max(bn, 1e-30),
                max_abs=float(delta.abs().max()), cosine=cosine)


def has_fp8_mma(ptx: str, mixed: bool) -> bool:
    # Inspect actual instructions, not comments or metadata naming an FP8 dtype.
    instructions = [line.strip() for line in ptx.splitlines()
                    if line.strip().startswith('mma.sync.aligned.')]
    suffix = '.f32.e5m2.e4m3.f32' if mixed else '.f32.e4m3.e4m3.f32'
    return bool(instructions) and all(suffix in line for line in instructions)



def fp32_promotion_report(ttir: str, ptx: str) -> dict:
    """Require zero-initialized FP8 dot partials and an explicit FP32 add.

    A bounded compiler-format check, not a proof of hardware accuracy. In
    Triton 3.5, CombineDotAdd rewrites acc + dot(A,B,0) to dot(A,B,acc).
    A separate inline-assembly FP32 add prevents that transformation. Verify
    the optimized IR AND the emitted PTX, then retain the numerical gate too.
    Unknown or missing compiler output refuses rather than certifies.
    """
    def refuse(reason):
        raise ValueError('FP32_PROMOTION_REQUIRED: '+reason)

    if not isinstance(ttir,str) or not isinstance(ptx,str):
        refuse('compiler output is not text')
    # Strip comments without counting instruction names mentioned in prose.
    ir_lines=[line.split('//',1)[0].strip() for line in ttir.splitlines()]
    asm_lines=[line.split('//',1)[0].strip() for line in ptx.splitlines()]
    ssa=r'%[A-Za-z0-9_.$]+'
    zeros=set()
    for line in ir_lines:
        match=re.match(r'^('+ssa+r')\s*=\s*arith\.constant\s+dense<([^>]+)>\s*:\s*tensor<',line)
        if match and 'xf32' in line:
            try:
                if float(match.group(2))==0.0:
                    zeros.add(match.group(1))
            except ValueError:
                pass
    dot_lines=[line for line in ir_lines if re.search(r'=\s*tt\.dot\s',line)]
    if not dot_lines:
        refuse('no dot in optimized IR')
    add_lines=[line for line in ir_lines
               if re.search(r'=\s*tt\.elementwise_inline_asm\s',line)
               and '"add.rn.f32 $0, $1, $2;"' in line]
    # Triton's attr-dict PRECEDES operands and can contain typed values such
    # as packed_element = 1 : i32. Splitting on the first " : " discards the
    # operands. Parse the two SSA operands after the attribute dictionary;
    # names in the result, attributes or location are not operand uses.
    quoted = r'"(?:[^"\\]|\\.)*"'
    attributes = r'\{(?:[^{}"]|' + quoted + r')*\}'
    add_pattern = re.compile(
        r'^' + ssa + r'\s*=\s*tt\.elementwise_inline_asm\s+'
        r'"add\.rn\.f32 \$0, \$1, \$2;"\s*' + attributes + r'\s*'
        r'(' + ssa + r')\s*,\s*(' + ssa + r')\s*:')
    add_operands = []
    for line in add_lines:
        operands = add_pattern.match(line)
        if operands is None:
            refuse('unrecognized explicit FP32 add operand syntax')
        add_operands.append(set(operands.groups()))
    for line in dot_lines:
        match=re.match(r'^('+ssa+r')\s*=\s*tt\.dot\s+'+ssa+r'\s*,\s*'+ssa+r'\s*,\s*('+ssa+r')(?=[\s,])',line)
        if not match or match.group(2) not in zeros or 'xf8' not in line:
            refuse('dot is not an FP8 product with a constant-zero accumulator')
        # The addition must consume THIS dot result, not an unrelated value.
        result=match.group(1)
        if not any(result in operands for operands in add_operands):
            refuse('dot result does not reach the explicit FP32 add')
    ptx_adds=sum(bool(re.match(r'^add\.rn\.f32\s',line)) for line in asm_lines)
    if not ptx_adds:
        refuse('no explicit add.rn.f32 in emitted PTX')
    return dict(verified=True,zero_initialized_dots=len(dot_lines),
                fp32_add_boundaries=len(add_lines),ptx_fp32_add_instructions=ptx_adds)


def adjudicate(rows):
    if set(rows) != {str(x) for x in LAYERS}:
        raise ValueError('SUBJECTS: exactly four frozen shared layers are required')
    for row in rows.values():
        for key in ('region_gain', 'block_gain', 'baseline_drift'):
            if type(row[key]) not in (float, int) or not math.isfinite(row[key]):
                raise ValueError('TIMING: nonfinite or nonnumeric measurement')
        if type(row['checks_pass']) is not bool:
            raise ValueError('CHECKS: boolean required')
    checked = all(r['checks_pass'] for r in rows.values())
    quiet = all(r['baseline_drift'] <= MAX_BASELINE_DRIFT for r in rows.values())
    useful = all(r['region_gain'] >= MIN_REGION_GAIN and
                 r['block_gain'] > r['baseline_drift'] for r in rows.values())
    status = ('IMPLEMENTATION_CHECK_FAILED' if not checked else
              'TIMING_INCONCLUSIVE' if not quiet else
              'COMPONENT_SCREEN_PASSED' if useful else 'NO_COMPONENT_GAIN')
    return dict(status=status, implementation_checks_pass=checked,
                baseline_consistent=quiet, learning_qualified=False,
                trainer_integration_authorized=False,
                interpretation='Screening only; local accuracy diagnostics have no learning acceptance margin.')


class CpuOps:
    """Independent eager oracle. It must never be selected by a native GPU probe."""
    def prepare(self, mode, wu, wg):
        validate_pair(wu, wg)
        if mode not in ('B', 'C', 'D', 'E'):
            raise ValueError('MODE: unknown pair arm')
        if mode == 'B':
            return {'packed': torch.cat((wu, wg), 0)}
        q, qt, scales = weight_shadow(wu, wg)
        result = dict(q=q, qt=qt, scales=scales)
        if mode == 'C':
            result['packed'] = torch.cat((wu, wg), 0)
        return result

    def forward(self, mode, x, wu, wg, shadow):
        f = wu.shape[0]
        if mode == 'B':
            y = x @ shadow['packed'].T
            return y[:, :f].contiguous(), y[:, f:].contiguous()
        qx, a = quantize_rows(x, 'e4m3')
        q, b = shadow['q'], shadow['scales']
        if mode == 'E':
            values = [(qx.double() @ q[i:i+f].double().T) * a.double()[:,None] * b[i:i+f].double()
                      for i in (0, f)]
            return tuple(y.to(torch.bfloat16).contiguous() for y in values)
        y = (qx.double() @ q.double().T) * a.double()[:, None] * b.double()
        return y[:,:f].to(torch.bfloat16).contiguous(), y[:,f:].to(torch.bfloat16).contiguous()

    def dgrad(self, mode, du, dg, wu, wg, shadow):
        if mode in ('B','C'):
            return torch.cat((du,dg),1) @ shadow['packed']
        qe, c = absorbed_gradient(du,dg,shadow['scales'])
        qt = shadow['qt']; f = wu.shape[0]
        if mode == 'E':
            out = qe[:,:f].double() @ qt[:,:f].double().T + qe[:,f:].double() @ qt[:,f:].double().T
        else:
            out = qe.double() @ qt.double().T
        return (out * c.double()[:,None]).to(torch.bfloat16)
