# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Create-only v2 timing run of pinned native kernels, without relaxing v1."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback
from . import contract as c

PREFIX='src/ember/governance/scripts/'
PINNED = {'docs/domains/lab/research/fp8-pair-v1.md': '9c78c28ba7d21a41bd955a7fdc56cf212441e665', 'src/ember/governance/scripts/fp8_pair_v1/__init__.py': 'cb99e8771410ddb39bb739d0b3e9d93a73317817', 'src/ember/governance/scripts/fp8_pair_v1/contract.py': '7c950ef3ce59e4afcb25a4d937e51aa48f525c86', 'src/ember/governance/scripts/fp8_pair_v1/kernels.py': 'cf90eec993a8e9329fd3dec306a73cf79419e9d8', 'src/ember/governance/scripts/fp8_pair_v1/pair.py': 'b942400e6b2a8296aa0e38ce09a7748362e9adff', 'src/ember/governance/scripts/fp8_pair_v1/probe.py': 'c085f6b269bab1d73cc3bef664effdb728072542', 'src/ember/governance/scripts/gpu_lock_guard.py': 'fb947cfbfb1cc182040898d5b1d9c27af576e4e7', 'src/ember/governance/scripts/issue1945_fp8_pair_v1.py': 'bfb5075a95c332e3f5666547735e8d31d1ea90aa', 'src/ember/governance/scripts/owned_process.py': '42610c9362b3384cfa8c0a134dadbbe68c0fc8f5', 'src/ember/governance/scripts/tests/test_issue1945_fp8_pair_v1.py': '35f45eed912cd6142ba1c066e678270724fe7654', 'src/ember/model/ember_v0_decoder.py': 'cfab6301484ea44aafd847d61ca234c23b700634', 'src/ember/model/ember_v0_document_reduction.py': '09e7d61dea81157cd2b4fa5ea7506651ad0f3cfd'}
NEW_FILES=[PREFIX+'issue1945_fp8_pair_v2.py',
           *[PREFIX+'fp8_pair_v2/'+x for x in ('__init__.py','contract.py','model.py','native.py','runner.py','quantizers.py','quantization_checks.py')],
           PREFIX+'tests/test_issue1945_fp8_pair_v2.py',
           PREFIX+'tests/test_issue1945_fp8_quantizer_fix.py','docs/domains/lab/research/fp8-pair-v2.md']
GIT_DISCOVERY=('GIT_DIR','GIT_WORK_TREE','GIT_INDEX_FILE','GIT_COMMON_DIR',
               'GIT_OBJECT_DIRECTORY','GIT_ALTERNATE_OBJECT_DIRECTORIES',
               'GIT_CEILING_DIRECTORIES','GIT_DISCOVERY_ACROSS_FILESYSTEM')
GIB=1024**3


def git(root,*args,raw=False):
    env={k:v for k,v in os.environ.items() if k not in GIT_DISCOVERY}
    r=subprocess.run(['git','-C',str(root),*args],env=env,capture_output=True,timeout=15,check=True)
    return r.stdout if raw else r.stdout.decode('utf-8').strip()


def source_binding(root,expected):
    root=Path(root).resolve(strict=True)
    if len(expected)!=40 or any(x not in '0123456789abcdef' for x in expected):
        raise ValueError('SOURCE: full lowercase commit required')
    if git(root,'rev-parse','HEAD')!=expected: raise ValueError('SOURCE: HEAD differs')
    git(root,'merge-base','--is-ancestor',c.BASE,'HEAD')
    if git(root,'status','--porcelain','--untracked-files=no'): raise ValueError('SOURCE: tracked changes not frozen')
    bound={}
    for rel in list(PINNED)+NEW_FILES:
        p=(root/rel).resolve(strict=True)
        if not p.is_relative_to(root): raise ValueError('SOURCE: path escaped checkout')
        blob=git(root,'rev-parse','HEAD:'+rel)
        if rel in PINNED and blob!=PINNED[rel]: raise ValueError('SOURCE: pinned dependency changed: '+rel)
        committed=git(root,'cat-file','blob','HEAD:'+rel,raw=True); working=p.read_bytes()
        if working!=committed and working.replace(b'\r\n',b'\n')!=committed:
            raise ValueError('SOURCE: working bytes differ: '+rel)
        bound[rel]=dict(git_blob=blob,working_sha256=hashlib.sha256(working).hexdigest())
    return bound


def write_new(path,data):
    raw=(json.dumps(data,indent=2,sort_keys=True,allow_nan=False)+'\n').encode('utf-8')
    with Path(path).open('xb') as f: f.write(raw); f.flush(); os.fsync(f.fileno())


def file_sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for raw in iter(lambda:f.read(8*1024*1024),b''): h.update(raw)
    return h.hexdigest()


