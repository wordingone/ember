# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""CPU checks for the experiment contract, never GPU performance evidence."""
import importlib
from pathlib import Path
import sys
import pytest
import torch

SCRIPTS = Path(__file__).resolve().parents[1]

@pytest.fixture
def modules():
    assert (SCRIPTS / 'fp8_pair_v1/contract.py').is_file(), 'FP8 pair contract has not been implemented'
    sys.path.insert(0, str(SCRIPTS))
    try:
        return (importlib.import_module('fp8_pair_v1.contract'),
                importlib.import_module('fp8_pair_v1.pair'))
    finally:
        sys.path.pop(0)

@pytest.fixture
def operands():
    g = torch.Generator().manual_seed(1045)
    x = torch.randn(8, 16, generator=g).to(torch.bfloat16)
    wu = (torch.randn(32, 16, generator=g) / 8).to(torch.bfloat16)
    wg = (torch.randn(32, 16, generator=g) / 8).to(torch.bfloat16)
    du = torch.randn(8, 32, generator=g).to(torch.bfloat16)
    dg = torch.randn(8, 32, generator=g).to(torch.bfloat16)
    return x, wu, wg, du, dg

@pytest.mark.parametrize('fmt', ['e4m3', 'e5m2'])
def test_zero_rows_use_unit_scale(modules, fmt):
    c, _ = modules
    q, scale = c.quantize_rows(torch.zeros(3, 16), fmt)
    assert torch.equal(scale, torch.ones(3))
    assert torch.count_nonzero(q.float()) == 0

@pytest.mark.parametrize('fmt,limit', [('e4m3', 448.), ('e5m2', 57344.)])
def test_scale_definition(modules, fmt, limit):
    c, _ = modules
    x = torch.tensor([[0., 2., -4.], [1., -8., 2.]])
    q, s = c.quantize_rows(x, fmt)
    assert torch.equal(s, torch.tensor([4.,8.]) / limit)
    assert torch.equal(q.float().abs().amax(1), torch.full((2,), limit))

@pytest.mark.parametrize('bad', [float('inf'), -float('inf'), float('nan')])
def test_nonfinite_rows_refused(modules, bad):
    c, _ = modules
    with pytest.raises(ValueError, match='NONFINITE'):
        c.quantize_rows(torch.tensor([[1., bad]]), 'e4m3')

@pytest.mark.parametrize('fmt', ['e4m3', 'e5m2'])
def test_row_locality(modules, operands, fmt):
    c, _ = modules
    x = operands[0].float()
    q1, s1 = c.quantize_rows(x, fmt)
    x[4:] *= 10000
    q2, s2 = c.quantize_rows(x, fmt)
    assert torch.equal(q1[:4].view(torch.uint8), q2[:4].view(torch.uint8))
    assert torch.equal(s1[:4], s2[:4])

@pytest.mark.parametrize('fmt', ['e4m3', 'e5m2'])
def test_subnormal_scales_are_positive_and_finite(modules, fmt):
    c, _ = modules
    x = torch.full((2, 8), torch.finfo(torch.float32).tiny / 16)
    q, s = c.quantize_rows(x, fmt)
    assert torch.isfinite(s).all() and (s > 0).all()
    assert torch.isfinite(q.float()).all()

@pytest.mark.parametrize('shape', [(16,), (2,3,4), (0,8), (4,0)])
def test_bad_row_schema_refused(modules, shape):
    c, _ = modules
    with pytest.raises(ValueError):
        c.quantize_rows(torch.zeros(shape), 'e4m3')

def test_unknown_format_refused(modules):
    c, _ = modules
    with pytest.raises(ValueError, match='FORMAT'):
        c.quantize_rows(torch.ones(1,2), 'fp4')

def test_dual_shadow_is_identical_bytes_transposed(modules, operands):
    c, _ = modules
    _, wu, wg, *_ = operands
    q, qt, scales = c.weight_shadow(wu, wg)
    assert torch.equal(q.view(torch.uint8).T, qt.view(torch.uint8))
    assert q.is_contiguous() and qt.is_contiguous()
    assert scales.shape == (64,)
    assert wu.dtype == torch.bfloat16 and wg.dtype == torch.bfloat16

def test_weight_scaling_does_not_couple_channels(modules, operands):
    c, _ = modules
    _, wu, wg, *_ = operands
    q1, _, s1 = c.weight_shadow(wu, wg)
    wu2 = wu.clone(); wu2[0] *= 100
    q2, _, s2 = c.weight_shadow(wu2, wg)
    assert torch.equal(q1[1:].view(torch.uint8), q2[1:].view(torch.uint8))
    assert torch.equal(s1[1:], s2[1:])

def test_absorbing_weight_scale_is_an_algebraic_identity(modules, operands):
    c, _ = modules
    _, wu, wg, du, dg = operands
    q, qt, s = c.weight_shadow(wu, wg)
    d = torch.cat((du,dg),1).double()
    direct = d @ (q.double() * s.double()[:,None])
    absorbed = (d * s.double()) @ qt.double().T
    torch.testing.assert_close(direct, absorbed, rtol=1e-12, atol=1e-12)

