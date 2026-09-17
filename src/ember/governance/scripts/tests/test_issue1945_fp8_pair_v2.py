# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""CPU tests for a distinct timing successor. No native speed claims."""
import importlib
import os
from pathlib import Path
import sys
import pytest
import torch

SCRIPTS = Path(__file__).resolve().parents[1]

@pytest.fixture
def m():
    assert (SCRIPTS/'fp8_pair_v2/model.py').is_file(), 'Ada model is not implemented'
    sys.path.insert(0,str(SCRIPTS))
    try:
        return importlib.import_module('fp8_pair_v2.model')
    finally:
        sys.path.pop(0)

@pytest.fixture
def c():
    assert (SCRIPTS/'fp8_pair_v2/contract.py').is_file(), 'v2 contract is not implemented'
    sys.path.insert(0,str(SCRIPTS))
    try:
        return importlib.import_module('fp8_pair_v2.contract')
    finally:
        sys.path.pop(0)

def pair(fmt=torch.float8_e4m3fn, k=64):
    return torch.ones((2,k)).to(fmt), torch.ones((k,3)).to(torch.float8_e4m3fn)

@pytest.mark.parametrize('fmt',[torch.float8_e4m3fn,torch.float8_e5m2])
def test_model_exact_integer_dot(m,fmt):
    a,b=pair(fmt)
    assert torch.equal(m.matmul(a,b),torch.full((2,3),64.))

@pytest.mark.parametrize('fmt',[torch.float8_e4m3fn,torch.float8_e5m2])
def test_model_zero_and_negative(m,fmt):
    a,b=pair(fmt); a=a.float(); a[0]=0; a[1]=-1
    out=m.matmul(a.to(fmt),b)
    assert torch.equal(out,torch.tensor([[0.,0.,0.],[-64.,-64.,-64.]]))

@pytest.mark.parametrize('shape',[(2,16),(0,32),(2,33)])
def test_model_bad_shape_refused(m,shape):
    with pytest.raises(ValueError):
        m.matmul(torch.ones(shape).to(torch.float8_e4m3fn),torch.ones((shape[1],3)).to(torch.float8_e4m3fn))

@pytest.mark.parametrize('fmt',[torch.float32,torch.float16,torch.bfloat16])
def test_model_requires_quantized_types(m,fmt):
    a,b=pair()
    with pytest.raises(ValueError): m.matmul(a.to(fmt),b)

@pytest.mark.parametrize('bad',[float('nan'),float('inf')])
def test_model_refuses_nonfinite(m,bad):
    a,b=pair(); a=a.float(); a[0,0]=bad
    with pytest.raises(ValueError,match='NONFINITE'): m.matmul(a.to(torch.float8_e5m2),b)

def test_model_bounds_work(m):
    a,b=pair(k=64)
    with pytest.raises(ValueError,match='BOUNDED'): m.matmul(a,b,max_products=2)

def test_model_fp8_subnormals(m):
    a=torch.full((1,32),2.**-9).to(torch.float8_e4m3fn)
    b=torch.full((32,1),2.**-16).to(torch.float8_e5m2)
    # Right operand is deliberately not the supported E4M3 weight type.
    with pytest.raises(ValueError): m.matmul(a,b)
    b=torch.full((32,1),2.**-9).to(torch.float8_e4m3fn)
    assert m.matmul(a,b).item()==32*2.**-18

def good_rows():
    return {str(i):dict(region_gain=.30,block_gain=.04,baseline_drift=.001,checks_pass=True)
            for i in (0,2,13,22)}

def test_speed_decision_keeps_learning_unqualified(c):
    v=c.decide(good_rows(),hardware_ok=True,ideal_ok=False)
    assert v['status']=='SPEED_JUSTIFIES_LEARNING_COMPARISON'
    assert v['worth_learning_comparison'] is True
    assert v['original_ideal_gate_passed'] is False
    assert v['learning_qualified'] is False
    assert v['trainer_integration_authorized'] is False

@pytest.mark.parametrize('field,value,status',[
    ('region_gain',.19,'NO_COMPONENT_GAIN'),('block_gain',.0001,'NO_COMPONENT_GAIN'),
    ('baseline_drift',.03,'TIMING_INCONCLUSIVE'),('checks_pass',False,'IMPLEMENTATION_CHECK_FAILED')])
