# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Finite, source-bound GPU experiment. No production installation or optimizer."""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time
import traceback

BASE='edc200bef9e459cb41aea0ac6a1016a8b07211e4'
PREFIX='src/ember/governance/scripts/'
DEPENDENCIES={
 'src/ember/model/ember_v0_document_reduction.py':'09e7d61dea81157cd2b4fa5ea7506651ad0f3cfd',
 'src/ember/model/ember_v0_decoder.py':'cfab6301484ea44aafd847d61ca234c23b700634',
 PREFIX+'gpu_lock_guard.py':'fb947cfbfb1cc182040898d5b1d9c27af576e4e7',
 PREFIX+'owned_process.py':'42610c9362b3384cfa8c0a134dadbbe68c0fc8f5',
}
NEW_SOURCES=[PREFIX+'issue1945_fp8_pair_v1.py',
             *[PREFIX+'fp8_pair_v1/'+x for x in ('__init__.py','contract.py','pair.py','kernels.py','probe.py')],
             PREFIX+'tests/test_issue1945_fp8_pair_v1.py',
             'docs/domains/lab/research/fp8-pair-v1.md']
GIB=1024**3


def write_new(path,value):
    data=json.dumps(value,indent=2,sort_keys=True,allow_nan=False)+'\n'
    with Path(path).open('x',encoding='utf-8',newline='\n') as handle:
        handle.write(data); handle.flush(); os.fsync(handle.fileno())


def file_sha(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda:handle.read(8*1024*1024),b''): digest.update(chunk)
    return digest.hexdigest()


def git(root,*args,raw=False):
    r=subprocess.run(['git','-C',str(root),*args],capture_output=True,timeout=15,check=False)
    if r.returncode: raise ValueError('SOURCE: '+r.stderr.decode('utf-8',errors='replace'))
    return r.stdout if raw else r.stdout.decode().strip()


def source_binding(root,expected):
    if len(expected)!=40 or any(x not in '0123456789abcdef' for x in expected):
        raise ValueError('SOURCE: full lowercase commit SHA required')
    if git(root,'rev-parse','HEAD')!=expected: raise ValueError('SOURCE: HEAD changed')
    git(root,'merge-base','--is-ancestor',BASE,'HEAD')
    if git(root,'status','--porcelain','--untracked-files=no'):
        raise ValueError('SOURCE: tracked changes are not frozen')
    bound={}
    for rel in list(DEPENDENCIES)+NEW_SOURCES:
        path=(root/rel).resolve(strict=True)
        if not path.is_relative_to(root): raise ValueError('SOURCE: path escaped checkout')
        blob=git(root,'rev-parse','HEAD:'+rel)
        if rel in DEPENDENCIES and blob!=DEPENDENCIES[rel]:
            raise ValueError('SOURCE: dependency differs from audited base: '+rel)
        original=git(root,'cat-file','blob','HEAD:'+rel,raw=True)
        working=path.read_bytes()
        if working!=original and working.replace(b'\r\n',b'\n')!=original:
            raise ValueError('SOURCE: working bytes differ: '+rel)
        bound[rel]=dict(git_blob=blob,working_sha256=hashlib.sha256(working).hexdigest())
    return bound


def load_module(path,name):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec)
    sys.modules[name]=module; spec.loader.exec_module(module)
    return module


def oracle_close(torch,actual,reference64,bound64):
    # One BF16 ULP plus conservative FP32 product-sum error. Not an FP8 learning margin.
    ref=reference64.to(torch.bfloat16).double()
    tolerance=ref.abs()/128 + bound64*1e-6 + 1e-30
    return bool(torch.isfinite(actual).all() and ((actual.double()-ref).abs()<=tolerance).all())