def test_packed_gradient_scale_is_joint_but_token_local(modules, operands):
    c, _ = modules
    _, wu, wg, du, dg = operands
    _, _, s = c.weight_shadow(wu,wg)
    q, qs = c.absorbed_gradient(du,dg,s)
    expected, es = c.quantize_rows(torch.cat((du,dg),1).float() * s, 'e5m2')
    assert torch.equal(q.view(torch.uint8), expected.view(torch.uint8))
    assert torch.equal(qs, es)
    dg2 = dg.clone(); dg2[7] *= 1000
    q2, qs2 = c.absorbed_gradient(du,dg2,s)
    assert torch.equal(q[:7].view(torch.uint8), q2[:7].view(torch.uint8))
    assert torch.equal(qs[:7], qs2[:7])

@pytest.mark.parametrize('mode', ['B', 'C', 'D', 'E'])
def test_pair_keeps_original_weight_gradient_rule(modules, operands, mode):
    c, p = modules
    x, wu, wg, du, dg = [v.detach().clone().requires_grad_(True) for v in operands]
    ops = c.CpuOps()
    seen = []
    def wgrad(x0,dy,lengths,order,dtype=None):
        seen.append((lengths,order,dtype))
        return c.document_wgrad(x0,dy,lengths,order,dtype)
    shadow = ops.prepare(mode,wu,wg)
    u,g = p.pair(x,wu,wg,mode,ops,shadow,(2,2,2,2),wgrad)
    dx, dwu, dwg = torch.autograd.grad((u,g),(x,wu,wg),grad_outputs=(du,dg))
    assert torch.equal(dwu,c.document_wgrad(x,du,(2,2,2,2),'descending'))
    assert torch.equal(dwg,c.document_wgrad(x,dg,(2,2,2,2),'descending'))
    assert len(seen)==2 and all(row[1]=='descending' for row in seen)
    assert dx.shape == x.shape and dx.dtype == torch.bfloat16
    assert torch.isfinite(dx).all()

@pytest.mark.parametrize('mode', ['B','C','D','E'])
def test_pair_forward_outputs_are_contiguous(modules,operands,mode):
    c,p=modules; x,wu,wg,*_=operands
    ops=c.CpuOps(); s=ops.prepare(mode,wu,wg)
    u,g=p.pair(x,wu,wg,mode,ops,s,(2,2,2,2),c.document_wgrad)
    assert u.is_contiguous() and g.is_contiguous()
    assert u.shape==g.shape==(8,32)

def test_bf16_bundle_is_not_falsely_assumed_bitwise_equal(modules,operands):
    c,p=modules; x,wu,wg,du,dg=operands
    ops=c.CpuOps(); s=ops.prepare('B',wu,wg)
    dx=ops.dgrad('B',du,dg,wu,wg,s)
    expected=torch.cat((du,dg),1)@torch.cat((wu,wg),0)
    assert torch.equal(dx,expected)

def test_nonfinite_weight_refused(modules,operands):
    c,_=modules; _,wu,wg,*_=operands
    wu=wu.clone(); wu[0,0]=float('nan')
    with pytest.raises(ValueError,match='NONFINITE'): c.weight_shadow(wu,wg)

@pytest.mark.parametrize('stage', ['forward','backward'])
def test_refresh_forbidden_during_inflight_lease(modules,stage):
    c,_=modules; lease=c.ShadowLease()
    lease.refreshed(7); lease.begin(7)
    if stage=='backward': lease.require(7)
    with pytest.raises(ValueError,match='INFLIGHT'): lease.refreshed(8)
    lease.finish(7); lease.refreshed(8)

def test_stale_shadow_and_wrong_finish_refused(modules):
    c,_=modules; lease=c.ShadowLease(); lease.refreshed(2)
    with pytest.raises(ValueError,match='STALE'): lease.begin(3)
    lease.begin(2)
    with pytest.raises(ValueError): lease.finish(3)
    lease.finish(2)

def test_baseline_returned_verdict_is_not_learning_qualification(modules):
    c,_=modules
    rows={str(i):{'region_gain':.3,'block_gain':.04,'baseline_drift':.001,
                  'checks_pass':True} for i in (0,2,13,22)}
    verdict=c.adjudicate(rows)
    assert verdict['status']=='COMPONENT_SCREEN_PASSED'
    assert verdict['learning_qualified'] is False and verdict['trainer_integration_authorized'] is False

@pytest.mark.parametrize('what,value,status', [('region_gain',.1,'NO_COMPONENT_GAIN'),
       ('checks_pass',False,'IMPLEMENTATION_CHECK_FAILED'),('block_gain',-.01,'NO_COMPONENT_GAIN'),
       ('baseline_drift',.10,'TIMING_INCONCLUSIVE')])
def test_decisions_fail_closed(modules,what,value,status):
    c,_=modules
    rows={str(i):dict(region_gain=.3,block_gain=.04,baseline_drift=.001,checks_pass=True)
          for i in (0,2,13,22)}
    rows['13'][what]=value
    assert c.adjudicate(rows)['status']==status

def test_missing_layer_refused(modules):
    c,_=modules
    with pytest.raises(ValueError,match='SUBJECTS'): c.adjudicate({})

@pytest.mark.parametrize('value',[float('nan'),float('inf')])
def test_nonfinite_timing_refused(modules,value):
    c,_=modules
    rows={str(i):dict(region_gain=.3,block_gain=value,baseline_drift=.001,checks_pass=True)
          for i in (0,2,13,22)}
    with pytest.raises(ValueError,match='TIMING'): c.adjudicate(rows)

