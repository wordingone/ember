# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""R1 for cce-document-v2: the 2026-09-28 fold-equivalence harness re-run with the MERGED + FOLDED function.

The 2026-09-28 run tested a two-piece-per-document fold prototype; this run tests what v2 actually executes: one
weighted CCE call per update over unique rows, per-row FP32 multiplier, FP32 in-kernel classifier accumulation.

Criterion: FROZEN, unchanged, read from its original file and refused unless its sha256 is a5524e5b... (the file is
not copied here; only its numeric fields enter the result). For each of five quantities (loss, hidden grad,
tied-classifier grad, SGD-style update lr*grad, one AdamW step) and each seed: treatment-vs-FP32-reference error <=
max(ratio * control-vs-FP32-reference error, floor). PASS requires all checks on all seeds AND the red exceeding
the limit on at least one quantity for every seed.

Arms. Control = production cce-document-v1 (document_streamed_loss over staged_inputs(fold=False): repeated answer
rows, one CCE call per document, BF16 classifier partials added). Treatment = cce-document-v2
(weighted_document_streamed_loss over staged_inputs(fold=True)). Red = the treatment with every weight forced to 1
(the answer multiplier dropped; denominator unchanged). Reference = FP32 dense cross-entropy over the control's
repeated rows (exact algebra). Real pack: image group 409652 built by the production input functions at weight 200;
hidden and classifier random BF16 at production shapes (hidden 1024, vocab 32768).

Bounds, refused before any device work: GPU utilization < 20% and memory used < 4 GiB at start
(nvidia-smi), this process capped at 8 GiB, wall < 5 minutes.

Usage: python fold_equivalence_merged_v2.py <prediction.json> <criterion.json> [<out.json>]"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import torch

CRITERION_SHA256 = 'a5524e5b4d15be1f7e082644437b0d957497fbc2ebdc9c02b1ff24bca0277919'
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TOOLS = ROOT / 'src/ember/infrastructure/tools/ember-restart-3b'
B0, W = 409652, 200
GPU_UTIL_MAX, GPU_USED_MAX_MIB, PROCESS_CAP_GIB, WALL_MAX_SECONDS = 20, 4096, 8, 300


def refuse(clause, **detail):
    print('FOLD_EQUIV_V2 REFUSED', clause, json.dumps(detail))
    sys.exit(4)


PRED, CRIT = Path(sys.argv[1]), Path(sys.argv[2])
OUT = Path(sys.argv[3]) if len(sys.argv) > 3 else HERE / 'fold-equivalence-merged-v2-result.json'
raw_crit = CRIT.read_bytes()
if hashlib.sha256(raw_crit).hexdigest() != CRITERION_SHA256:
    refuse('criterion-bytes-differ', found=hashlib.sha256(raw_crit).hexdigest())
crit = json.loads(raw_crit)

query = subprocess.run(['nvidia-smi', '--query-gpu=utilization.gpu,memory.used', '--format=csv,noheader,nounits'],
                       capture_output=True, text=True, check=True).stdout.strip().splitlines()[0]
gpu_util, gpu_used = (int(x.strip()) for x in query.split(','))
if gpu_util >= GPU_UTIL_MAX or gpu_used >= GPU_USED_MAX_MIB:
    refuse('gpu-not-idle', utilization=gpu_util, used_mib=gpu_used)

sys.path.insert(0, str(ROOT / 'src'))
os.environ['EMBER_ANSWER_WEIGHT'] = str(W)
from ember.model import ember_v0_streamed_loss as streamed  # noqa: E402

spec = importlib.util.spec_from_file_location('cia_step_runner_fold_v2', TOOLS / 'cia_step_runner.py')
runner = importlib.util.module_from_spec(spec); sys.modules[spec.name] = runner; spec.loader.exec_module(runner)
dev = torch.device('cuda')
total = torch.cuda.get_device_properties(dev).total_memory
torch.cuda.set_per_process_memory_fraction(min(1.0, PROCESS_CAP_GIB * 2 ** 30 / total), 0)

