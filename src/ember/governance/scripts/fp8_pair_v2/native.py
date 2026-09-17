# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Hardware-model checks separated from the unchanged ideal-arithmetic diagnostic."""


def fixtures(torch):
    gen=torch.Generator().manual_seed(1945)
    x=torch.randn((32,64),generator=gen).to(torch.bfloat16)
    wu=(torch.randn((128,64),generator=gen)/8).to(torch.bfloat16)
    wg=(torch.randn((128,64),generator=gen)/8).to(torch.bfloat16)
    du=torch.randn((32,128),generator=gen).to(torch.bfloat16)
    dg=torch.randn((32,128),generator=gen).to(torch.bfloat16)
    return dict(ordinary=(x,wu,wg,du,dg),
        zero_token=(torch.cat((torch.zeros_like(x[:1]),x[1:])),wu,wg,du,dg),
        cancellation=(x,wu,wu.clone(),du,-du),
        outlier_token=(torch.cat((x[:1]*64,x[1:])),wu,wg,du,dg),
        unequal_branches=(x,wu*32,wg/32,du/32,dg*32))


def sample_plan(m,f,h):
    if (m,f,h)!=(4096,2048,1024): raise ValueError('SUBJECT_SCHEMA: fixed production shapes required')
    return ((0,1023,1024,2047,2048,3071,3072,4095),
            (0,511,1023,2047,2048,2559,3071,4095),
            (0,127,255,511,512,767,895,1023))


def require_admission(flags):
    for group in ('quantization','hardware','replay','instructions'):
        values=flags.get(group)
        if not isinstance(values,dict) or not values or not all(type(v) is bool and v for v in values.values()):
            raise ValueError('V2_IMPLEMENTATION_CHECK_FAILED: '+group)
    return True


def _pick(torch,t,rows=None,cols=None):
    # CPU advanced indexing for FP8 is not implemented in every torch build.
    fp8=t.dtype in (torch.float8_e4m3fn,torch.float8_e5m2)
    work=t.view(torch.uint8) if fp8 else t
    if rows is not None: work=work[list(rows)]
    if cols is not None: work=work[:,list(cols)]
    work=work.contiguous()
    return work.view(t.dtype) if fp8 else work