def tensors_new(torch,path,data):
    with Path(path).open('xb') as f: torch.save(data,f); f.flush(); os.fsync(f.fileno())


def save_codegen(output,ops):
    inventory={}
    for name,kernel in ops.compiled.items():
        for ext in ('ptx','ttir','ttgir','llir'):
            text=kernel.asm.get(ext)
            if not isinstance(text,str): continue
            raw=text.encode('utf-8'); path=output/(name.replace(':','-')+'.'+ext)
            if path.exists():
                if path.read_bytes()!=raw: raise ValueError('CODEGEN: specialization changed')
            else:
                with path.open('xb') as f: f.write(raw)
            inventory[path.name]=hashlib.sha256(raw).hexdigest()
    return inventory


def _module_identity(module,path):
    if Path(module.__file__).resolve()!=path.resolve(): raise ValueError('IMPORT_IDENTITY: '+module.__name__)


def _run_native(torch,ops,c1,v1,model,native,output):
    from .quantization_checks import run_rounding_checks
    rounding,rounding_tensors=run_rounding_checks(torch,ops,c1)
    tensors_new(torch,output/'direct-rounding-tensors.pt',rounding_tensors)
    write_new(output/'direct-rounding-checks.json',rounding)
    save_codegen(output,ops)
    if not all(r['bytes_exact'] and r['scale_exact'] for r in rounding.values()):
        raise ValueError('V2_DIRECT_CONVERSION_FAILED: see direct-rounding-checks.json')
    cases={}; snapshots={}
    for label,values in native.fixtures(torch).items():
        devices=[t.cuda() for t in values]
        row,tensors=native.check_case(torch,ops,c1,v1,model,devices)
        cases[label]=row; snapshots[label]=tensors
        del devices
    replay=native.replay_and_locality(torch,ops,v1)
    instruction_details=ops.instruction_report()
    quantizer_details=ops.quantization_report()
    flags={
        'quantization':{label+'/'+k:v for label,row in cases.items() for k,v in row['quantization'].items()},
        'hardware':{label+'/'+k:v for label,row in cases.items() for k,v in row['hardware'].items()},
        'replay':replay,
        'instructions':{name:row['native_fp8_mma'] and row['fp32_promotion']['verified']
                        for name,row in instruction_details.items()},
        'ideal':{label+'/'+k:v['passed'] for label,row in cases.items() for k,v in row['ideal'].items()},
    }
    flags['instructions'].update({'quantizer/'+name:row['verified'] for name,row in quantizer_details.items()})
    # Retain all observations BEFORE any refusal; the old ideal failures are explicit.
    report=dict(cases=cases,flags=flags,instructions=instruction_details,
        direct_rounding=rounding,quantizer_instructions=quantizer_details,
        original_ideal_gate_passed=all(flags['ideal'].values()),
        meaning='Hardware agreement admits timing only; original ideal failure is not relabelled.')
    tensors_new(torch,output/'native-v2-tensors.pt',snapshots)
    write_new(output/'native-v2-checks.json',report)
    save_codegen(output,ops)
    native.require_admission(flags)
    print('V2 NATIVE: hardware model matched; original ideal gate passed='+str(report['original_ideal_gate_passed']),flush=True)
    return report


def _validate_record(torch,record):
    if not isinstance(record,dict) or set(record)!={'weights','chunks'}: raise ValueError('SUBJECT_SCHEMA: fields differ')
    weights=record['weights']; chunks=record['chunks']
    if (not isinstance(weights,(list,tuple)) or len(weights)!=3
            or not isinstance(chunks,list) or len(chunks)!=4): raise ValueError('SUBJECT_SCHEMA: counts differ')
    tensors=[]
    for w,shape in zip(weights,((2048,1024),(2048,1024),(1024,2048))):
        if not torch.is_tensor(w) or tuple(w.shape)!=shape: raise ValueError('SUBJECT_SCHEMA: weight shape differs')
        tensors.append(w)
    for chunk in chunks:
        if not isinstance(chunk,dict) or set(chunk)!={'input','upstream'}: raise ValueError('SUBJECT_SCHEMA: chunk fields differ')
        for key in ('input','upstream'):
            t=chunk[key]
            if not torch.is_tensor(t) or tuple(t.shape)!=(1024,1024): raise ValueError('SUBJECT_SCHEMA: chunk shape differs')
            tensors.append(t)
    if not all(t.device.type=='cpu' and t.dtype==torch.bfloat16 and bool(torch.isfinite(t).all()) for t in tensors):
        raise ValueError('SUBJECT_SCHEMA: expected finite CPU BF16')