def test_screen_negative_not_hidden(c,field,value,status):
    rows=good_rows(); rows['22'][field]=value
    assert c.decide(rows,hardware_ok=True,ideal_ok=False)['status']==status

def test_hardware_mismatch_stops_timing_decision(c):
    assert c.decide(good_rows(),hardware_ok=False,ideal_ok=False)['status']=='IMPLEMENTATION_CHECK_FAILED'

def test_unknown_layers_refused(c):
    with pytest.raises(ValueError): c.decide({},hardware_ok=True,ideal_ok=False)

@pytest.mark.parametrize('value',[float('nan'),float('inf'),True,'0.3'])
def test_invalid_metrics_refused(c,value):
    rows=good_rows(); rows['0']['region_gain']=value
    with pytest.raises(ValueError): c.decide(rows,hardware_ok=True,ideal_ok=False)

def test_threshold_boundary(c):
    rows=good_rows()
    for r in rows.values(): r.update(region_gain=.20,block_gain=.02,baseline_drift=.02)
    assert c.decide(rows,hardware_ok=True,ideal_ok=False)['status']=='NO_COMPONENT_GAIN'
    for r in rows.values(): r['block_gain']=.020001
    assert c.decide(rows,hardware_ok=True,ideal_ok=False)['status']=='SPEED_JUSTIFIES_LEARNING_COMPARISON'

@pytest.mark.parametrize('label',['ordinary','zero_token','cancellation','outlier_token','unequal_branches'])
def test_model_matches_saved_native_outputs(m,label):
    path=os.environ.get('EMBER_FP8_PRIOR_TENSORS')
    if not path: pytest.skip('Provide the retained b3ea8dd0 tensor archive for empirical replay')
    data=torch.load(path,map_location='cpu',weights_only=True)
    fixture=data[label+'/operands']
    predictions=m.predict_fixture(fixture)
    actual={key.split('/',1)[1]:value for key,value in data.items()
            if key.startswith(label+'/') and not key.endswith('/operands')}
    assert set(predictions)==set(actual)
    for name,record in actual.items():
        assert torch.equal(predictions[name].view(torch.int16),record['actual'].view(torch.int16)), (label,name)


def test_v2_implementation_exists():
    assert (SCRIPTS/"fp8_pair_v2/model.py").is_file()

@pytest.fixture
def n():
    assert (SCRIPTS/'fp8_pair_v2/native.py').is_file(), 'native gate not implemented'
    sys.path.insert(0,str(SCRIPTS))
    try: return importlib.import_module('fp8_pair_v2.native')
    finally: sys.path.pop(0)


def test_fixtures_have_original_names_and_are_independent(n):
    fixtures=n.fixtures(torch)
    assert set(fixtures)=={'ordinary','zero_token','cancellation','outlier_token','unequal_branches'}
    assert fixtures['ordinary'][0].shape==(32,64)
    assert torch.count_nonzero(fixtures['zero_token'][0][0])==0
    assert torch.equal(fixtures['cancellation'][1],fixtures['cancellation'][2])
    assert torch.equal(fixtures['cancellation'][3],-fixtures['cancellation'][4])


def test_new_admission_separates_ideal_but_not_hardware(n):
    good={'quantization':{'x':True},'hardware':{'out':True},'replay':{'ok':True},
          'instructions':{'kernel':True},'ideal':{'old_gate':False}}
    assert n.require_admission(good) is True
    for group in ('quantization','hardware','replay','instructions'):
        bad={k:dict(v) for k,v in good.items()}; bad[group][next(iter(bad[group]))]=False
        with pytest.raises(ValueError): n.require_admission(bad)

@pytest.mark.parametrize('group',['quantization','hardware','replay','instructions'])
def test_missing_admission_group_refuses(n,group):
    flags={'quantization':{'a':True},'hardware':{'a':True},'replay':{'a':True},'instructions':{'a':True},'ideal':{'a':False}}
    flags[group]={}
    with pytest.raises(ValueError): n.require_admission(flags)