def oracle_diagnostics(torch, actual, reference64, bound64):
    """Describe the ORIGINAL oracle result; never select or relax its margin.

    All inputs are snapshotted on CPU. Nonfinite actual values remain failures,
    with null summary scalars instead of non-standard NaN/Infinity JSON.
    """
    if (actual.ndim != 2 or actual.numel() == 0
            or actual.shape != reference64.shape or actual.shape != bound64.shape):
        raise ValueError('ORACLE_DIAGNOSTIC_SCHEMA: nonempty matching matrices required')
    a = actual.detach().cpu().double()
    expected = reference64.detach().cpu().double()
    bound = bound64.detach().cpu().double()
    if not bool(torch.isfinite(expected).all() and torch.isfinite(bound).all()
                and (bound >= 0).all()):
        raise ValueError('ORACLE_DIAGNOSTIC_SCHEMA: invalid reference or absolute-product sum')
    rounded = expected.to(torch.bfloat16).double()
    # Identical expression to oracle_close; diagnostic only, not a new gate.
    tolerance = rounded.abs()/128 + bound*1e-6 + 1e-30
    error = (a-rounded).abs()
    finite = torch.isfinite(a)
    failed = (~finite) | (error > tolerance)
    ratio = torch.where(finite, error/tolerance, torch.full_like(a, float('inf')))
    worst_flat = int(ratio.flatten().argmax())
    row, column = divmod(worst_flat, a.shape[1])

    def scalar(value):
        value = float(value)
        return value if -float('inf') < value < float('inf') else None

    reference_norm = float(rounded.norm())
    return dict(
        passed=oracle_close(torch, a, expected, bound),
        shape=list(a.shape), elements=a.numel(),
        failed_elements=int(failed.sum()), nonfinite_elements=int((~finite).sum()),
        max_abs_error=scalar(error.max()),
        relative_l2_to_rounded_reference=(scalar((a-rounded).norm()/reference_norm)
                                          if reference_norm else None),
        zero_reference=reference_norm == 0,
        max_error_over_tolerance=scalar(ratio.max()),
        row_failed_elements=failed.sum(1).tolist(),
        column_failed_elements=failed.sum(0).tolist(),
        worst_element=dict(index=[row, column], actual=scalar(a[row,column]),
            reference64=scalar(expected[row,column]),
            rounded_reference=scalar(rounded[row,column]),
            absolute_product_sum=scalar(bound[row,column]),
            absolute_error=scalar(error[row,column]), tolerance=scalar(tolerance[row,column]),
            error_over_tolerance=scalar(ratio[row,column])),
    )


def record_oracle(torch, details, snapshots, fixture, name, actual, reference64, bound64):
    """Observe one comparison and return its unchanged original boolean."""
    key = fixture+'/'+name
    if key in snapshots or name in details.get(fixture, {}):
        raise ValueError('ORACLE_DIAGNOSTIC_DUPLICATE: '+key)
    snapshot = {label: value.detach().cpu().contiguous().clone()
                for label, value in (('actual', actual), ('reference64', reference64),
                                     ('absolute_product_sum64', bound64))}
    snapshots[key] = snapshot
    result = oracle_diagnostics(torch, snapshot['actual'], snapshot['reference64'],
                                snapshot['absolute_product_sum64'])
    details.setdefault(fixture, {})[name] = result
    # The existing function remains the sole acceptance decision.
    return oracle_close(torch, actual, reference64, bound64)