def _run_layer(torch,F,production,pair,ops,c1,v1,model,native,record,layer,output):
    _validate_record(torch,record)
    wu,wg,wd=[w.detach().cuda().requires_grad_(True) for w in record['weights']]
    x=torch.cat([z['input'] for z in record['chunks']],0).cuda().requires_grad_(True)
    dy=torch.cat([z['upstream'] for z in record['chunks']],0).cuda()
    with torch.enable_grad():
        u=production.document_reduced_linear(x,wu,c.LENGTHS,'descending')
        g=production.document_reduced_linear(x,wg,c.LENGTHS,'descending')
        y=production.document_reduced_linear(F.silu(g)*u,wd,c.LENGTHS,'descending')
        du,dg=torch.autograd.grad(y,(u,g),grad_outputs=dy)
    del u,g,y
    sampled,snapshot=native.check_case(torch,ops,c1,v1,model,(x,wu,wg,du,dg),sampled=True)
    tensors_new(torch,output/f'layer-{layer}-sample-tensors.pt',snapshot)
    write_new(output/f'layer-{layer}-sample-checks.json',sampled)
    save_codegen(output,ops)
    if not all(sampled['quantization'].values()) or not all(sampled['hardware'].values()):
        raise ValueError('V2_PRODUCTION_SAMPLE_FAILED: layer '+str(layer))
    del snapshot
    with torch.no_grad():
        a=du@wu; b=dg@wg
        cancellation=float(a.double().norm()+b.double().norm())/max(float((a+b).double().norm()),1e-30)
    del a,b
    regions={}
    for region,name in ((True,'projection'),(False,'block')):
        functions=v1.make_functions(torch,F,production,pair,ops,x,wu,wg,wd,dy,du,dg,c.LENGTHS,region)
        regions[name]=v1.measure_group(torch,c1,functions,ops,x,wu,du,dg,region)
        write_new(output/f'layer-{layer}-{name}.json',regions[name])
        del functions
    rp,bp=regions['projection'],regions['block']; r,b=rp['median_us'],bp['median_us']
    summary=dict(region_gain=1-r['D']/r['A'],block_gain=1-b['D']/b['A'],
        baseline_drift=max(abs(r['A2']-r['A'])/r['A'],abs(b['A2']-b['A'])/b['A']),
        checks_pass=rp['checks_pass'] and bp['checks_pass'])
    result=dict(regions=regions,summary=summary,sample_checks=sampled,cancellation_norm_ratio=cancellation)
    write_new(output/f'layer-{layer}.json',result)
    print(f'layer={layer:2} checks={summary["checks_pass"]} D projection={r["A"]/r["D"]:.4f}x '
          f'D block={b["A"]/b["D"]:.4f}x block_saved_us={b["A"]-b["D"]:.3f} '
          f'A/A2 drift={summary["baseline_drift"]:.3%}',flush=True)
    del x,dy,du,dg,wu,wg,wd
    torch.cuda.synchronize(); torch.cuda.empty_cache()
    return result


