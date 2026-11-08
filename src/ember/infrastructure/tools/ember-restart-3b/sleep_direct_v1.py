# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""SLEEP-1 direct mode (#2119, ruling (b)): the SLEEP-1 objective trains the 5 target weights themselves with the wake
child's own restored optimizer, so the consolidated child publishes as an ordinary CIA first descendant of that child.

Why not the merged low-rank delta of sleep_consolidate_v1.main(): the CIA lineage refuses a parameter whose bytes change
while its own optimizer clock stays put ("CIA inactive parameter bytes differ from parent"). Here every changed byte
comes from a real AdamW step on that parameter, so the existing lineage, counter and scorer read the child unchanged.
Deviation from the paper, recorded in the receipt: a full-rank update on 5 weights, not rank-64 experts.

Student = the parent child rebuilt exactly as its hour built it (identity support, optimizer kwargs, resident experts),
restored through load_checkpoint_artifacts (model AND optimizer moments) at the parent's own lr, so optimizer_identity
and placement equal the parent's. Only the targets carry requires_grad during the pass; the flags are restored before
publish so the recorded placement is the parent's. Teacher = a frozen checkpoint (no optimizer, paged).
Targets = the layer-11 shared up/gate/down (fixed) + the down projections of the 2 most-routed layer-23 experts among the
student's trainable experts, counted on the teacher over the prefixes (routing-counts.json).
Custody: OUT/measurement-sleep1/trained-child (+ hour-result.json with child_manifest_sha256) so the hour scorer's derive
and smoke_load_child_v1 read it unchanged.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path

import torch

for _p in (Path(__file__).resolve().parent, Path(__file__).resolve().parents[4]):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
import sleep_consolidate_v1 as sleep  # noqa: E402

FIXED_TARGETS = tuple(f'layers.11.shared.{p}.weight' for p in ('up', 'gate', 'down'))
ROUTED_LAYER = 23
DEVIATION = 'full-rank update on 5 weights, not rank-64 experts; paper-fidelity deferred to SLEEP-2'


def pick_routed(routing_counts: dict, trainable_experts, k=2, layer=ROUTED_LAYER):
    """The k most-routed experts at `layer` among the student's trainable experts (ties: lower expert id)."""
    ranked = sorted(((c, int(key.split(':')[1])) for key, c in routing_counts.items()
                     if int(key.split(':')[0]) == layer and int(key.split(':')[1]) in set(trainable_experts)),
                    key=lambda ce: (-ce[0], ce[1]))
    if len(ranked) < k:
        raise ValueError(f'fewer than {k} trainable experts were routed at layer {layer}')
    return [f'experts.{e}.layers.{layer}.down.weight' for _c, e in ranked[:k]]


def relative_norms(before: dict, inventory: dict) -> dict:
    return {n: float((inventory[n].detach().float().cpu() - w0).norm() / w0.norm().clamp_min(1e-30)) for n, w0 in before.items()}


def advance_cursor(cursor: dict, steps: int, tokens: int) -> dict:
    """Same shard and record (the sleep pass reads no new training data); step and tokens advance by the pass."""
    return dict(cursor, global_step=cursor['global_step'] + steps, tokens_seen=cursor['tokens_seen'] + tokens)


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[3])
    ap.add_argument('--teacher-root', required=True)
    ap.add_argument('--teacher-manifest-sha256', required=True)
    ap.add_argument('--student-root', required=True)
    ap.add_argument('--student-manifest-sha256', required=True)
    ap.add_argument('--student-prediction', required=True, help="the parent hour's prediction.json (its identity)")
    ap.add_argument('--prefixes', required=True)
    ap.add_argument('--prefixes-sha256', required=True)
    ap.add_argument('--steps', type=int, required=True)
    ap.add_argument('--batch', type=int, default=4)
    ap.add_argument('--cont-len', type=int, default=32)
    ap.add_argument('--wall-seconds', type=int, default=3300)
    ap.add_argument('--device', default='cuda:0')
    ap.add_argument('--frozen-prediction', required=True, help='criteria text frozen into the receipt before step 1')
    ap.add_argument('--out', required=True)
    return ap.parse_args(argv)


def _write_new(path: Path, value) -> None:
    with path.open('x', encoding='utf-8') as f:
        f.write(json.dumps(value, indent=1, sort_keys=True) + '\n')
        f.flush(); os.fsync(f.fileno())


def check_prefixes(prefixes, cont_len, max_positions=4096):
    """Every prefix is a non-empty list of int token ids whose prefix + continuation fits one packed forward.
    (The first smoke paid a 24-minute load to learn that 4093 of 4096 prefixes were empty.)"""
    if not prefixes:
        raise ValueError('no prefixes')
    for i, p in enumerate(prefixes):
        if not isinstance(p, list) or not p or not all(type(t) is int and t >= 0 for t in p):
            raise ValueError(f'prefix {i} is empty or not a list of token ids')
        if len(p) + cont_len > max_positions:
            raise ValueError(f'prefix {i} plus continuation exceeds {max_positions} positions')