def finish_native_checks(torch, output, checks, details, snapshots, ops):
    """Retain failure evidence BEFORE raising, without rerunning any GPU kernel."""
    output = Path(output)
    write_new(output/'native-checks.json', checks)
    archive = output/'native-oracle-tensors.pt'
    with archive.open('xb') as handle:
        torch.save(snapshots, handle)
        handle.flush(); os.fsync(handle.fileno())
    codegen = {}
    for name, kernel in ops.compiled.items():
        if not name.startswith(('fprop', 'dgrad')):
            continue
        for extension in ('ptx', 'ttir', 'ttgir', 'llir'):
            text = kernel.asm.get(extension)
            if not isinstance(text, str):
                continue
            filename = name.replace(':','-')+'.'+extension
            path = output/filename
            with path.open('x', encoding='utf-8', newline='\n') as handle:
                handle.write(text)
            codegen[filename] = file_sha(path)
    report = dict(
        schema='ember-fp8-native-oracle-diagnostics-v1',
        claim='Diagnostic observations only; original native gate and all margins unchanged.',
        fixtures=details, tensor_archive=archive.name,
        tensor_archive_sha256=file_sha(archive), codegen_sha256=codegen,
    )
    write_new(output/'native-oracle-diagnostics.json', report)
    for fixture, rows in details.items():
        for name, row in rows.items():
            print('ORACLE %s %s failed=%d/%d max_abs=%s max_limit_ratio=%s' % (
                fixture, name, row['failed_elements'], row['elements'],
                row['max_abs_error'], row['max_error_over_tolerance']), flush=True)
    flags = [v for group, rows in checks.items() if group != 'native_instructions'
             for v in rows.values()]
    if not all(flags):
        raise ValueError('NATIVE_CHECK_FAILED: see native-checks.json; do not alter margins')
    return checks