def test_metrics_handle_cancellation_and_zero(modules):
    c,_=modules
    metrics=c.metrics(torch.zeros(2,3),torch.zeros(2,3))
    assert metrics['relative_l2']==0 and metrics['finite']
    ref=torch.tensor([1e-7,0.]); actual=ref+1e-6
    assert c.metrics(actual,ref)['relative_l2']>1

def test_source_hash_normalizes_only_line_endings(modules):
    c,_=modules
    assert c.logical_sha(b'x\r\ny\r\n')==c.logical_sha(b'x\ny\n')
    assert c.logical_sha(b'x\ny\n')!=c.logical_sha(b'x\nY\n')

def test_ptx_gate_accepts_only_native_fp8_formats(modules):
    c,_=modules
    assert c.has_fp8_mma('mma.sync.aligned.m16n8k32.row.col.f32.e4m3.e4m3.f32;',False)
    assert c.has_fp8_mma('mma.sync.aligned.m16n8k32.row.col.f32.e5m2.e4m3.f32;',True)
    assert not c.has_fp8_mma('mma.sync.aligned.m16n8k16.row.col.f32.bf16.bf16.f32;',False)
    assert not c.has_fp8_mma('mma.sync.aligned.m16n8k32.row.col.f32.e4m3.e4m3.f32;',True)

@pytest.mark.parametrize('lengths', [(2,2,4,0),(2,2,2,-2),(8.0,),(),(7,)])
def test_pair_refuses_invalid_document_contract(modules,operands,lengths):
    c,p=modules; x,wu,wg,*_=operands
    ops=c.CpuOps(); s=ops.prepare('B',wu,wg)
    with pytest.raises(ValueError,match='PAIR_SCHEMA'):
        p.pair(x,wu,wg,'B',ops,s,lengths,c.document_wgrad)

def test_pair_refuses_non_bf16_activation(modules,operands):
    c,p=modules; x,wu,wg,*_=operands
    ops=c.CpuOps(); s=ops.prepare('D',wu,wg)
    with pytest.raises(ValueError,match='PAIR_SCHEMA'):
        p.pair(x.float(),wu,wg,'D',ops,s,(2,2,2,2),c.document_wgrad)

@pytest.mark.parametrize('mode',['B','C','D','E'])
def test_one_unused_branch_still_returns_zero_weight_grad(modules,operands,mode):
    c,p=modules
    x,wu,wg,*_=[v.clone().requires_grad_(True) for v in operands]
    ops=c.CpuOps(); state=ops.prepare(mode,wu,wg)
    u,g=p.pair(x,wu,wg,mode,ops,state,(2,2,2,2),c.document_wgrad)
    grads=torch.autograd.grad(u,(x,wu,wg),torch.ones_like(u))
    assert torch.count_nonzero(grads[2])==0


def source_fixture(tmp_path,monkeypatch):
    import subprocess
    probe=importlib.import_module('fp8_pair_v1.probe')
    root=tmp_path/'repo'; root.mkdir()
    hooks=tmp_path/'empty-hooks'; hooks.mkdir()
    def run(*args):
        result=subprocess.run(['git','-c','core.hooksPath='+str(hooks),'-C',str(root),*args],
                              capture_output=True,timeout=10,check=True)
        return result.stdout.decode().strip()
    run('init'); run('config','user.name','FP8 fixture'); run('config','user.email','fixture@example.invalid')
    run('config','core.autocrlf','false')
    (root/'reference.py').write_bytes(b'ref = 1\n')
    (root/'audit.py').write_bytes(b'audit = 2\n')
    run('add','.'); run('commit','-m','fixture')
    head=run('rev-parse','HEAD'); blob=run('rev-parse','HEAD:reference.py')
    monkeypatch.setattr(probe,'BASE',head)
    monkeypatch.setattr(probe,'DEPENDENCIES',{'reference.py':blob})
    monkeypatch.setattr(probe,'NEW_SOURCES',['audit.py'])
    return probe,root,head,run


def test_source_binding_accepts_exact_commit(modules,tmp_path,monkeypatch):
    probe,root,head,_=source_fixture(tmp_path,monkeypatch)
    assert set(probe.source_binding(root,head))=={'reference.py','audit.py'}


def test_source_binding_rejects_wrong_commit(modules,tmp_path,monkeypatch):
    probe,root,head,_=source_fixture(tmp_path,monkeypatch)
    with pytest.raises(ValueError,match='HEAD changed'): probe.source_binding(root,'0'*40)


def test_source_binding_rejects_modified_file(modules,tmp_path,monkeypatch):
    probe,root,head,_=source_fixture(tmp_path,monkeypatch)
    (root/'reference.py').write_bytes(b'ref = 3\n')
    with pytest.raises(ValueError,match='not frozen'): probe.source_binding(root,head)


def test_source_binding_accepts_committed_crlf(modules,tmp_path,monkeypatch):
    probe,root,head,run=source_fixture(tmp_path,monkeypatch)
    (root/'reference.py').write_bytes(b'ref = 1\r\n')
    run('add','.'); run('commit','-m','CRLF fixture')
    head=run('rev-parse','HEAD')
    monkeypatch.setattr(probe,'DEPENDENCIES',{'reference.py':run('rev-parse','HEAD:reference.py')})
    assert probe.source_binding(root,head)


