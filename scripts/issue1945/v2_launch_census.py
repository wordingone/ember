# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Launch census for cce-document-v2 against cce-document-v1 on real H34-era packs (input to R3's count bounds).

For each of N consecutive packs (production fill_pack, weight 200): how many documents carry a row selection under
v1 and under v2. On the first pack whose image document is selected: device events (kernels, memcpy, memset) of
one v1 and one v2 forward+backward with the production CCE operator, counted by name with torch.profiler, plus the
v2 event count attributable to the four validation clauses (the _assert_async kernels and their operands), the
device weight reduction, and the pinned copy. Bounds: GPU idle at start, 8 GiB cap, host RSS reported.

Usage: python v2_launch_census.py <prediction.json> [<packs>]"""
import collections
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import torch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TOOLS = ROOT / 'src/ember/infrastructure/tools/ember-restart-3b'
B0, W = 409652, 200
PRED = Path(sys.argv[1])
PACKS = int(sys.argv[2]) if len(sys.argv) > 2 else 16
query = subprocess.run(['nvidia-smi', '--query-gpu=utilization.gpu,memory.used', '--format=csv,noheader,nounits'],
                       capture_output=True, text=True, check=True).stdout.strip().splitlines()[0]
util, used = (int(v.strip()) for v in query.split(','))
if util >= 20 or used >= 4096:
    print('CENSUS REFUSED gpu-not-idle', util, used); sys.exit(4)
sys.path.insert(0, str(ROOT / 'src'))
os.environ['EMBER_ANSWER_WEIGHT'] = str(W)
from ember.model import ember_v0_streamed_loss as streamed  # noqa: E402
spec = importlib.util.spec_from_file_location('cia_step_runner_census', TOOLS / 'cia_step_runner.py')
runner = importlib.util.module_from_spec(spec); sys.modules[spec.name] = runner; spec.loader.exec_module(runner)
dev = torch.device('cuda')
torch.cuda.set_per_process_memory_fraction(min(1.0, 8 * 2 ** 30 / torch.cuda.get_device_properties(0).total_memory), 0)

raw = PRED.read_bytes()
data = json.loads(raw); data = data.get('identity', data)['data']
stream, _, tokenizer, _ = runner.open_input_stream(data)
image_text = runner.open_image_text(data, tokenizer, 1024)
cursor = dict(data['cursor'])
packs, per_pack = [], []
for k in range(PACKS):
    pack = {'token_ids': [], 'target_ids': [], 'positions': [], 'document_starts': [], 'index': k, 'phase': 'measured'}
    runner.fill_pack(pack, stream, cursor, image_text, sequence=1024, documents=4, image_index=B0 + k)
    v1 = runner.loss_selection(pack, torch.device('cpu'))
    v2 = runner.loss_selection(pack, torch.device('cpu'), fold=True)
    count = lambda sel: 0 if sel is None else sum(1 for s in sel['selections'] if s is not None)
    per_pack.append(dict(pack=k, selected_documents_v1=count(v1), selected_documents_v2=count(v2),
                         answer_rows=len(pack.get('answer_rows', ())),
                         loss_rows=sum(1 for t in pack['target_ids'] if t != runner.IGNORE_TARGET)))
    packs.append(pack)

pack = next(p for p, row in zip(packs, per_pack) if row['selected_documents_v2'] > 0)
starts = list(pack['document_starts']) + [len(pack['target_ids'])]
lengths = [hi - lo for lo, hi in zip(starts, starts[1:])]
_, targets, _, sel_v1 = runner.staged_inputs(pack, dev)
_, _, _, sel_v2 = runner.staged_inputs(pack, dev, fold=True)
tgt = targets.clamp(min=0)
op = streamed._cce_operator()
g = torch.Generator(device='cuda').manual_seed(11)
h0 = (torch.randn(len(tgt), 1024, device=dev, generator=g)).to(torch.bfloat16)
c0 = (torch.randn(32768, 1024, device=dev, generator=g) * 0.02).to(torch.bfloat16)


# Raw mangled kernel symbols are not recorded: each event is labelled by the first matching keyword (checked in
# order) and a 12-hex digest of its full symbol, so two kernels sharing a label stay distinct.
LABELS = ('_cce_lse_forward_kernel', '_cce_backward_kernel', '_assert_async', 'Memcpy DtoH', 'Memcpy DtoD',
          'Memcpy HtoD', 'index_copy', 'indexFuncLargeIndex', 'vectorized_gather', 'scatter_gather', 'CatArrayBatchedCopy',
          'bfloat16_copy', 'direct_copy', 'and_kernel', 'sum_functorIddd', 'sum_functorIfff', 'BitwiseAnd',
          'compare_scalar_kernelIf', 'compare_scalar_kernelIx', 'CompareFunctor', 'AUnaryFunctor', 'FillFunctorIN3c108BFloat16',
          'FillFunctorIf', 'FillFunctorIi', 'FillFunctorIj', 'CUDAFunctor_addIN3c108BFloat16', 'CUDAFunctor_addIf',
          'CUDAFunctorOnSelf_add', 'BUnaryFunctorIfffNS0_15binary_internal10MulFunctor',
          'BinaryFunctorIfffNS0_15binary_internal10MulFunctor')


def label(name):
    digest = hashlib.sha256(name.encode()).hexdigest()[:12]
    word = next((w for w in LABELS if w in name), 'other')
    return '%s#%s' % (word, digest)


def call(kind):
    h, c = h0.clone().requires_grad_(), c0.clone().requires_grad_()
    torch.cuda.synchronize()
    with torch.profiler.profile(activities=[torch.profiler.ProfilerActivity.CUDA]) as prof:
        if kind == 'v1':
            loss = streamed.document_streamed_loss(h, c, tgt, lengths, sel_v1['denominator'], operator=op,
                                                   selections=sel_v1['selections'])
        else:
            loss = streamed.weighted_document_streamed_loss(h, c, tgt, lengths, sel_v2['denominator'], operator=op,
                                                            selections=sel_v2['selections'])
        loss.backward()
        torch.cuda.synchronize()
    names = collections.Counter()
    for event in prof.events():
        if event.device_type == torch.autograd.DeviceType.CUDA:
            names[label(event.name)] += 1
    return names


for kind in ('v1', 'v2'):
    call(kind)  # warm (autotune off, JIT compile)
v1, v2 = call('v1'), call('v2')
assert_kernels = sum(n for name, n in v2.items() if 'assert' in name.lower())
memcpy_v2 = sum(n for name, n in v2.items() if 'memcpy' in name.lower())
memcpy_v1 = sum(n for name, n in v1.items() if 'memcpy' in name.lower())
try:
    import psutil
    rss = psutil.Process().memory_info().peak_wset if hasattr(psutil.Process().memory_info(), 'peak_wset') else None
except ImportError:
    rss = None
selected = [row['selected_documents_v2'] for row in per_pack]
report = dict(goal_id='EMBER-02', workstream_id='EMBER-02A',
              next_executed_outcome='EMBER-02 first sufficiently pretrained clean-genesis 3B Ember',
              schema='ember-1945-v2-launch-census', prediction_sha256=hashlib.sha256(raw).hexdigest(),
              first_image_group=B0, weight=W, packs=per_pack,
              selected_documents_v2_per_pack=dict(min=min(selected), max=max(selected),
                                                  mean=sum(selected) / len(selected)),
              profiled_pack=pack['index'], profiled_selected_documents_v2=sum(
                  1 for s in sel_v2['selections'] if s is not None),
              device_events_v1=sum(v1.values()), device_events_v2=sum(v2.values()),
              assert_kernels_v2=assert_kernels, memcpy_v1=memcpy_v1, memcpy_v2=memcpy_v2,
              by_name_v1=dict(sorted(v1.items())), by_name_v2=dict(sorted(v2.items())),
              host_peak_working_set_bytes=rss, gpu_at_start=dict(utilization_percent=util, used_mib=used),
              peak_alloc_gib=round(torch.cuda.max_memory_allocated() / 2 ** 30, 2))
out = HERE / 'v2-launch-census-result.json'
out.write_bytes((json.dumps(report, indent=1) + '\n').encode('utf-8'))
print('CENSUS', json.dumps({k: report[k] for k in ('selected_documents_v2_per_pack', 'profiled_selected_documents_v2',
      'device_events_v1', 'device_events_v2', 'assert_kernels_v2', 'memcpy_v1', 'memcpy_v2',
      'host_peak_working_set_bytes', 'peak_alloc_gib')}))