def native_checks(torch,ops,c,output):
    """Independent small exact-byte and FP64-product checks before any timing."""
    cpu=c.CpuOps()
    gen=torch.Generator().manual_seed(1945)
    x0=torch.randn((32,64),generator=gen).to(torch.bfloat16)
    wu0=(torch.randn((128,64),generator=gen)/8).to(torch.bfloat16)
    wg0=(torch.randn((128,64),generator=gen)/8).to(torch.bfloat16)
    du0=torch.randn((32,128),generator=gen).to(torch.bfloat16)
    dg0=torch.randn((32,128),generator=gen).to(torch.bfloat16)
    fixtures={
       'ordinary':(x0,wu0,wg0,du0,dg0),
       'zero_token':(torch.cat((torch.zeros_like(x0[:1]),x0[1:])),wu0,wg0,du0,dg0),
       'cancellation':(x0,wu0,wu0.clone(),du0,-du0),
       'outlier_token':(torch.cat((x0[:1]*64,x0[1:])),wu0,wg0,du0,dg0),
       'unequal_branches':(x0,wu0*32,wg0/32,du0/32,dg0*32),
    }
    checks={}
    details, snapshots = {}, {}
    with torch.no_grad():
        for label,values in fixtures.items():
            x,wu,wg,du,dg=[t.cuda() for t in values]
            expected=cpu.prepare('D',values[1],values[2])
            shadow=ops.prepare('D',wu,wg)
            qx,a=ops.quantize(x,'e4m3'); ex,ea=c.quantize_rows(values[0],'e4m3')
            qe,cs=ops.grad_quant(du,dg,shadow['scales'])
            ee,ec=c.absorbed_gradient(values[3],values[4],expected['scales'])
            exact={
               'weight_bytes':torch.equal(shadow['q'].cpu().view(torch.uint8),expected['q'].view(torch.uint8)),
               'weight_scale':torch.equal(shadow['scales'].cpu(),expected['scales']),
               'transpose_bytes':torch.equal(shadow['qt'].cpu().view(torch.uint8),expected['qt'].view(torch.uint8)),
               'activation_bytes':torch.equal(qx.cpu().view(torch.uint8),ex.view(torch.uint8)),
               'activation_scale':torch.equal(a.cpu(),ea),
               'absorbed_gradient_bytes':torch.equal(qe.cpu().view(torch.uint8),ee.view(torch.uint8)),
               'absorbed_gradient_scale':torch.equal(cs.cpu(),ec),
            }
            q=expected['q'].double(); a64=ea.double()[:,None]; b64=expected['scales'].double()
            f64=(ex.double()@q.T)*a64*b64
            fb=(ex.double().abs()@q.T.abs())*a64*b64
            dx64=(ee.double()@expected['qt'].double().T)*ec.double()[:,None]
            db=(ee.double().abs()@expected['qt'].double().T.abs())*ec.double()[:,None]
            # Keep the exact quantized bytes and scales used by the oracle.
            # These are host copies only; this instrumentation adds no native launches.
            snapshots[label+'/operands'] = {
                'x': values[0].detach().cpu().clone(),
                'wu': values[1].detach().cpu().clone(),
                'wg': values[2].detach().cpu().clone(),
                'du': values[3].detach().cpu().clone(),
                'dg': values[4].detach().cpu().clone(),
                'qx_bytes': ex.view(torch.uint8).clone(),
                'qw_bytes': expected['q'].view(torch.uint8).clone(),
                'qt_bytes': expected['qt'].view(torch.uint8).clone(),
                'qe_bytes': ee.view(torch.uint8).clone(),
                'activation_scales': ea.clone(),
                'weight_scales': expected['scales'].clone(),
                'gradient_scales': ec.clone(),
            }
            for mode in ('C','D','E'):
                state=ops.prepare(mode,wu,wg)
                u,g=ops.forward(mode,x,wu,wg,state)
                exact[mode+'_fprop_oracle']=record_oracle(
                    torch,details,snapshots,label,mode+'_fprop_oracle',torch.cat((u,g),1).cpu(),f64,fb)
                if mode in ('D','E'):
                    dx=ops.dgrad(mode,du,dg,wu,wg,state)
                    exact[mode+'_dgrad_oracle']=record_oracle(
                        torch,details,snapshots,label,mode+'_dgrad_oracle',dx.cpu(),dx64,db)
            ops.require_valid()
            checks[label]=exact
        # Modify later/unrelated token rows; earlier projection rows must not change.
        x,wu,wg,*_=[t.cuda() for t in fixtures['ordinary']]
        state=ops.prepare('D',wu,wg)
        before=ops.forward('D',x,wu,wg,state)
        x[16:].mul_(32)
        after=ops.forward('D',x,wu,wg,state)
        checks['token_locality']={'unchanged_prefix':all(torch.equal(a[:16].view(torch.int16),b[:16].view(torch.int16))
                                                      for a,b in zip(before,after))}
        # An isolated poisoned helper demonstrates refusal without poisoning the measured helper.
        badops=type(ops)('cuda:0'); bad=x.clone(); bad[0,0]=float('nan')
        badops.quantize(bad,'e4m3')
        refused=False
        try: badops.require_valid()
        except ValueError: refused=True
        checks['nonfinite_negative']={'refused':refused}
        # Graph capture/replay is tested before the full measurement stage.
        x,wu,wg,du,dg=[t.cuda() for t in fixtures['ordinary']]
        def replay_body():
            state=ops.prepare('D',wu,wg)
            u,g=ops.forward('D',x,wu,wg,state)
            return u,g,ops.dgrad('D',du,dg,wu,wg,state)
        graph,outs=capture(torch,replay_body,2)
        saved=tuple(t.clone() for t in outs)
        original_w=wu.clone()
        wu.mul_(1.25)
        graph.replay(); torch.cuda.synchronize()
        changed=tuple(t.clone() for t in outs)
        fresh=replay_body()
        refreshed=(not torch.equal(saved[0].view(torch.int16),changed[0].view(torch.int16))
                   and tuple_equal(torch,changed,fresh))
        wu.copy_(original_w)
        x.zero_(); du.zero_(); dg.zero_()
        graph.replay(); torch.cuda.synchronize()
        zero=all(bool(torch.isfinite(t).all()) and int(torch.count_nonzero(t))==0 for t in outs)
        checks['captured_execution']={'refreshed_weights':refreshed,'zero_input_and_gradient_replay':zero}
        del graph,outs,saved,changed,fresh
        ops.require_valid()
        checks['native_instructions']=ops.instruction_report()
    return finish_native_checks(torch,output,checks,details,snapshots,ops)