def test_receipt_creation_does_not_overwrite(modules,tmp_path):
    probe=importlib.import_module('fp8_pair_v1.probe')
    path=tmp_path/'receipt.json'
    probe.write_new(path,{'status':'original'})
    with pytest.raises(FileExistsError): probe.write_new(path,{'status':'changed'})
    assert 'original' in path.read_text()


def test_receipt_refuses_nonfinite_before_creating_file(modules,tmp_path):
    probe=importlib.import_module('fp8_pair_v1.probe')
    path=tmp_path/'receipt.json'
    with pytest.raises(ValueError): probe.write_new(path,{'time':float('nan')})
    assert not path.exists()

@pytest.mark.parametrize('region',[True,False])
def test_complete_callable_arms_leave_parameter_owners_unchanged(modules,operands,region):
    from types import SimpleNamespace
    import torch.nn.functional as F
    c,p=modules
    probe=importlib.import_module('fp8_pair_v1.probe')
    class ReferenceLinear(torch.autograd.Function):
        @staticmethod
        def forward(ctx,x,w,lengths,order):
            ctx.save_for_backward(x,w); ctx.lengths=lengths; ctx.order=order
            return F.linear(x,w)
        @staticmethod
        def backward(ctx,dy):
            x,w=ctx.saved_tensors
            return dy@w,c.document_wgrad(x,dy,ctx.lengths,ctx.order,w.dtype),None,None
    source=SimpleNamespace(document_reduced_linear=ReferenceLinear.apply,reduce_weight_gradient=c.document_wgrad)
    x,wu,wg,du,dg=[v.detach().clone().requires_grad_(True) for v in operands]
    wd=torch.randn(16,32).to(torch.bfloat16).requires_grad_(True)
    dy=torch.randn_like(x)
    snapshot=[t.detach().clone() for t in (x,wu,wg,wd)]
    functions=probe.make_functions(torch,F,source,p.pair,c.CpuOps(),x,wu,wg,wd,dy,du,dg,(2,2,2,2),region)
    outputs={label:fn() for label,fn in functions.items()}
    assert probe.tuple_equal(torch,outputs['A'],outputs['A2'])
    for tensors in outputs.values():
        assert len(tensors)==(3 if region else 5)
        assert all(torch.isfinite(t).all() for t in tensors)
    assert all(torch.equal(t,s) and t.grad is None for t,s in zip((x,wu,wg,wd),snapshot))


@pytest.mark.parametrize('kernel_name,operand', [
    ('_transpose', 'Q'),
    ('_fprop', 'QX'), ('_fprop', 'QW'),
    ('_dgrad', 'QE'), ('_dgrad', 'QT'),
])
def test_fp8_masked_load_uses_floating_zero(kernel_name, operand):
    """Triton 3.5 cannot cast integer padding directly to an FP8 element.

    This source regression check does not assert GPU compilation or execution.
    It prevents recurrence in every FP8 operand load, not only the transpose.
    """
    import ast
    tree = ast.parse((SCRIPTS / 'fp8_pair_v1/kernels.py').read_text(encoding='utf-8'))
    function = next(node for node in tree.body
                    if isinstance(node, ast.FunctionDef) and node.name == kernel_name)
    loads = [node for node in ast.walk(function)
             if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Attribute)
             and isinstance(node.func.value, ast.Name)
             and node.func.value.id == 'tl' and node.func.attr == 'load'
             and node.args
             and any(isinstance(arg, ast.Name) and arg.id == operand
                     for arg in ast.walk(node.args[0]))]
    assert len(loads) == 1, (kernel_name, operand, 'expected exactly one load')
    padding = next((keyword.value for keyword in loads[0].keywords
                    if keyword.arg == 'other'), None)
    assert (isinstance(padding, ast.Constant)
            and type(padding.value) is float and padding.value == 0.0), (
                kernel_name, operand, 'FP8 masked-load padding must be floating zero')