raw_pred = PRED.read_bytes()
data = json.loads(raw_pred); data = data.get('identity', data)['data']
stream, receipt, tokenizer, ledger = runner.open_input_stream(data)
image_text = runner.open_image_text(data, tokenizer, 1024)
pack = {'token_ids': [], 'target_ids': [], 'positions': [], 'document_starts': [], 'index': 0, 'phase': 'measured'}
runner.fill_pack(pack, stream, dict(data['cursor']), image_text, sequence=1024, documents=4, image_index=B0)
_, targets, _, control_sel = runner.staged_inputs(pack, dev)
_, targets_v2, _, treatment_sel = runner.staged_inputs(pack, dev, fold=True)
if not torch.equal(targets, targets_v2) or control_sel['denominator'] != treatment_sel['denominator']:
    refuse('staging-differs-outside-the-selection')
starts = list(pack['document_starts']) + [len(pack['target_ids'])]
lengths = [hi - lo for lo, hi in zip(starts, starts[1:])]
answers = list(pack['answer_rows'])
denominator = control_sel['denominator']
rows_expanded = sum(l if s is None else s[1] for s, l in zip(control_sel['selections'], lengths))
rows_unique = sum(l if s is None else len(s[0]) for s, l in zip(treatment_sel['selections'], lengths))
# Independent of every staged selection: counted from the pack's own targets and answer rows.
pack_loss_rows = sum(1 for t in pack['target_ids'] if t != runner.IGNORE_TARGET)
pack_answer_repeats = sum(1 for a in answers if pack['target_ids'][a] != runner.IGNORE_TARGET)
pack_weight_total = pack_loss_rows + (W - 1) * pack_answer_repeats
red_sel = {'selections': tuple(None if s is None else (s[0], torch.ones_like(s[1]), len(s[0]))
                               for s in treatment_sel['selections']), 'denominator': denominator}
op = streamed._cce_operator()
H, V = 1024, 32768
tgt = torch.where(targets < 0, torch.zeros_like(targets), targets)  # IGNORE rows are never selected


def make(seed):
    g = torch.Generator(device='cuda').manual_seed(seed)
    h = (torch.randn(len(tgt), H, device=dev, generator=g) * 1.0).to(torch.bfloat16).requires_grad_()
    c = (torch.randn(V, H, device=dev, generator=g) * 0.02).to(torch.bfloat16).requires_grad_()
    return h, c


executed = {}


def run(kind, seed):
    h, c = make(seed)
    if kind == 'control':
        loss = streamed.document_streamed_loss(h, c, tgt, lengths, denominator, operator=op,
                                               selections=control_sel['selections'])
    elif kind in ('treatment', 'red'):
        sel = treatment_sel if kind == 'treatment' else red_sel
        loss = streamed.weighted_document_streamed_loss(h, c, tgt, lengths, denominator, operator=op,
                                                        selections=sel['selections'])
        executed[kind] = loss.cce_executed  # read with executed_values after backward has synchronized
    else:  # FP32 dense reference over the control's repeated rows (exact algebra)
        h32, c32 = h.detach().float().requires_grad_(), c.detach().float().requires_grad_()
        acc, start = 0, 0
        for s, l in zip(control_sel['selections'], lengths):
            rows = torch.arange(start, start + l, device=dev) if s is None else s[0]
            acc = acc + torch.nn.functional.cross_entropy(h32.index_select(0, rows) @ c32.T, tgt.index_select(0, rows),
                                                          reduction='sum')
            start += l
        loss = acc / denominator
        loss.backward()
        return float(loss), h32.grad, c32.grad
    loss.backward()
    result = float(loss), h.grad.float(), c.grad.float()  # float() synchronizes
    if kind in executed:
        executed[kind] = streamed.executed_values(executed[kind])
    return result


def rel(a, b):
    return float((a - b).norm() / b.norm().clamp_min(1e-30))


def update(cg):
    sgd = -crit['lr_sgd'] * cg
    p = torch.nn.Parameter(torch.zeros_like(cg)); p.grad = cg.clone()
    torch.optim.AdamW([p], lr=crit['lr_adamw'], weight_decay=0.0).step()
    return sgd, p.detach()