def make_functions(torch,F,production,pair_fn,ops,x,wu,wg,wd,dy,du,dg,lengths,region):
    functions={}
    for label in ('A','A2','B','C','D','E'):
        mode='A' if label=='A2' else label
        if region:
            def fn(mode=mode):
                with torch.no_grad():
                    if mode=='A':
                        return F.linear(x,wu),F.linear(x,wg),du@wu+dg@wg
                    shadow=ops.prepare(mode,wu,wg)
                    u,g=ops.forward(mode,x,wu,wg,shadow)
                    return u,g,ops.dgrad(mode,du,dg,wu,wg,shadow)
        else:
            def fn(mode=mode):
                with torch.enable_grad():
                    if mode=='A':
                        u=production.document_reduced_linear(x,wu,lengths,'descending')
                        g=production.document_reduced_linear(x,wg,lengths,'descending')
                    else:
                        with torch.no_grad(): shadow=ops.prepare(mode,wu,wg)
                        u,g=pair_fn(x,wu,wg,mode,ops,shadow,lengths,production.reduce_weight_gradient)
                    hidden=F.silu(g)*u
                    y=production.document_reduced_linear(hidden,wd,lengths,'descending')
                    gradients=torch.autograd.grad(y,(x,wu,wg,wd),grad_outputs=dy)
                    return (y.detach(),)+gradients
        functions[label]=fn
    return functions


def capture(torch,fn,calls):
    stream=torch.cuda.Stream(); stream.wait_stream(torch.cuda.current_stream())
    with torch.cuda.stream(stream):
        for _ in range(3): outputs=fn()
    torch.cuda.current_stream().wait_stream(stream)
    del outputs
    torch.cuda.synchronize()
    graph=torch.cuda.CUDAGraph()
    with torch.cuda.graph(graph):
        for _ in range(calls): outputs=fn()
    graph.replay(); torch.cuda.synchronize()
    return graph,outputs


def tuple_equal(torch,a,b):
    return len(a)==len(b) and all(x.dtype==y.dtype and x.shape==y.shape and
               bool(torch.isfinite(x).all()) and torch.equal(x.view(torch.int16),y.view(torch.int16))
               for x,y in zip(a,b))