def check_case(torch,ops,c1,v1,model,values,*,sampled=False):
    """Evaluate pinned kernels; derive expectations independently on CPU.

    Full production matrices run natively. Only the fixed CPU oracle coordinates
    are sampled in production cases; five small fixtures are checked in full.
    """
    x,wu,wg,du,dg=values
    cpu_values=[t.detach().cpu() for t in values]
    xc,wuc,wgc,duc,dgc=cpu_values
    q,s1=c1.quantize_rows(xc,'e4m3')
    w,wt,ws=c1.weight_shadow(wuc,wgc)
    e,gs=c1.absorbed_gradient(duc,dgc,ws)
    with torch.no_grad():
        state=ops.prepare('D',wu,wg)
        qg,ag=ops.quantize(x,'e4m3')
        eg,cg=ops.grad_quant(du,dg,state['scales'])
        qflags=dict(weight_bytes=torch.equal(state['q'].cpu().view(torch.uint8),w.view(torch.uint8)),
          weight_scale=torch.equal(state['scales'].cpu(),ws),
          transpose_bytes=torch.equal(state['qt'].cpu().view(torch.uint8),wt.view(torch.uint8)),
          activation_bytes=torch.equal(qg.cpu().view(torch.uint8),q.view(torch.uint8)),
          activation_scale=torch.equal(ag.cpu(),s1),
          absorbed_gradient_bytes=torch.equal(eg.cpu().view(torch.uint8),e.view(torch.uint8)),
          absorbed_gradient_scale=torch.equal(cg.cpu(),gs))
        del state,qg,ag,eg,cg
        if sampled:
            rows,columns,features=sample_plan(x.shape[0],wu.shape[0],wu.shape[1])
        else:
            rows=tuple(range(x.shape[0])); columns=tuple(range(2*wu.shape[0])); features=tuple(range(wu.shape[1]))
        qr=_pick(torch,q,rows); wr=_pick(torch,w,columns)
        er=_pick(torch,e,rows); wc=_pick(torch,w,cols=features)
        ar=s1[list(rows)]; br=ws[list(columns)]; gr=gs[list(rows)]
        f=wu.shape[0]
        forward=((model.matmul(qr,wr.T)*ar[:,None])*br).to(torch.bfloat16)
        dx_d=(model.matmul(er,wc)*gr[:,None]).to(torch.bfloat16)
        dx_e=((model.matmul(er[:,:f],wc[:f])+model.matmul(er[:,f:],wc[f:]))*gr[:,None]).to(torch.bfloat16)
        f64=(qr.double()@wr.double().T)*ar.double()[:,None]*br.double()
        fb=(qr.double().abs()@wr.double().T.abs())*ar.double()[:,None]*br.double()
        d64=(er.double()@wc.double())*gr.double()[:,None]
        db=(er.double().abs()@wc.double().abs())*gr.double()[:,None]
        hardware,ideal,record={},{},{}
        for arm in ('C','D','E'):
            state=ops.prepare(arm,wu,wg)
            u,g=ops.forward(arm,x,wu,wg,state)
            # Slice on CPU after transfer to avoid depending on CUDA indexing layout.
            actual=_pick(torch,torch.cat((u.detach().cpu(),g.detach().cpu()),1),rows,columns)
            key=arm+'_fprop_oracle'
            hardware[key]=torch.equal(actual.view(torch.int16),forward.view(torch.int16))
            ideal[key]=v1.oracle_diagnostics(torch,actual,f64,fb)
            record[key]=dict(actual=actual,hardware=forward,reference64=f64,absolute_product_sum64=fb)
            if arm in ('D','E'):
                dx=ops.dgrad(arm,du,dg,wu,wg,state)
                actual=_pick(torch,dx.detach().cpu(),rows,features)
                expected=dx_d if arm=='D' else dx_e
                key=arm+'_dgrad_oracle'
                hardware[key]=torch.equal(actual.view(torch.int16),expected.view(torch.int16))
                ideal[key]=v1.oracle_diagnostics(torch,actual,d64,db)
                record[key]=dict(actual=actual,hardware=expected,reference64=d64,absolute_product_sum64=db)
                del dx
            del u,g,state
        ops.require_valid()
    snapshot=dict(qx_rows=qr.view(torch.uint8),qw_output_rows=wr.view(torch.uint8),
                  qe_rows=er.view(torch.uint8),qw_input_columns=wc.view(torch.uint8),
                  activation_scales=ar,weight_scales=br,gradient_scales=gr,outputs=record)
    summary=dict(quantization=qflags,hardware=hardware,ideal=ideal,
        coordinates=dict(rows=list(rows),output_channels=list(columns),input_features=list(features)),
        scope='sampled production coordinates' if sampled else 'entire small fixture',
        hardware_mismatches={key:int(torch.count_nonzero(row['actual'].view(torch.int16)!=row['hardware'].view(torch.int16)))
                             for key,row in record.items()})
    return summary,snapshot


def replay_and_locality(torch,ops,v1):
    with torch.no_grad():
        x,wu,wg,du,dg=[t.cuda() for t in fixtures(torch)['ordinary']]
        state=ops.prepare('D',wu,wg)
        before=ops.forward('D',x,wu,wg,state)
        x[16:].mul_(32)
        after=ops.forward('D',x,wu,wg,state)
        locality=all(torch.equal(a[:16].view(torch.int16),b[:16].view(torch.int16)) for a,b in zip(before,after))
        badops=type(ops)('cuda:0'); bad=x.clone(); bad[0,0]=float('nan')
        badops.quantize(bad,'e4m3'); refused=False
        try: badops.require_valid()
        except ValueError as error:
            refused=str(error).startswith('NONFINITE:')
        del state,before,after,bad,badops
        x,wu,wg,du,dg=[t.cuda() for t in fixtures(torch)['ordinary']]
        def body():
            s=ops.prepare('D',wu,wg)
            u,g=ops.forward('D',x,wu,wg,s)
            return u,g,ops.dgrad('D',du,dg,wu,wg,s)
        graph,outs=v1.capture(torch,body,2)
        saved=tuple(t.clone() for t in outs)
        old=wu.clone(); wu.mul_(1.25)
        graph.replay(); torch.cuda.synchronize()
        changed=tuple(t.clone() for t in outs); fresh=body()
        refresh=(not torch.equal(saved[0].view(torch.int16),changed[0].view(torch.int16))
                 and v1.tuple_equal(torch,changed,fresh))
        wu.copy_(old); x.zero_(); du.zero_(); dg.zero_()
        graph.replay(); torch.cuda.synchronize()
        zero=all(bool(torch.isfinite(t).all()) and int(torch.count_nonzero(t))==0 for t in outs)
        del graph,outs,saved,old,changed,fresh
        ops.require_valid()
    return dict(token_locality=locality,nonfinite_refused=refused,refreshed_weights=refresh,zero_replay=zero)