def execute(root,output,args,report):
    if not os.environ.get('EMBER_GPU_LOCK_PATH','').strip(): raise ValueError('GPU_LOCK: recorded path required')
    from fp8_pair_v1 import probe as v1
    _module_identity(v1,root/PREFIX/'fp8_pair_v1/probe.py')
    for name,sub in (('TRITON_CACHE_DIR','triton'),('CUDA_CACHE_PATH','cuda'),('TORCHINDUCTOR_CACHE_DIR','inductor')):
        os.environ[name]=str(output/'cache'/sub)
    tmp=output/'cache/tmp'; tmp.mkdir(parents=True)
    os.environ['TEMP']=os.environ['TMP']=str(tmp)
    guard=v1.load_module(root/PREFIX/'gpu_lock_guard.py','_v2_existing_gpu_guard')
    with guard.acquire(script='issue1945_fp8_pair_v2.py'):
        import torch
        import torch.nn.functional as F
        import triton
        from fp8_pair_v1 import contract as c1, pair as pair_module, kernels
        from . import model,native,quantizers
        _module_identity(quantizers,root/PREFIX/'fp8_pair_v2/quantizers.py')
        for module,name in ((c1,'contract'),(pair_module,'pair'),(kernels,'kernels')):
            _module_identity(module,root/PREFIX/f'fp8_pair_v1/{name}.py')
        if (torch.__version__,triton.__version__,torch.version.cuda)!=('2.10.0+cu126','3.5.0','12.6'):
            raise ValueError('ENVIRONMENT: frozen torch/Triton/CUDA versions required')
        if (not torch.cuda.is_available() or torch.cuda.device_count()!=1
                or torch.cuda.get_device_capability(0)!=(8,9) or 'RTX 4090' not in torch.cuda.get_device_name(0)):
            raise ValueError('DEVICE: one visible RTX 4090 required')
        free,total=torch.cuda.mem_get_info()
        if free<6*GIB: raise ValueError('HEADROOM: require 6 GiB free; rail unchanged')
        torch.cuda.set_per_process_memory_fraction(4*GIB/total,0)
        torch.set_num_threads(2); torch.backends.cuda.matmul.allow_tf32=False; torch.backends.cudnn.allow_tf32=False
        sys.path.insert(0,str(root/'src'))
        from ember.model.ember_v0_decoder import bind_triton_c_compiler
        compiler=bind_triton_c_compiler()
        production=v1.load_module(root/'src/ember/model/ember_v0_document_reduction.py','_v2_production_reduction')
        report['environment']=dict(torch=torch.__version__,triton=triton.__version__,cuda=torch.version.cuda,
            device=torch.cuda.get_device_name(0),gpu_lock=guard.LOCK_PATH,compiler=compiler,
            free_before_bytes=free,allocator_cap_bytes=4*GIB,
            bf16_reduced_precision_reduction=torch.backends.cuda.matmul.allow_bf16_reduced_precision_reduction)
        if file_sha(args.operands)!=c1.OPERAND_SHA256: raise ValueError('OPERANDS: original byte hash differs')
        report['operand_sha256']=c1.OPERAND_SHA256
        ops=quantizers.NativeOps('cuda:0')
        try:
            report['native_checks']=_run_native(torch,ops,c1,v1,model,native,output)
            data=torch.load(args.operands,map_location='cpu',weights_only=True)
            if set(data['shared'])!={f'layers.{i}.shared' for i in c.LAYERS}: raise ValueError('SUBJECTS: set differs')
            rows={}
            for layer in c.LAYERS:
                result=_run_layer(torch,F,production,pair_module.pair,ops,c1,v1,model,native,
                                  data['shared'][f'layers.{layer}.shared'],layer,output)
                report['layers'][str(layer)]=result
                rows[str(layer)]=result['summary']
            report['verdict']=c.decide(rows,hardware_ok=True,
                ideal_ok=report['native_checks']['original_ideal_gate_passed'])
            report['peak_allocated_bytes']=int(torch.cuda.max_memory_allocated())
            report['peak_reserved_bytes']=int(torch.cuda.max_memory_reserved())
            report['instructions_final']=ops.instruction_report()
        finally:
            report['codegen_sha256']=save_codegen(output,ops)


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[5])
    ap.add_argument('--expect-commit',required=True)
    ap.add_argument('--operands',type=Path,required=True)
    ap.add_argument('--output-dir',type=Path,required=True)
    args=ap.parse_args(argv)
    root=args.root.resolve(strict=True); out=args.output_dir.resolve()
    if os.name!='nt' or out.drive.upper()!='B:' or not out.parent.is_dir():
        raise ValueError('CUSTODY: existing B: parent and native Windows required')
    out.mkdir(exist_ok=False)
    report=dict(schema='ember-1945-fp8-pair-speed-v2',ticket='1945',
        goal_id='EMBER-02',workstream_id='EMBER-02A',
        next_executed_outcome='EMBER-02 first sufficiently pretrained clean-genesis 3B Ember',
        ts=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
        sha_convention='SHA256 of file bytes as-is; Git blobs use Git object hashing',
        invariant_sha256='08a0eb7418c09a8088be4658e10785107abbb7507fc2dbcdc789936aa54e02a6',
        status='STARTED',source_commit=args.expect_commit,applied_positions=0,optimizer_updates=0,
        claim=c.CLAIM,layers={},v1_verdict_revised=False,
        protocol=dict(candidate='D (promoted b3ea8dd0 kernels)',labels=list(c.LABELS),rounds=c.ROUNDS,
            calls_per_graph=c.CALLS,minimum_region_gain=c.MIN_REGION_GAIN,max_baseline_drift=c.MAX_BASELINE_DRIFT,
            full_block_condition='positive and greater than duplicate-baseline fractional drift on every subject',
            accuracy='finite-input Ada model; ideal arithmetic errors retained separately',
            learning_acceptance='not tested; unchanged external campaign gates remain mandatory'))
    rc=1
    try:
        bound=source_binding(root,args.expect_commit); report['source_binding']=bound
        execute(root,out,args,report)
        if source_binding(root,args.expect_commit)!=bound: raise ValueError('SOURCE: changed during execution')
        report['status']='COMPLETED'
        rc=0 if report['verdict']['worth_learning_comparison'] else 2
    except BaseException as error:
        report['status']='REFUSED_OR_FAILED'
        report['error']=dict(type=type(error).__name__,message=str(error),traceback=traceback.format_exc())
    finally:
        report['finished_utc']=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())
        write_new(out/'result.json',report)
        print(json.dumps(report.get('verdict',report.get('error')),indent=2),flush=True)
        print('receipt:',out/'result.json',flush=True)
    return rc