def _fp8_aot_cases(kernel_name):
    """Exact capability/full-shape compile signatures; never allocate CUDA tensors."""
    cases = []
    for label, m, h, f in (('capability', 32, 64, 128), ('full', 4096, 1024, 2048)):
        options = dict(num_warps=4, num_stages=3, enable_fp_fusion=False)
        if kernel_name == '_row_quant':
            for fmt, dtype, limit in (('e4m3', '*fp8e4nv', 448.), ('e5m2', '*fp8e5', 57344.)):
                cases.append((label+'-'+fmt,
                    dict(X='*bf16', Q=dtype, S='*fp32', BAD='*i32'),
                    dict(R=m, C=h, X0=h, X1=1, LIMIT=limit, BLOCK=h), options))
        elif kernel_name == '_weight_quant':
            cases.append((label,
                dict(WU='*bf16', WG='*bf16', Q='*fp8e4nv', S='*fp32', BAD='*i32'),
                dict(F=f, H=h, U0=h, U1=1, G0=h, G1=1, BLOCK=h), options))
        elif kernel_name == '_transpose':
            cases.append((label, dict(Q='*fp8e4nv', QT='*fp8e4nv'),
                dict(R=2*f, C=h, BLOCK=32), dict(num_warps=4)))
        elif kernel_name == '_gradient_quant':
            cases.append((label,
                dict(DU='*bf16', DG='*bf16', W_SCALE='*fp32', QE='*fp8e5',
                     C_SCALE='*fp32', BAD='*i32'),
                dict(M=m, F=f, U0=f, U1=1, G0=f, G1=1, BLOCK=2*f), options))
        elif kernel_name == '_fprop':
            for bundled in (True, False):
                cases.append((label+('-bundled' if bundled else '-separate'),
                    dict(QX='*fp8e4nv', QW='*fp8e4nv', A='*fp32', B='*fp32',
                         U='*bf16', G='*bf16'),
                    dict(M=m, H=h, N=2*f if bundled else f, F=f, SPLIT=bundled,
                         W0=h, W1=1, BM=32, BN=128, BK=32), options))
        elif kernel_name == '_dgrad':
            for partial in (False, True):
                cases.append((label+('-separate' if partial else '-bundled'),
                    dict(QE='*fp8e5', QT='*fp8e4nv', S='*fp32',
                         OUT='*fp32' if partial else '*bf16'),
                    dict(M=m, K=f if partial else 2*f, N=h, E0=2*f, E1=1,
                         T0=2*f, T1=1, PARTIAL=partial, BM=32, BN=128, BK=32), options))
        elif kernel_name == '_combine':
            cases.append((label, dict(A='*fp32', B='*fp32', S='*fp32', Y='*bf16'),
                          dict(M=m, H=h, BLOCK=256), dict(num_warps=4)))
        else:
            raise AssertionError('Unknown kernel in the compile-only census: '+kernel_name)
    if kernel_name == '_transpose':
        cases.append(('masked-edges', dict(Q='*fp8e4nv', QT='*fp8e4nv'),
                      dict(R=33, C=65, BLOCK=32), dict(num_warps=4)))
    return cases


_FP8_NATIVE_KERNELS = ('_row_quant', '_weight_quant', '_transpose',
                       '_gradient_quant', '_fprop', '_dgrad', '_combine')


@pytest.mark.parametrize('kernel_name', _FP8_NATIVE_KERNELS)
def test_aot_case_signatures_cover_the_actual_kernel(kernel_name):
    """Keep the no-GPU compiler regression inputs synchronized with source."""
    import ast
    tree = ast.parse((SCRIPTS / 'fp8_pair_v1/kernels.py').read_text(encoding='utf-8'))
    function = next(node for node in tree.body
                    if isinstance(node, ast.FunctionDef) and node.name == kernel_name)
    arguments = {arg.arg for arg in function.args.args}
    constant_names = {arg.arg for arg in function.args.args
                      if isinstance(arg.annotation, ast.Attribute)
                      and arg.annotation.attr == 'constexpr'}
    for label, pointers, constants, _ in _fp8_aot_cases(kernel_name):
        assert set(constants) == constant_names, (kernel_name, label)
        assert set(pointers).isdisjoint(constants)
        assert set(pointers) | set(constants) == arguments, (kernel_name, label)


@pytest.mark.parametrize('kernel_name', _FP8_NATIVE_KERNELS)
def test_native_sm89_compilation_without_gpu(kernel_name, modules, tmp_path, monkeypatch):
    """Opt-in compiler-only regression. Does not launch or qualify any GPU work.

    Explicit target avoids active-device discovery. Any attempted Triton driver
    access or PyTorch CUDA initialization fails the test, rather than allocating
    on the card without the governed GPU launcher.
    """
    import os
    if os.environ.get('EMBER_FP8_AOT_CHECK') != '1':
        pytest.skip('Set EMBER_FP8_AOT_CHECK=1 for compiler-only SM89 regression')
    import triton
    from triton.backends.compiler import GPUTarget
    from triton.compiler import ASTSource
    assert triton.__version__ == '3.5.0', 'Compiler check requires frozen Triton 3.5.0'
    assert not torch.cuda.is_initialized(), 'Run compiler-only tests in a fresh process'

    class NoGpuDriver:
        def __getattr__(self, name):
            raise AssertionError('Compiler-only test attempted GPU driver access: '+name)

    def refuse_cuda(*args, **kwargs):
        raise AssertionError('Compiler-only test attempted PyTorch CUDA initialization')

    monkeypatch.setattr(triton.runtime.driver, '_active', NoGpuDriver())
    monkeypatch.setattr(torch.cuda, '_lazy_init', refuse_cuda)
    kernels = importlib.import_module('fp8_pair_v1.kernels')
    kernel = getattr(kernels, kernel_name)
    target = GPUTarget('cuda', 89, 32)
    c, _ = modules
    for label, pointers, constants, options in _fp8_aot_cases(kernel_name):
        signature = {name: 'constexpr' if name in constants else pointers[name]
                     for name in kernel.arg_names}
        source = ASTSource(fn=kernel, signature=signature, constexprs=constants)
        compiled = triton.compile(source, target=target, options=options)
        ptx = compiled.asm['ptx']
        # Retain successful compiler output even if a subsequent verifier fails.
        for extension in ('ttir', 'ptx'):
            (tmp_path / (kernel_name+'-'+label+'.'+extension)).write_text(
                compiled.asm[extension], encoding='utf-8')
        assert '.target sm_89' in ptx
        assert compiled.asm['cubin'], 'Compiler did not produce a CUDA binary'
        if kernel_name in ('_fprop', '_dgrad'):
            assert c.has_fp8_mma(ptx, kernel_name == '_dgrad'), (kernel_name, label)
            assert c.fp32_promotion_report(compiled.asm['ttir'],ptx)['verified'], (kernel_name,label)
    assert not torch.cuda.is_initialized()


