# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Direct-conversion regression; CPU tests are not GPU execution evidence."""
import ast
import importlib
import os
from pathlib import Path
import sys
import pytest
import torch

SCRIPTS=Path(__file__).resolve().parents[1]

@pytest.fixture
def checks():
    assert (SCRIPTS/'fp8_pair_v2/quantization_checks.py').is_file(), 'direct quantization checks missing'
    sys.path.insert(0,str(SCRIPTS))
    try: return importlib.import_module('fp8_pair_v2.quantization_checks')
    finally: sys.path.pop(0)

@pytest.mark.parametrize('fmt',['e4m3','e5m2'])
def test_rounding_cases_have_unit_scale_and_finite_inputs(checks,fmt):
    sys.path.insert(0,str(SCRIPTS))
    try: c=importlib.import_module('fp8_pair_v1.contract')
    finally: sys.path.pop(0)
    cases=checks.rounding_inputs(torch,fmt)
    assert cases.ndim==2 and cases.shape[1]==1024 and torch.isfinite(cases).all()
    q,s=c.quantize_rows(cases,fmt)
    assert torch.equal(s,torch.ones_like(s))
    assert torch.equal(q.view(torch.uint8),cases.to(c.FORMATS[fmt][0]).view(torch.uint8))

@pytest.mark.parametrize('fmt',['e4m3','e5m2'])
def test_rounding_cases_cover_ties_both_signs_and_zero(checks,fmt):
    x=checks.rounding_inputs(torch,fmt)
    tie=1.0625 if fmt=='e4m3' else 1.125
    for value in (tie,-tie,0.): assert bool((x==value).any())
    assert bool(((x==0)&torch.signbit(x)).any())
    assert bool(((x==0)&~torch.signbit(x)).any())
    # Move each sequence through all four packed positions without altering values.
    assert x.shape[0]==4
    assert torch.equal(x[0].sort().values,x[3].sort().values)

@pytest.mark.parametrize('fmt',['e4m3','e5m2'])
def test_direct_ptx_gate_accepts_requested_format(checks,fmt):
    suffix='e4m3' if fmt=='e4m3' else 'e5m2'
    ptx='.version 8.5\n.target sm_89\ncvt.rn.satfinite.'+suffix+'x2.f32 lo, %f2, %f1;'
    assert checks.check_direct_ptx(ptx,fmt)['verified']

@pytest.mark.parametrize('bad',[
    '// cvt.rn.satfinite.e4m3x2.f32 lo, %f2, %f1;',
    'cvt.rn.satfinite.e5m2x2.f32 lo, %f2, %f1;',
    'cvt.rn.satfinite.e4m3x2.f16x2 lo, %r1;',
    'add.u32 c2, c2, lsb1;',
])
def test_direct_ptx_gate_rejects_missing_or_wrong_conversion(checks,bad):
    with pytest.raises(ValueError,match='DIRECT_FP8'):
        checks.check_direct_ptx('.version 8.5\n.target sm_89\n'+bad,'e4m3')


def test_direct_primitive_cannot_reuse_peer_rounding_bit():
    path=SCRIPTS/'fp8_pair_v2/quantizers.py'
    assert path.is_file(), 'corrected primitives missing'
    tree=ast.parse(path.read_text(encoding='utf-8'))
    fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_encode_fp32')
    text=ast.get_source_segment(path.read_text(),fn)
    assert 'cvt.rn.satfinite.e4m3x2.f32 lo, $2, $1;' in text
    assert 'cvt.rn.satfinite.e4m3x2.f32 hi, $4, $3;' in text
    assert 'cvt.rn.satfinite.e5m2x2.f32 lo, $2, $1;' in text
    assert 'cvt.rn.satfinite.e5m2x2.f32 hi, $4, $3;' in text
    assert 'mov.b32 $0, {lo, hi};' in text and 'pack=4' in text
    assert 'lsb' not in text


@pytest.mark.parametrize('name',['_row_quant','_weight_quant','_gradient_quant'])
def test_scale_math_and_masks_match_frozen_primitives(name):
    path=SCRIPTS/'fp8_pair_v2/quantizers.py'
    assert path.is_file(), 'corrected primitives missing'
    oldtree=ast.parse((SCRIPTS/'fp8_pair_v1/kernels.py').read_text())
    newtree=ast.parse(path.read_text())
    old=next(n for n in oldtree.body if isinstance(n,ast.FunctionDef) and n.name==name)
    new=next(n for n in newtree.body if isinstance(n,ast.FunctionDef) and n.name==name)
    # Only the final numeric downcast is replaced by the declared byte conversion.
    class StripEncoding(ast.NodeTransformer):
        def visit_Call(self,node):
            if isinstance(node.func,ast.Name) and node.func.id=='_encode_fp32':
                return ast.Name(id='QUANTIZED',ctx=ast.Load())
            if (isinstance(node.func,ast.Attribute) and node.func.attr=='to'
                and any(k.arg=='fp_downcast_rounding' for k in node.keywords)):
                return ast.Name(id='QUANTIZED',ctx=ast.Load())
            return self.generic_visit(node)
    assert ast.dump(StripEncoding().visit(old))==ast.dump(StripEncoding().visit(new))