@pytest.mark.parametrize('value',[1,'yes',None])
def test_nonboolean_admission_refuses(n,value):
    flags={k:{'a':True} for k in ('quantization','hardware','replay','instructions')}
    flags['hardware']['a']=value
    with pytest.raises(ValueError): n.require_admission(flags)


def test_sample_plan_covers_all_documents_and_branches(n):
    rows,columns,features=n.sample_plan(4096,2048,1024)
    assert rows==(0,1023,1024,2047,2048,3071,3072,4095)
    assert min(columns)<2048 and max(columns)>=2048
    assert columns[0]==0 and columns[-1]==4095
    assert features[0]==0 and features[-1]==1023


def test_v2_runner_exists():
    assert (SCRIPTS/'fp8_pair_v2/runner.py').is_file()

@pytest.fixture
def runner():
    sys.path.insert(0,str(SCRIPTS))
    try: return importlib.import_module('fp8_pair_v2.runner')
    finally: sys.path.pop(0)


def source_fixture(tmp_path,monkeypatch,runner):
    import subprocess
    root=tmp_path/'repo'; root.mkdir()
    hooks=tmp_path/'fixture-hooks'; hooks.mkdir()
    def git(*args):
        return subprocess.run(['git','-c','core.hooksPath='+str(hooks),'-C',str(root),*args],
                              capture_output=True,check=True,timeout=10).stdout.decode().strip()
    git('init'); git('config','user.name','Fixture'); git('config','user.email','fixture@example.invalid')
    git('config','core.autocrlf','false')
    (root/'old.py').write_bytes(b'old=1\n'); (root/'new.py').write_bytes(b'new=2\n')
    git('add','.'); git('commit','-m','fixture')
    head=git('rev-parse','HEAD')
    monkeypatch.setattr(runner.c,'BASE',head)
    monkeypatch.setattr(runner,'PINNED',{'old.py':git('rev-parse','HEAD:old.py')})
    monkeypatch.setattr(runner,'NEW_FILES',['new.py'])
    return root,head,git


def test_source_exact_and_crlf_checkout(runner,tmp_path,monkeypatch):
    root,head,_=source_fixture(tmp_path,monkeypatch,runner)
    assert set(runner.source_binding(root,head))=={'old.py','new.py'}
    (root/'old.py').write_bytes(b'old=1\r\n')
    # The fixture config intentionally treats this as a dirty tracked file.
    with pytest.raises(ValueError,match='not frozen'): runner.source_binding(root,head)


def test_source_pin_rejects_changed_dependency(runner,tmp_path,monkeypatch):
    root,head,git=source_fixture(tmp_path,monkeypatch,runner)
    (root/'old.py').write_bytes(b'old=3\n'); git('add','.'); git('commit','-m','changed')
    with pytest.raises(ValueError,match='pinned dependency'): runner.source_binding(root,git('rev-parse','HEAD'))


def test_source_clears_inherited_hook_context(runner,tmp_path,monkeypatch):
    root,head,_=source_fixture(tmp_path,monkeypatch,runner)
    monkeypatch.setenv('GIT_DIR',str(tmp_path/'not-a-repository'))
    monkeypatch.setenv('GIT_INDEX_FILE',str(tmp_path/'not-an-index'))
    assert set(runner.source_binding(root,head))=={'old.py','new.py'}


def test_source_rejects_new_uncommitted_bytes(runner,tmp_path,monkeypatch):
    root,head,_=source_fixture(tmp_path,monkeypatch,runner)
    (root/'new.py').write_bytes(b'new=9\n')
    with pytest.raises(ValueError,match='not frozen'): runner.source_binding(root,head)

@pytest.mark.parametrize('head',['a'*8,'Z'*40,'0'*40])
def test_source_rejects_bad_identity(runner,tmp_path,monkeypatch,head):
    root,_,_=source_fixture(tmp_path,monkeypatch,runner)
    with pytest.raises(ValueError): runner.source_binding(root,head)


def test_receipt_creation_is_exclusive(runner,tmp_path):
    p=tmp_path/'result.json'; runner.write_new(p,{'a':1})
    with pytest.raises(FileExistsError): runner.write_new(p,{'a':2})
    import json
    assert json.loads(p.read_text())=={'a':1}