def test_oracle_diagnostics_helper_exists(modules):
    probe = importlib.import_module('fp8_pair_v1.probe')
    assert callable(getattr(probe, 'oracle_diagnostics', None)), 'Missing element-level oracle diagnostics'


@pytest.mark.parametrize('case', ['exact', 'error', 'zero', 'cancellation', 'nan', 'inf'])
def test_oracle_diagnostics_reproduce_original_gate(modules, case):
    import json
    probe = importlib.import_module('fp8_pair_v1.probe')
    helper = getattr(probe, 'oracle_diagnostics', None)
    assert callable(helper), 'Missing element-level oracle diagnostics'
    reference = torch.tensor([[0., 1., -2.], [3., 1e-6, -4.]], dtype=torch.float64)
    bound = reference.abs() + 1
    actual = reference.to(torch.bfloat16)
    if case == 'error': actual[0, 1] = 1.25
    elif case == 'zero': actual.zero_(); reference.zero_(); bound.zero_()
    elif case == 'cancellation': actual[1, 1] = .001; bound[1, 1] = 100
    elif case == 'nan': actual[0, 1] = float('nan')
    elif case == 'inf': actual[0, 1] = float('inf')
    original = [t.clone() for t in (actual, reference, bound)]
    detail = helper(torch, actual, reference, bound)
    assert detail['passed'] is probe.oracle_close(torch, actual, reference, bound)
    assert detail['failed_elements'] == sum(detail['row_failed_elements'])
    assert detail['failed_elements'] == sum(detail['column_failed_elements'])
    json.dumps(detail, allow_nan=False)
    for before, after in zip(original, (actual, reference, bound)):
        torch.testing.assert_close(before, after, rtol=0, atol=0, equal_nan=True)


def test_oracle_diagnostics_locates_error_and_reports_original_limit(modules):
    probe = importlib.import_module('fp8_pair_v1.probe')
    helper = getattr(probe, 'oracle_diagnostics', None)
    assert callable(helper), 'Missing element-level oracle diagnostics'
    reference = torch.ones(2, 3, dtype=torch.float64)
    bound = reference.clone()
    actual = reference.to(torch.bfloat16); actual[1, 2] = 2
    result = helper(torch, actual, reference, bound)
    assert not result['passed'] and result['failed_elements'] == 1
    assert result['worst_element']['index'] == [1, 2]
    assert result['worst_element']['actual'] == 2
    assert result['worst_element']['rounded_reference'] == 1
    assert result['worst_element']['tolerance'] == pytest.approx(1/128+1e-6+1e-30)
    assert result['max_abs_error'] == 1


def test_oracle_diagnostics_rejects_shape_broadcasting(modules):
    probe = importlib.import_module('fp8_pair_v1.probe')
    helper = getattr(probe, 'oracle_diagnostics', None)
    assert callable(helper), 'Missing element-level oracle diagnostics'
    with pytest.raises(ValueError, match='ORACLE_DIAGNOSTIC_SCHEMA'):
        helper(torch, torch.ones(2, 3), torch.ones(1, 3), torch.ones(2, 3))


def test_native_oracle_failure_keeps_diagnostics_and_return_value(modules, tmp_path):
    probe = importlib.import_module('fp8_pair_v1.probe')
    observe = getattr(probe, 'record_oracle', None)
    finish = getattr(probe, 'finish_native_checks', None)
    assert callable(observe) and callable(finish), 'Missing failure evidence retention'
    reference = torch.ones(2, 3, dtype=torch.float64)
    actual = torch.full((2, 3), 2., dtype=torch.bfloat16)
    checks = {'ordinary': {'D_fprop_oracle': False}, 'native_instructions': {}}
    details, snapshots = {}, {}
    assert observe(torch, details, snapshots, 'ordinary', 'D_fprop_oracle',
                   actual, reference, reference) is False
    actual.zero_()
    assert snapshots['ordinary/D_fprop_oracle']['actual'].eq(2).all()
    class FakeOps:
        compiled = {}
    with pytest.raises(ValueError, match='NATIVE_CHECK_FAILED'):
        finish(torch, tmp_path, checks, details, snapshots, FakeOps())
    assert (tmp_path/'native-checks.json').is_file()
    assert (tmp_path/'native-oracle-diagnostics.json').is_file()
    saved = torch.load(tmp_path/'native-oracle-tensors.pt', weights_only=True)
    assert saved['ordinary/D_fprop_oracle']['actual'].eq(2).all()
    import json
    report = json.loads((tmp_path/'native-oracle-diagnostics.json').read_text())
    assert report['tensor_archive_sha256'] == probe.file_sha(tmp_path/'native-oracle-tensors.pt')
    # A second call cannot rewrite the first failure's evidence.
    with pytest.raises(FileExistsError):
        finish(torch, tmp_path, checks, details, snapshots, FakeOps())


