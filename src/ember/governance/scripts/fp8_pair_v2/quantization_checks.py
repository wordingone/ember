# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""CPU fixtures and emitted-instruction checks for independent FP8 rounding."""
import re


def rounding_inputs(torch,fmt):
    if fmt not in ('e4m3','e5m2'): raise ValueError('FORMAT: unknown FP8')
    dtype=torch.float8_e4m3fn if fmt=='e4m3' else torch.float8_e5m2
    last=126 if fmt=='e4m3' else 123
    levels=torch.arange(last+1,dtype=torch.int16).to(torch.uint8).view(dtype).float()
    mid=(levels[:-1]+levels[1:])/2
    below=torch.nextafter(mid,torch.full_like(mid,-float('inf')))
    above=torch.nextafter(mid,torch.full_like(mid,float('inf')))
    positive=torch.stack((below,mid,above),1).flatten()
    values=torch.cat((positive,-positive,torch.tensor([0.,-0.,levels[-1],-levels[-1]])))
    if len(values)>1024: raise ValueError('ROUNDING_FIXTURE: unexpected size')
    row=torch.zeros(1024,dtype=torch.float32); row[:len(values)]=values
    return torch.stack([torch.roll(row,shift) for shift in range(4)])


def check_direct_ptx(ptx,fmt):
    if fmt not in ('e4m3','e5m2') or not isinstance(ptx,str):
        raise ValueError('DIRECT_FP8_REQUIRED: invalid input')
    lines=[s.split('//',1)[0].strip() for s in ptx.splitlines()]
    body='\n'.join(lines)
    version=re.search(r'(?m)^\.version\s+(\d+)\.(\d+)',body)
    if (not version or tuple(map(int,version.groups()))<(8,1)
        or not re.search(r'(?m)^\.target\s+sm_89(?:\s|,|$)',body)):
        raise ValueError('DIRECT_FP8_REQUIRED: expected SM89 and PTX >= 8.1')
    opcode='cvt.rn.satfinite.'+fmt+'x2.f32'
    counts=sum(bool(re.match(re.escape(opcode)+r'\s',line)) for line in lines)
    if counts==0 or re.search(r'\blsb[0-9]+\b',body):
        raise ValueError('DIRECT_FP8_REQUIRED: missing native conversion or software tie-bit path')
    return dict(verified=True,format=fmt,opcode=opcode,instructions=counts)


def run_rounding_checks(torch,ops,c1,*,device='cuda:0'):
    checks={}; tensors={}
    for fmt in ('e4m3','e5m2'):
        inputs=rounding_inputs(torch,fmt)
        expected,scales=c1.quantize_rows(inputs,fmt)
        actual,actual_scale=ops.quantize(inputs.to(device),fmt)
        ops.require_valid()
        observed=actual.detach().cpu().view(torch.uint8)
        expected_bytes=expected.view(torch.uint8)
        observed_scales=actual_scale.detach().cpu()
        checks[fmt]=dict(bytes_exact=torch.equal(observed,expected_bytes),
            scale_exact=torch.equal(observed_scales,scales),
            unequal_bytes=int(torch.count_nonzero(observed!=expected_bytes)),
            elements=inputs.numel())
        tensors[fmt]=dict(inputs=inputs,actual_bytes=observed,expected_bytes=expected_bytes,
                         actual_scales=observed_scales,expected_scales=scales)
    return checks,tensors