def errors(x, ref):
    (l, hg, cg), (lr_, hgr, cgr) = x, ref
    s, a = update(cg); sr, ar = update(cgr)
    return {'loss_rel': abs(l - lr_) / abs(lr_), 'hidden_grad_rel_l2': rel(hg, hgr), 'classifier_grad_rel_l2': rel(cg, cgr),
            'sgd_update_rel_l2': rel(s, sr), 'adamw_update_rel_l2': rel(a, ar)}


t0 = time.time()
report = dict(goal_id='EMBER-02', workstream_id='EMBER-02A',
              next_executed_outcome='EMBER-02 first sufficiently pretrained clean-genesis 3B Ember',
              schema='ember-1945-fold-equivalence-merged-v2', criterion_sha256=CRITERION_SHA256,
              criterion=dict(ratio=crit['ratio'], floor=crit['floor'], lr_sgd=crit['lr_sgd'], lr_adamw=crit['lr_adamw'],
                             seeds=crit['seeds']),
              prediction_sha256=hashlib.sha256(raw_pred).hexdigest(), pack_group=B0, weight=W,
              gpu_at_start=dict(utilization_percent=gpu_util, used_mib=gpu_used),
              control='cce-document-v1 document_streamed_loss, staged_inputs(fold=False)',
              treatment='cce-document-v2 weighted_document_streamed_loss, staged_inputs(fold=True)',
              red='treatment with every weight forced to 1, denominator unchanged',
              rows_unique=rows_unique, rows_expanded=rows_expanded, pack_loss_rows=pack_loss_rows,
              pack_weight_total=pack_weight_total, removed_fraction=1 - rows_unique / rows_expanded,
              answer_rows=answers, docs=lengths, denominator=denominator, seeds=[])
ok = True
for seed in crit['seeds']:
    if time.time() - t0 > WALL_MAX_SECONDS:
        refuse('wall-bound', seconds=time.time() - t0)
    ref = run('reference', seed)
    control = run('control', seed); control2 = run('control', seed)
    treatment = run('treatment', seed)
    red = run('red', seed)
    e_control, e_treat, e_null, e_red = (errors(control, ref), errors(treatment, ref), errors(control2, control),
                                         errors(red, ref))
    row = dict(seed=seed, control_vs_ref=e_control, treatment_vs_ref=e_treat, control_vs_control_null=e_null,
               red_dropped_multiplier_vs_ref=e_red, checks={},
               treatment_executed=executed['treatment'], red_executed=executed['red'])
    for k in e_treat:
        limit = max(crit['ratio'] * e_control[k], crit['floor'][k])
        row['checks'][k] = dict(control=e_control[k], treatment=e_treat[k], red=e_red[k], limit=limit,
                                ok=e_treat[k] <= limit, red_refused=e_red[k] > limit)
        ok &= row['checks'][k]['ok']
    row['red_refused_on_any'] = any(c['red_refused'] for c in row['checks'].values())
    ok &= row['red_refused_on_any']
    # executed, not configured: one operator call, the pack's own loss-row count, and the device-reduced weight
    # sum equal to the pack's own weighted count and to the denominator
    row['executed_ok'] = (executed['treatment'] == dict(cce_calls=1, cce_rows=pack_loss_rows,
                                                        cce_weight_total=pack_weight_total)
                          and pack_weight_total == denominator)
    ok &= row['executed_ok']
    report['seeds'].append(row)
report['pass'] = bool(ok)
report['seconds'] = round(time.time() - t0, 1)
report['peak_alloc_gib'] = round(torch.cuda.max_memory_allocated() / 2 ** 30, 2)
OUT.write_bytes((json.dumps(report, indent=1) + '\n').encode('utf-8'))
print('FOLD_EQUIV_V2', 'PASS' if ok else 'FAIL', 'removed_fraction', round(report['removed_fraction'], 4),
      'seconds', report['seconds'], 'peak_alloc_gib', report['peak_alloc_gib'])
sys.exit(0 if ok else 3)