def test_native_oracle_success_keeps_codegen_without_executing_it(modules, tmp_path):
    import types
    import json
    probe = importlib.import_module('fp8_pair_v1.probe')
    finish = getattr(probe, 'finish_native_checks', None)
    assert callable(finish), 'Missing failure evidence retention'
    ops = types.SimpleNamespace(compiled={
        'fprop_bundle:abc': types.SimpleNamespace(asm={'ptx': 'ptx bytes', 'ttir': 'ttir bytes'}),
        'dgrad_bundle:def': types.SimpleNamespace(asm={'ptx': 'mixed ptx bytes'}),
    })
    checks = {'ordinary': {'D_fprop_oracle': True}, 'native_instructions': {}}
    assert finish(torch, tmp_path, checks, {}, {}, ops) is checks
    assert (tmp_path/'fprop_bundle-abc.ptx').read_text() == 'ptx bytes'
    assert (tmp_path/'fprop_bundle-abc.ttir').read_text() == 'ttir bytes'
    report = json.loads((tmp_path/'native-oracle-diagnostics.json').read_text())
    assert report['codegen_sha256']['fprop_bundle-abc.ptx'] == probe.file_sha(tmp_path/'fprop_bundle-abc.ptx')


def test_diagnostic_instrumentation_never_changes_frozen_oracle(modules):
    import ast
    import textwrap
    probe_source = (SCRIPTS/'fp8_pair_v1/probe.py').read_text(encoding='utf-8')
    tree = ast.parse(probe_source)
    actual = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'oracle_close')
    expected = ast.parse(textwrap.dedent('''\
        def oracle_close(torch,actual,reference64,bound64):
            ref=reference64.to(torch.bfloat16).double()
            tolerance=ref.abs()/128 + bound64*1e-6 + 1e-30
            return bool(torch.isfinite(actual).all() and ((actual.double()-ref).abs()<=tolerance).all())
    ''')).body[0]
    assert ast.dump(actual, include_attributes=False) == ast.dump(expected, include_attributes=False)


@pytest.mark.parametrize('kernel_name', ['_fprop', '_dgrad'])
def test_fp8_partial_sums_have_explicit_fp32_add_boundary(kernel_name):
    """Plain acc + dot is combined into dot(acc) even with FP fusion disabled."""
    import ast
    tree = ast.parse((SCRIPTS/'fp8_pair_v1/kernels.py').read_text(encoding='utf-8'))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == kernel_name)
    additions = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Attribute)
                 and isinstance(n.func.value, ast.Name)
                 and n.func.value.id == 'tl' and n.func.attr == 'inline_asm_elementwise']
    assert len(additions) == 1, 'Each reduction loop needs its own non-fusible FP32 addition'
    kw = {x.arg: x.value for x in additions[0].keywords}
    assert ast.literal_eval(kw['asm']) == 'add.rn.f32 $0, $1, $2;'
    assert ast.literal_eval(kw['constraints']) == '=f,f,f'
    assert [n.id for n in kw['args'].elts] == ['acc', 'partial']
    assert ast.unparse(kw['dtype']) == 'tl.float32'
    assert ast.literal_eval(kw['is_pure']) is True
    assert ast.literal_eval(kw['pack']) == 1
    assert not any(isinstance(n, ast.BinOp) and isinstance(n.op, ast.Add)
                   and {ast.unparse(n.left), ast.unparse(n.right)} == {'acc','partial'}
                   for n in ast.walk(fn))


def _promotion_fixture():
    # Reduced compiler-format example: not a performance result or executed kernel.
    ir = '''
%zero = arith.constant dense<0.000000e+00> : tensor<32x128xf32>
%partial = tt.dot %left, %right, %zero, inputPrecision = tf32 : tensor<32x32xf8E4M3FN> * tensor<32x128xf8E4M3FN> -> tensor<32x128xf32>
%sum = tt.elementwise_inline_asm "add.rn.f32 $0, $1, $2;" {constraints = "=f,f,f", packed_element = 1 : i32, pure = true} %running, %partial : tensor<32x128xf32>, tensor<32x128xf32> -> tensor<32x128xf32>
'''
    ptx = 'mma.sync.aligned.m16n8k32.row.col.f32.e4m3.e4m3.f32 {d}, {a}, {b}, {z};\nadd.rn.f32 %f0, %f1, %f2;\n'
    return ir, ptx


def _promotion_checker(modules):
    c, _ = modules
    check = getattr(c, 'fp32_promotion_report', None)
    assert callable(check), 'Missing emitted-code FP32-promotion check'
    return check


def test_emitted_promotion_checker_accepts_zero_dot_plus_add(modules):
    report = _promotion_checker(modules)(*_promotion_fixture())
    assert report['zero_initialized_dots'] == 1
    assert report['fp32_add_boundaries'] == 1
    assert report['verified'] is True


@pytest.mark.parametrize('defect', ['carried_accumulator', 'nonzero_constant', 'missing_ir_add',
                                   'unrelated_ir_add', 'missing_ptx_add', 'comment_only',
                                   'missing_dot', 'non_fp32_add', 'plain_add'])