def main(argv=None):  # pragma: no cover - GPU binding, exercised by the governed run
    args = parse_args(argv)
    import cia_step_runner as runner
    import checkpoint_artifacts as artifacts
    from ember.model.ember_v0_decoder import CIADecoder
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=False)
    custody = out / 'measurement-sleep1'
    custody.mkdir()
    device = torch.device(args.device)
    if hashlib.sha256(Path(args.prefixes).read_bytes()).hexdigest() != args.prefixes_sha256:
        raise ValueError('prefixes sha differs from its declaration')
    prefixes = [json.loads(l)['tokens'] for l in Path(args.prefixes).read_text(encoding='utf-8').splitlines() if l.strip()]
    check_prefixes(prefixes, args.cont_len)   # before any load: a malformed prefix must not cost a GPU window
    identity = json.loads(Path(args.student_prediction).read_text(encoding='utf-8'))['identity']
    receipt = dict(kind='sleep-1-consolidation-direct', deviation=DEVIATION, frozen_prediction=args.frozen_prediction,
                   teacher=args.teacher_manifest_sha256, student_in=args.student_manifest_sha256,
                   prefixes_sha256=args.prefixes_sha256, alpha=sleep.ALPHA, lambda_=sleep.LAMBDA, gamma=sleep.GAMMA, z0=sleep.Z0,
                   batch=args.batch, cont_len=args.cont_len, steps_requested=args.steps)
    _write_new(out / 'sleep-frozen.json', receipt)   # frozen before the first step

    # teacher: frozen, paged, no optimizer
    treceipt = artifacts.published_checkpoint_receipt(Path(args.teacher_root))
    tv, tensors, _o, _r = artifacts._cia_validated_checkpoint(Path(args.teacher_root), treceipt, retain_model=True,
                                                            max_restore_payload_bytes=40 * 2 ** 30)
    if tv['checkpoint_manifest_sha256'] != args.teacher_manifest_sha256:
        raise ValueError('teacher manifest differs')
    teacher = CIADecoder(architecture_config=tv['architecture_config']).materialize_cpu(seed=0)
    tinv = teacher.parameter_inventory()
    with torch.no_grad():
        for name, value in tensors.items():
            tinv[name].copy_(value)
    del tensors
    sleep.freeze_except(tinv, ())
    teacher.eval()
    teacher.activate_cuda(device)
    torch.cuda.reset_peak_memory_stats(device)
    globals_log = out / 'torch-globals.jsonl'

    def record(row):
        row['t'] = round(time.monotonic(), 2)
        with globals_log.open('a', encoding='utf-8') as f:
            f.write(json.dumps(row) + '\n')
    scope = sleep.GlobalScope(record)   # captured right after the teacher build, before any student work

    # student: the parent's hour build, then the full restore (model + moments) at the parent's own lr
    sreceipt = artifacts.published_checkpoint_receipt(Path(args.student_root))
    if sreceipt['checkpoint_manifest_sha256'] != args.student_manifest_sha256:
        raise ValueError('student manifest differs')
    student = CIADecoder(architecture_config=sreceipt['architecture_config'], **runner.decoder_kwargs(identity)).materialize_cpu(seed=identity['seed'])
    support = identity['support']
    student.apply_update_support(support['locus'], experts=tuple(support['experts']))
    inventory = student.parameter_inventory()
    optimizer = torch.optim.AdamW(list(inventory.values()), **runner.optimizer_kwargs(identity['optimizer']))
    if {g['lr'] for g in optimizer.param_groups} != {sreceipt['optimizer_identity']['defaults']['lr']}:
        raise ValueError('student optimizer lr is not the parent lr')
    student.activate_cuda(device, resident_capacity=4, resident_experts=tuple(support['experts']), optimizer=optimizer)
    restored = artifacts.load_checkpoint_artifacts(student, optimizer, Path(args.student_root), sreceipt,
                                                   max_transient_scratch_bytes=10 * runner.GIB, host_commit_reserve_bytes=16 * runner.GIB)
    cursor = restored['data_cursor']

    record(dict(who='after_student_restore', **sleep.torch_globals()))
    with scope('teacher_probe'), sleep.step_context(teacher, device):
        probe = teacher.embed_text(torch.tensor(prefixes[0], dtype=torch.long, device=device))
    record(dict(who='teacher_embed_after_restore', dtype=str(probe.dtype), shape=list(probe.shape), device=str(probe.device)))
    del probe
    with scope('teacher_count_routes'):
        routing = sleep.count_routes(teacher, prefixes, device)
    (out / 'routing-counts.json').write_text(json.dumps(routing, indent=1) + '\n', encoding='utf-8')
    targets = list(FIXED_TARGETS) + pick_routed(routing, support['experts'])
    flags = {n: p.requires_grad for n, p in inventory.items()}
    if not all(flags[t] for t in targets):
        raise ValueError('a target is outside the parent update support')
    before = {t: inventory[t].detach().float().cpu().clone() for t in targets}
    for n, p in inventory.items():
        p.requires_grad_(n in targets); p.grad = None
    student.train()

    def fn(model, who):
        def logits(tokens):
            t = torch.tensor(tokens, dtype=torch.long, device=device)
            pos = torch.tensor([[i, 0, 0] for i in range(len(tokens))], dtype=torch.long, device=device)
            with scope(who), sleep.step_context(model, device):
                embedded = model.embed_text(t)
                if embedded.dtype != torch.bfloat16 or not 1 <= len(embedded) <= 4096:
                    record(dict(who=who, refusal='embedded', dtype=str(embedded.dtype), length=len(embedded)))
                return model(embedded, pos, document_starts=(0,))
        return logits

    ledger = sleep.Ledger(out / 'self-dream-ledger.jsonl', dict(teacher=args.teacher_manifest_sha256, student=args.student_manifest_sha256))
    started, rows, counts = time.perf_counter(), [], {}
    for step in range(args.steps):
        if time.perf_counter() - started > args.wall_seconds:
            break
        t0 = time.perf_counter()
        batch = [prefixes[(step * args.batch + j) % len(prefixes)] for j in range(args.batch)]
        terms = sleep.consolidation_step(fn(student, 'student'), fn(teacher, 'teacher'), [], optimizer, batch, cont_len=args.cont_len, seed=step, ledger=ledger)
        if not all(math.isfinite(v) for v in terms.values()):
            raise ValueError(f'non-finite loss at step {step}')
        for t in targets:
            counts[t] = counts.get(t, 0) + 1
        rows.append(dict(step=step, seconds=time.perf_counter() - t0, peak_gib=torch.cuda.max_memory_allocated(device) / 2 ** 30, **terms))
        with (out / 'steps.jsonl').open('a', encoding='utf-8') as f:
            f.write(json.dumps(rows[-1]) + '\n')
    torch.cuda.synchronize(device)
    dream_tokens = ledger.tokens
    norms = relative_norms(before, inventory)
    for n, p in inventory.items():
        p.requires_grad_(flags[n])
    optimizer.zero_grad(set_to_none=True)

    def verifier(candidate, _receipt):
        result = subprocess.run([sys.executable, '-I', str(Path(__file__).with_name('parameter_counter.py')),
                                 '--model-config', str(runner.ROOT / runner.CONFIG),
                                 '--checkpoint-manifest', str(candidate / 'checkpoint-manifest.json'), '--active-expert', 'all'],
                                stdin=subprocess.DEVNULL, capture_output=True, timeout=600)
        if result.returncode:
            raise ValueError('independent checkpoint counter refused: ' + result.stderr.decode('utf-8', 'replace')[-2048:])
        measured = json.loads(result.stdout)
        _write_new(candidate / 'parameter-counter-receipt.json', measured)
        return measured

    cap = 10 * runner.GIB
    child = artifacts.write_checkpoint_artifacts(student, optimizer, custody / 'trained-child',
        launch_seed=identity['seed'], rng_state={'cpu': torch.get_rng_state(), 'cuda': torch.cuda.get_rng_state(device)},
        data_cursor=advance_cursor(cursor, len(rows), dream_tokens),
        model_config_sha256=identity['config_sha256'], contract_sha256=identity['source_sha256']['src/ember/model/ember_v0_contract.py'],
        expert_genesis_sha256={}, max_serialized_bytes=cap, max_transient_scratch_bytes=cap, host_commit_reserve_bytes=16 * runner.GIB,
        pre_publish_verifier=verifier, cia_parent_checkpoint=Path(args.student_root), cia_owner_update_counts=dict(counts),
        cia_lr_declaration=None)
    receipt.update(targets=targets, routing_counts_file='routing-counts.json', steps_done=len(rows), dream_tokens=dream_tokens,
                   ledger_rows=ledger.rows, seconds=time.perf_counter() - started, owner_update_counts=counts,
                   relative_update_norm=norms, peak_gib=max((r['peak_gib'] for r in rows), default=0.0),
                   child_manifest_sha256=child['checkpoint_manifest_sha256'], lineage=child.get('lineage'),
                   claim='The consolidated child is the student after AdamW steps on the 5 targets only; published as a CIA first descendant of the student.')
    _write_new(out / 'sleep-receipt.json', receipt)
    _write_new(custody / 'hour-result.json', dict(child_manifest_sha256=child['checkpoint_manifest_sha256'], kind='sleep-1-consolidation-direct',
               parent_manifest_sha256=args.student_manifest_sha256, sleep_receipt='../sleep-receipt.json'))
    print('SLEEP1_DIRECT_DONE ' + json.dumps(dict(child=child['checkpoint_manifest_sha256'], steps=len(rows), norms=norms,
                                                  peak_gib=receipt['peak_gib'])), flush=True)
    return receipt


if __name__ == '__main__':  # pragma: no cover
    main()