def measure_group(torch,c,functions,ops,x,wu,du,dg,region):
    # Capture each arm into its own private pool; there is no shared-pool overwrite ambiguity.
    graphs={label:capture(torch,fn,c.CALLS) for label,fn in functions.items()}
    captured={label:tuple(t.detach().clone() for t in value[1]) for label,value in graphs.items()}
    eager_checks={label:tuple_equal(torch,value,functions[label]()) for label,value in captured.items()}
    baseline_check=tuple_equal(torch,captured['A'],captured['A2'])
    # No weights or inputs here are live trainer objects; these are saved-operand clones.
    with torch.no_grad():
        saved_x=x.clone(); saved_w=wu.clone(); saved_du=du.clone(); saved_dg=dg.clone()
        x.zero_()
        if region: du.zero_(); dg.zero_()
        zeros={}
        for label,(graph,outs) in graphs.items():
            graph.replay(); torch.cuda.synchronize()
            zeros[label]=all(bool(torch.isfinite(t).all()) and int(torch.count_nonzero(t))==0 for t in outs)
        x.copy_(saved_x); du.copy_(saved_du); dg.copy_(saved_dg)
        # Captured refresh must observe changed BF16 owners, not capture-time shadow values.
        wu.mul_(1.25)
        refresh={}
        for label,(graph,outs) in graphs.items():
            graph.replay(); torch.cuda.synchronize()
            actual=tuple(t.clone() for t in outs)
            fresh=functions[label]()
            refresh[label]=(not torch.equal(actual[0].view(torch.int16),captured[label][0].view(torch.int16))
                            and tuple_equal(torch,actual,fresh))
        wu.copy_(saved_w)
        # Direct row-locality check on the captured forward (not on aggregate weight gradients).
        prefix={}
        for label,(graph,outs) in graphs.items():
            graph.replay(); torch.cuda.synchronize()
            reference=outs[0][:1024].clone()
            x[1024:].mul_(4)
            graph.replay(); torch.cuda.synchronize()
            prefix[label]=torch.equal(reference.view(torch.int16),outs[0][:1024].view(torch.int16))
            x.copy_(saved_x)
        del saved_x,saved_w,saved_du,saved_dg
    restored={}
    for label,(graph,outs) in graphs.items():
        graph.replay(); torch.cuda.synchronize()
        restored[label]=tuple_equal(torch,outs,captured[label])
    ops.require_valid()
    samples={label:[] for label in c.LABELS}
    start,end=torch.cuda.Event(enable_timing=True),torch.cuda.Event(enable_timing=True)
    for round_index in range(c.ROUNDS):
        order=list(c.LABELS)
        if (round_index//len(order))%2: order.reverse()
        shift=round_index%len(order); order=order[shift:]+order[:shift]
        for label in order:
            graph=graphs[label][0]
            for _ in range(3): graph.replay()
            torch.cuda.synchronize()
            start.record(); graph.replay(); end.record(); end.synchronize()
            samples[label].append(start.elapsed_time(end)*1000/c.CALLS)
    post={}
    for label,(graph,outs) in graphs.items():
        graph.replay(); torch.cuda.synchronize()
        post[label]=tuple_equal(torch,outs,captured[label])
    ops.require_valid()
    numerical={label:[c.metrics(a,b) for a,b in zip(value,captured['A'])]
               for label,value in captured.items()}
    checks=dict(eager_vs_capture=eager_checks,baseline_repeat=baseline_check,
                zero_replay=zeros,weight_refresh_replay=refresh,token_locality=prefix,
                restored=restored,post_timing=post)
    all_checks=baseline_check and all(all(x.values()) for x in (eager_checks,zeros,refresh,prefix,restored,post))
    medians={k:statistics.median(v) for k,v in samples.items()}
    if any(not (0<value<float('inf')) for value in medians.values()):
        raise ValueError('TIMING: invalid duration')
    result=dict(median_us=medians,raw_per_round_us=samples,checks=checks,checks_pass=all_checks,
                numerical_vs_A=numerical,
                output_order=['up','gate','input_gradient'] if region else
                             ['block_output','input_gradient','up_weight_gradient','gate_weight_gradient','down_weight_gradient'])
    del graphs,captured
    torch.cuda.synchronize(); torch.cuda.empty_cache()
    return result


def execute(root,output,args,report):
    # Every import that could initialize CUDA is below the acquired shared lock.
    os.environ['TRITON_CACHE_DIR']=str(output/'cache/triton')
    os.environ['CUDA_CACHE_PATH']=str(output/'cache/cuda')
    os.environ['TORCHINDUCTOR_CACHE_DIR']=str(output/'cache/inductor')
    tmp=output/'cache/tmp'; tmp.mkdir(parents=True)
    os.environ['TEMP']=os.environ['TMP']=str(tmp)
    scripts=root/PREFIX
    guard=load_module(scripts/'gpu_lock_guard.py','_fp8_pair_existing_gpu_guard')
    if not os.environ.get('EMBER_GPU_LOCK_PATH','').strip():
        raise ValueError('GPU_LOCK_UNCONFIGURED: use the existing recorded lock path')
    with guard.acquire(script='issue1945_fp8_pair_v1.py'):
        import torch
        import torch.nn.functional as F
        import triton
        from . import contract as c
        from .pair import pair
        from .kernels import NativeOps
        if (torch.__version__!='2.10.0+cu126' or triton.__version__!='3.5.0' or torch.version.cuda!='12.6'):
            raise ValueError('ENVIRONMENT: requires the frozen torch 2.10.0+cu126 / Triton 3.5.0 / CUDA 12.6 stack')
        if not torch.cuda.is_available() or torch.cuda.device_count()!=1 or torch.cuda.get_device_capability(0)!=(8,9):
            raise ValueError('DEVICE: exactly one visible SM89 device is required')
        if 'RTX 4090' not in torch.cuda.get_device_name(0): raise ValueError('DEVICE: expected RTX 4090')
        free,total=torch.cuda.mem_get_info()
        if free<6*GIB: raise ValueError('HEADROOM: less than 6 GiB free; no relaxation')
        torch.cuda.set_per_process_memory_fraction(4*GIB/total,0)
        torch.set_num_threads(2)
        torch.backends.cuda.matmul.allow_tf32=False
        torch.backends.cudnn.allow_tf32=False
        # Reuse the existing compiler binder rather than inventing a compiler path.
        sys.path.insert(0,str(root/'src'))
        from ember.model.ember_v0_decoder import bind_triton_c_compiler
        compiler=bind_triton_c_compiler()
        production=load_module(root/'src/ember/model/ember_v0_document_reduction.py','_fp8_pair_production_reduction')
        report['environment']=dict(torch=torch.__version__,triton=triton.__version__,cuda=torch.version.cuda,
             device=torch.cuda.get_device_name(0),compiler=compiler,gpu_lock=guard.LOCK_PATH,
             free_before_bytes=free,allocator_cap_bytes=4*GIB,
             allow_bf16_reduced_precision_reduction=torch.backends.cuda.matmul.allow_bf16_reduced_precision_reduction)
        if file_sha(args.operands)!=c.OPERAND_SHA256: raise ValueError('OPERAND_IDENTITY: hash differs')
        report['operand_sha256']=c.OPERAND_SHA256
        ops=NativeOps('cuda:0')
        report['native_checks']=native_checks(torch,ops,c,output)
        print('NATIVE CHECKS: passed (FP8 instructions, arithmetic oracle, locality, refusal)',flush=True)
        if args.phase=='capability':
            report['verdict']=dict(status='NATIVE_CAPABILITY_PASSED',learning_qualified=False,
                                   trainer_integration_authorized=False)
            return
        data=torch.load(args.operands,map_location='cpu',weights_only=True)
        if set(data['shared'])!={f'layers.{i}.shared' for i in c.LAYERS}:
            raise ValueError('SUBJECTS: saved shared set differs')
        summary={}
        for layer in c.LAYERS:
            record=data['shared'][f'layers.{layer}.shared']
            if ([tuple(w.shape) for w in record['weights']]!=[(2048,1024),(2048,1024),(1024,2048)]
                    or len(record['chunks'])!=4 or any(tuple(z[k].shape)!=(1024,1024)
                            for z in record['chunks'] for k in ('input','upstream'))):
                raise ValueError('SUBJECT_SCHEMA: saved shape differs')
            wu,wg,wd=[w.detach().cuda().requires_grad_(True) for w in record['weights']]
            x=torch.cat([z['input'].cuda() for z in record['chunks']],0).detach().requires_grad_(True)
            dy=torch.cat([z['upstream'].cuda() for z in record['chunks']],0)
            if not all(t.dtype==torch.bfloat16 and bool(torch.isfinite(t).all()) for t in (x,wu,wg,wd,dy)):
                raise ValueError('SUBJECT_SCHEMA: nonfinite or non-BF16')
            with torch.enable_grad():
                u=production.document_reduced_linear(x,wu,c.LENGTHS,'descending')
                g=production.document_reduced_linear(x,wg,c.LENGTHS,'descending')
                y=production.document_reduced_linear(F.silu(g)*u,wd,c.LENGTHS,'descending')
                du,dg=torch.autograd.grad(y,(u,g),grad_outputs=dy)
            del u,g,y
            with torch.no_grad():
                up_contrib=du@wu; gate_contrib=dg@wg
                cancellation=float(up_contrib.double().norm()+gate_contrib.double().norm())/max(float((up_contrib+gate_contrib).double().norm()),1e-30)
            del up_contrib,gate_contrib
            row={'cancellation_norm_ratio':cancellation,'regions':{}}
            for region in (True,False):
                functions=make_functions(torch,F,production,pair,ops,x,wu,wg,wd,dy,du,dg,c.LENGTHS,region)
                result=measure_group(torch,c,functions,ops,x,wu,du,dg,region)
                row['regions']['projection' if region else 'block']=result
                del functions
            r,b=row['regions']['projection'],row['regions']['block']
            rm,bm=r['median_us'],b['median_us']
            region_gain=1-rm['D']/rm['A']; block_gain=1-bm['D']/bm['A']
            drift=max(abs(rm['A2']-rm['A'])/rm['A'],abs(bm['A2']-bm['A'])/bm['A'])
            summary[str(layer)]=dict(region_gain=region_gain,block_gain=block_gain,baseline_drift=drift,
                                    checks_pass=r['checks_pass'] and b['checks_pass'])
            row['screen']=summary[str(layer)]
            report['layers'][str(layer)]=row
            write_new(output/f'layer-{layer}.json',row)
            print(f'layer={layer:2} checks={summary[str(layer)]["checks_pass"]} '
                  f'D projection={rm["A"]/rm["D"]:.4f}x D block={bm["A"]/bm["D"]:.4f}x '
                  f'A/A2 drift={drift:.3%}',flush=True)
            del x,dy,du,dg,wu,wg,wd
            torch.cuda.synchronize(); torch.cuda.empty_cache()
        report['native_instructions_final']=ops.instruction_report()
        for name,kernel in ops.compiled.items():
            if name.startswith(('fprop','dgrad')):
                target=output/(name.replace(':','-')+'.ptx')
                ptx=kernel.asm['ptx']
                if target.exists():
                    if target.read_text(encoding='utf-8')!=ptx:
                        raise ValueError('PTX_IDENTITY: retained specialization changed')
                else:
                    with target.open('x',encoding='utf-8',newline='\n') as handle: handle.write(ptx)
        report['peak_allocated_bytes']=int(torch.cuda.max_memory_allocated())
        report['peak_reserved_bytes']=int(torch.cuda.max_memory_reserved())
        report['verdict']=c.adjudicate(summary)


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[5])
    ap.add_argument('--expect-commit',required=True)
    ap.add_argument('--operands',type=Path,required=True)
    ap.add_argument('--output-dir',type=Path,required=True)
    ap.add_argument('--phase',choices=('capability','full'),default='capability')
    args=ap.parse_args(argv)
    root=args.root.resolve(strict=True); output=args.output_dir.resolve()
    if os.name!='nt' or output.drive.upper()!='B:':
        raise ValueError('CUSTODY: native Windows and a new B: output directory required')
    if not output.parent.is_dir(): raise ValueError('CUSTODY: parent must already exist')
    output.mkdir(exist_ok=False)
    report=dict(schema='ember-1945-fp8-shared-pair-v1',status='STARTED',source_commit=args.expect_commit,
                phase=args.phase,applied_positions=0,optimizer_updates=0,layers={},
                claim='Component experiment only; no learning, whole-step or integration credit.',
                protocol=dict(rounds=24,calls_per_graph=2,labels=['A','A2','B','C','D','E'],
                  primary='D vs A with refresh and all allocation/layout work included',
                  numerical_oracle='one BF16 ULP + 1e-6 absolute-product-sum bound; implementation only',
                  learning_margin=None,minimum_region_gain=.20,maximum_baseline_drift=.02,
                  complete_block_gain='positive and greater than duplicate-baseline fractional drift'))
    rc=1
    try:
        report['source_binding']=source_binding(root,args.expect_commit)
        execute(root,output,args,report)
        # Detect source changes during the process as well as before first GPU use.
        if source_binding(root,args.expect_commit)!=report['source_binding']:
            raise ValueError('SOURCE: changed during execution')
        report['status']='COMPLETED'
        rc=0 if report['verdict']['status'] in ('NATIVE_CAPABILITY_PASSED','COMPONENT_SCREEN_PASSED') else 2
    except BaseException as error:
        report['status']='REFUSED_OR_FAILED'
        report['error']=dict(type=type(error).__name__,message=str(error),traceback=traceback.format_exc())
    finally:
        report['finished_utc']=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())
        write_new(output/'result.json',report)
        print(json.dumps(report.get('verdict',report.get('error')),indent=2),flush=True)
        print('receipt:',output/'result.json',flush=True)
    return rc