def test_emitted_promotion_checker_refuses_lost_boundary(modules, defect):
    check = _promotion_checker(modules)
    ir, ptx = _promotion_fixture()
    if defect == 'carried_accumulator': ir = ir.replace('%right, %zero', '%right, %running')
    elif defect == 'nonzero_constant': ir = ir.replace('0.000000e+00', '1.000000e+00')
    elif defect == 'missing_ir_add': ir = '\n'.join(x for x in ir.splitlines() if 'inline_asm' not in x)
    elif defect == 'unrelated_ir_add': ir = ir.replace('%running, %partial :', '%running, %unrelated :')
    elif defect == 'missing_ptx_add': ptx = ptx.splitlines()[0]
    elif defect == 'comment_only': ptx = ptx.splitlines()[0] + '\n// add.rn.f32 %f0, %f1, %f2;'
    elif defect == 'missing_dot': ir = '\n'.join(x for x in ir.splitlines() if 'tt.dot' not in x)
    elif defect == 'non_fp32_add': ir = ir.replace('add.rn.f32', 'add.rn.f16')
    elif defect == 'plain_add': ir = ir.replace('tt.elementwise_inline_asm', 'arith.addf')
    with pytest.raises(ValueError, match='FP32_PROMOTION_REQUIRED'):
        check(ir, ptx)


def test_emitted_promotion_guard_is_called_by_runtime_and_aot():
    import ast
    tree = ast.parse((SCRIPTS/'fp8_pair_v1/kernels.py').read_text(encoding='utf-8'))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'NativeOps')
    fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'instruction_report')
    calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute) and n.func.attr == 'fp32_promotion_report']
    assert len(calls) == 1, 'Native instruction report must check promotion as well as FP8 opcodes'
    test_tree = ast.parse(Path(__file__).read_text(encoding='utf-8'))
    aot = next(n for n in test_tree.body if isinstance(n, ast.FunctionDef)
               and n.name == 'test_native_sm89_compilation_without_gpu')
    assert any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and n.func.attr == 'fp32_promotion_report' for n in ast.walk(aot))


@pytest.mark.parametrize('attributes', [
    'constraints = "=f,f,f", packed_element = 1 : i32, pure = true',
    'packed_element = 1 : i32, pure = true, constraints = "=f,f,f"',
    'pure = true, constraints = "=f,f,f", packed_element = 1 : i32',
])
def test_promotion_parser_accepts_typed_inline_asm_attributes(modules, attributes):
    """Regression: the first colon belongs to an attribute, not the operands.

    This reduced fixture follows Triton 3.5 TritonOps.td's assembly format;
    it is not represented as an emitted or executed kernel.
    """
    ir, ptx = _promotion_fixture()
    canonical = 'constraints = "=f,f,f", packed_element = 1 : i32, pure = true'
    ir = ir.replace(canonical, attributes)
    report = _promotion_checker(modules)(ir, ptx)
    assert report['verified'] and report['fp32_add_boundaries'] == 1


@pytest.mark.parametrize('operand', ['%partial_extra', '%partial.1', '%other'])
def test_promotion_parser_requires_exact_operand_identity(modules, operand):
    ir, ptx = _promotion_fixture()
    ir = ir.replace('%running, %partial :', '%running, '+operand+' :')
    with pytest.raises(ValueError, match='FP32_PROMOTION_REQUIRED'):
        _promotion_checker(modules)(ir, ptx)


@pytest.mark.parametrize('location', ['result', 'attribute', 'source_location'])
def test_promotion_parser_ignores_nonoperand_mentions(modules, location):
    ir, ptx = _promotion_fixture()
    ir = ir.replace('%running, %partial :', '%running, %other :')
    if location == 'result':
        # An invalid redefinition must not count as use of the dot result.
        ir = ir.replace('%sum = tt.elementwise_inline_asm', '%partial = tt.elementwise_inline_asm')
    elif location == 'attribute':
        ir = ir.replace('packed_element = 1 : i32', 'note = "%partial", packed_element = 1 : i32')
    else:
        ir = ir.rstrip() + ' loc("%partial")\n'
    with pytest.raises(ValueError, match='FP32_PROMOTION_REQUIRED'):
        _promotion_checker(modules)(ir, ptx)


@pytest.mark.parametrize('missing', ['first', 'second'])
def test_promotion_parser_checks_every_dot(modules, missing):
    ir, ptx = _promotion_fixture()
    dot = next(x for x in ir.splitlines() if ' = tt.dot ' in x)
    add = next(x for x in ir.splitlines() if ' = tt.elementwise_inline_asm ' in x)
    ir += dot.replace('%partial =', '%second =') + '\n'
    ir += add.replace('%sum =', '%sum2 =').replace('%partial :', '%second :') + '\n'
    name = '%partial' if missing == 'first' else '%second'
    ir = ir.replace('%running, '+name+' :', '%running, %other :')
    with pytest.raises(ValueError, match='FP32_PROMOTION_REQUIRED'):
        _promotion_checker(modules)(ir, ptx)


def test_promotion_parser_rejects_malformed_attribute_dictionary(modules):
    ir, ptx = _promotion_fixture()
    ir = ir.replace('pure = true}', 'pure = true')
    with pytest.raises(ValueError, match='FP32_PROMOTION_REQUIRED'):
        _promotion_checker(modules)(ir, ptx)