def test_nonfinite_json_refused_before_file_creation(runner,tmp_path):
    p=tmp_path/'result.json'
    with pytest.raises(ValueError): runner.write_new(p,{'a':float('nan')})
    assert not p.exists()


def test_both_versions_have_distinct_schema_and_unmodified_gate(runner):
    assert runner.c.BASE=='b3ea8dd0504e2eb9afab4d8939577abaa1bf8e4e'
    text=(SCRIPTS/'fp8_pair_v2/runner.py').read_text()
    assert 'ember-1945-fp8-pair-speed-v2' in text
    assert 'v1.native_checks(' not in text and 'except ValueError: pass' not in text
    assert 'v1.measure_group(' in text
    assert 'v1.make_functions(' in text

@pytest.mark.parametrize('label',['ordinary','zero_token','cancellation','outlier_token','unequal_branches'])
def test_case_gate_against_retained_gpu_output(n,m,label):
    path=os.environ.get('EMBER_FP8_PRIOR_TENSORS')
    if not path: pytest.skip('Retained b3ea8dd0 tensor archive needed')
    data=torch.load(path,map_location='cpu',weights_only=True)
    sys.path.insert(0,str(SCRIPTS))
    try:
        c1=importlib.import_module('fp8_pair_v1.contract')
        v1=importlib.import_module('fp8_pair_v1.probe')
    finally: sys.path.pop(0)
    values=data[label+'/operands']
    class RecordedOps(c1.CpuOps):
        def quantize(self,x,fmt): return c1.quantize_rows(x,fmt)
        def grad_quant(self,du,dg,s): return c1.absorbed_gradient(du,dg,s)
        def require_valid(self): pass
        def forward(self,arm,x,wu,wg,state):
            y=data[label+'/'+arm+'_fprop_oracle']['actual']; f=wu.shape[0]
            return y[:,:f].contiguous(),y[:,f:].contiguous()
        def dgrad(self,arm,*args): return data[label+'/'+arm+'_dgrad_oracle']['actual']
    ops=RecordedOps()
    row,snapshot=n.check_case(torch,ops,c1,v1,m,tuple(values[k] for k in ('x','wu','wg','du','dg')))
    assert all(row['hardware'].values()) and all(row['quantization'].values())
    assert not all(d['passed'] for d in row['ideal'].values())
    assert all(k in snapshot['outputs'] for k in row['hardware'])


def test_model_rejects_corrupt_transpose(m):
    sys.path.insert(0,str(SCRIPTS))
    try: c1=importlib.import_module('fp8_pair_v1.contract')
    finally: sys.path.pop(0)
    wu=torch.ones((32,32),dtype=torch.bfloat16); w,wt,s=c1.weight_shadow(wu,wu)
    fixture={'qx_bytes':torch.ones((1,32)).to(torch.float8_e4m3fn).view(torch.uint8),
        'qw_bytes':w.view(torch.uint8),'qt_bytes':wt.view(torch.uint8).clone(),
        'qe_bytes':torch.ones((1,64)).to(torch.float8_e5m2).view(torch.uint8),
        'activation_scales':torch.ones(1),'weight_scales':s,'gradient_scales':torch.ones(1)}
    fixture['qt_bytes'][0,0]^=1
    with pytest.raises(ValueError,match='transpose'): m.predict_fixture(fixture)


def test_cpu_reference_does_not_fit_hardware_parameters(m):
    import inspect
    text=inspect.getsource(m)
    assert '13-maximum' in text and 'for j in (k,k+16)' in text
    assert 'target' not in inspect.signature(m.matmul).parameters
    assert 'observed' not in inspect.signature(m.matmul).parameters


def test_source_contains_single_goal_markers(runner):
    for rel in runner.NEW_FILES:
        if not rel.endswith('.py'): continue
        path=SCRIPTS.parents[3]/rel
        lines=path.read_text().splitlines()
        assert [x for x in lines if x.startswith('# goal_id:')]==['# goal_id: EMBER-02'], rel
        assert [x for x in lines if x.startswith('# workstream_id:')]==['# workstream_id: EMBER-02A'], rel
        assert [x for x in lines if x.startswith('# next_executed_outcome:')]==[
            '# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember'], rel