def test_native_matrix_implementations_are_inherited_unchanged():
    path=SCRIPTS/'fp8_pair_v2/quantizers.py'
    assert path.is_file()
    tree=ast.parse(path.read_text())
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='NativeOps')
    names={n.name for n in cls.body if isinstance(n,ast.FunctionDef)}
    assert not names.intersection({'forward','dgrad','require_valid','instruction_report'})
    assert {'quantize','prepare','grad_quant','quantization_report'}<=names


def test_source_binding_and_runtime_use_corrected_primitives():
    sys.path.insert(0,str(SCRIPTS))
    try: runner=importlib.import_module('fp8_pair_v2.runner')
    finally: sys.path.pop(0)
    assert str('src/ember/governance/scripts/fp8_pair_v2/quantizers.py') in runner.NEW_FILES
    text=(SCRIPTS/'fp8_pair_v2/runner.py').read_text()
    assert "ops=quantizers.NativeOps('cuda:0')" in text
    assert "ops=kernels.NativeOps('cuda:0')" not in text


@pytest.mark.parametrize('which',['good','corrupt'])
def test_rounding_admission_and_evidence(checks,tmp_path,which):
    sys.path.insert(0,str(SCRIPTS))
    try: c=importlib.import_module('fp8_pair_v1.contract')
    finally: sys.path.pop(0)
    class Ops:
        def quantize(self,x,fmt):
            q,s=c.quantize_rows(x,fmt)
            if which=='corrupt': q.view(torch.uint8)[0,2]^=1
            return q,s
        def require_valid(self): pass
    result,tensors=checks.run_rounding_checks(torch,Ops(),c,device='cpu')
    assert set(result)=={'e4m3','e5m2'} and set(tensors)=={'e4m3','e5m2'}
    assert all(r['scale_exact'] for r in result.values())
    assert all(r['bytes_exact'] for r in result.values())==(which=='good')
    assert all('actual_bytes' in v and 'expected_bytes' in v for v in tensors.values())


@pytest.mark.parametrize('kernel_name',['_row_quant','_weight_quant','_gradient_quant'])
def test_direct_quantizer_compile_no_gpu(kernel_name,checks,tmp_path,monkeypatch):
    if os.environ.get('EMBER_FP8_AOT_CHECK')!='1': pytest.skip('opt-in compiler-only regression')
    import triton
    from triton.backends.compiler import GPUTarget
    from triton.compiler import ASTSource
    assert triton.__version__=='3.5.0'
    assert not torch.cuda.is_initialized()
    class NoGpu:
        def __getattr__(self,name): raise AssertionError('GPU access during AOT: '+name)
    monkeypatch.setattr(triton.runtime.driver,'_active',NoGpu())
    def no_cuda(*a,**k): raise AssertionError('CUDA initialized during AOT')
    monkeypatch.setattr(torch.cuda,'_lazy_init',no_cuda)
    sys.path.insert(0,str(SCRIPTS))
    try: kernels=importlib.import_module('fp8_pair_v2.quantizers')
    finally: sys.path.pop(0)
    oldtest=importlib.import_module('test_issue1945_fp8_pair_v1')
    cases=oldtest._fp8_aot_cases(kernel_name)
    if kernel_name=='_row_quant':
        extra=[]
        for label,pointers,constants,options in cases:
            p=dict(pointers); p['X']='*fp32';extra.append((label+'-fp32',p,constants,options))
        cases+=extra
    kernel=getattr(kernels,kernel_name)
    for label,pointers,constants,options in cases:
        signature={name:'constexpr' if name in constants else pointers[name] for name in kernel.arg_names}
        compiled=triton.compile(ASTSource(fn=kernel,signature=signature,constexprs=constants),
                                target=GPUTarget('cuda',89,32),options=options)
        ptx=compiled.asm['ptx']
        for ext in ('ptx','ttir'):
            (tmp_path/(kernel_name+'-'+label+'.'+ext)).write_text(compiled.asm[ext])
        assert compiled.asm['cubin']
        fmt='e5m2' if kernel_name=='_gradient_quant' or pointers.get('Q')=='*fp8e5' else 'e4m3'
        assert checks.check_direct_ptx(ptx,fmt)['verified']
    assert not torch.cuda.is_initialized()
