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
