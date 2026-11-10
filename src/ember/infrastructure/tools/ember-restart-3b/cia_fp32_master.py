# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""fp32 master weights and fp32 AdamW moments for the trainable set (#2119, lead ruling 82420 item 1).

Why: a bf16 weight |w| in [2^e, 2^(e+1)) moves under an in-place update only when |update| >= 2^(e-8); at lr 1e-4 about 71%
of the dense weights of the H48 child cannot move at all (state/fp32-master-20261110/headroom-h48child.json). The master path
keeps the weight and both moments in fp32, runs the SAME fused AdamW kernel over them, and writes the round-to-nearest bf16
view back to the working parameter, so the bf16 weights the model computes with are always bf16(master).

Layout: masters live in a side table on the optimizer (optimizer._ember_masters: Parameter -> fp32 tensor), keyed by the Parameter
OBJECT through torch's identity-keyed weak dictionary, never by id(): a freed Parameter drops its master with it, so a later
Parameter that happens to reuse the address can never inherit a stale master (lead review 82486 Q1). The optimizer state keeps
exactly the native fields {step, exp_avg, exp_avg_sq} (fp32 here), so every existing field-set check still holds.
Invariant I: for every parameter with a master, parameter == master.to(bfloat16) bit for bit, after every step and after restore.
Expert paging copies a bank Parameter's data to a device buffer (`source.detach().to(device, copy=True)`, ember_v0_residency.py
lease) and never creates or replaces the bank Parameter that the optimizer owns, so a page-out/page-in leaves the table alone.
"""
from __future__ import annotations

import torch
from torch.utils.weak import WeakTensorKeyDictionary

SCHEMA = 'fp32_master_v1'


def masters(optimizer):
    table = getattr(optimizer, '_ember_masters', None)
    if table is None:
        table = optimizer._ember_masters = WeakTensorKeyDictionary()
    return table


def enabled(optimizer):
    return getattr(optimizer, '_ember_fp32_master', False) is True


def enable(optimizer):
    """Switch the optimizer to the master treatment. Idempotent. Any bf16 state already present (a v2 parent) is converted
    exactly by convert_loaded()."""
    for group in optimizer.param_groups:
        if group.get('fused') is not True or group.get('amsgrad') or group.get('maximize'):
            raise ValueError('fp32 master supports fused non-amsgrad AdamW only')
        if any(p.dtype != torch.bfloat16 for p in group['params']):
            raise ValueError('fp32 master requires bf16 working parameters')
    optimizer._ember_fp32_master = True
    masters(optimizer)
    convert_loaded(optimizer)
    return optimizer


def convert_loaded(optimizer):
    """Make state loaded as bf16 (a v2 checkpoint) master-form, exactly: moment = float(moment) (bf16 -> fp32 is exact), master =
    float(parameter) (exact), step unchanged. Parameters that already have a master are left alone. Call after
    optimizer.load_state_dict()."""
    table = masters(optimizer)
    with torch.no_grad():
        for group in optimizer.param_groups:
            for p in group['params']:
                state = optimizer.state.get(p)
                if not state:
                    continue
                for key in ('exp_avg', 'exp_avg_sq'):
                    if state[key].dtype == torch.bfloat16:
                        state[key] = state[key].to(torch.float32)
                    elif state[key].dtype != torch.float32:
                        raise ValueError('fp32 master found a moment that is neither bf16 nor fp32')
                if p not in table:
                    table[p] = p.detach().to(torch.float32).clone()


def install(optimizer, state_by_index, masters_by_index):
    """Install a v3 payload after optimizer.load_state_dict({'state': {}, 'param_groups': ...}) (load_state_dict would cast fp32
    moments to the bf16 parameter dtype). Keys are the positions torch's state_dict uses (parameters in param_groups order)."""
    params = [p for group in optimizer.param_groups for p in group['params']]
    table = masters(optimizer)
    if set(masters_by_index) != {i for i, fields in state_by_index.items() if fields}:
        raise ValueError('fp32 master install: masters must cover exactly the owners with state')
    for i, fields in state_by_index.items():
        if fields:
            optimizer.state[params[i]] = dict(fields)
    for i, tensor in masters_by_index.items():
        table[params[i]] = tensor


def _ensure(optimizer, p):
    """Create lazy fp32 state and the master for a parameter on its first step."""
    state = optimizer.state[p]
    if not state:
        state['step'] = torch.zeros((), dtype=torch.float32, device=p.device)
        state['exp_avg'] = torch.zeros_like(p, dtype=torch.float32, memory_format=torch.preserve_format)
        state['exp_avg_sq'] = torch.zeros_like(p, dtype=torch.float32, memory_format=torch.preserve_format)
    table = masters(optimizer)
    if p not in table:
        table[p] = p.detach().to(torch.float32).clone()
    return state, table[p]


def step(optimizer, group, params, found_inf):
    """One fused AdamW launch over `params` (bf16, grads present) of one optimizer group, in fp32, then copy-back.

    Same kernel and arguments as the three native call sites (optimizer.step, gated_optimizer_step, SegmentOptimizer._launch);
    only the tensors differ: fp32 master as the parameter, an fp32 copy of the gradient, fp32 moments. When found_inf is set
    the kernel leaves the master and the moments untouched and the copy-back rewrites the identical bf16 view (invariant I).
    Runs on the caller's current CUDA stream; the copy-back is ordered after the kernel on that stream."""
    from torch.optim.adam import adam
    if not params:
        return
    beta1, beta2 = group['betas']
    ms, gs, avgs, sqs, steps = [], [], [], [], []
    for p in params:
        state, master = _ensure(optimizer, p)
        ms.append(master)
        gs.append(p.grad.to(torch.float32))
        avgs.append(state['exp_avg'])
        sqs.append(state['exp_avg_sq'])
        steps.append(state['step'])
    with torch.no_grad():
        adam(ms, gs, avgs, sqs, [], steps, amsgrad=False, has_complex=False, beta1=beta1, beta2=beta2, lr=group['lr'],
             weight_decay=group['weight_decay'], eps=group['eps'], maximize=False, foreach=group['foreach'],
             capturable=group['capturable'], differentiable=group['differentiable'], fused=True,
             grad_scale=None, found_inf=found_inf, decoupled_weight_decay=group['decoupled_weight_decay'])
        for p, master in zip(params, ms):
            p.copy_(master)


def check_invariant(optimizer):
    """Names of parameters whose bf16 value differs from bf16(master): empty when invariant I holds."""
    bad = []
    table = masters(optimizer)
    for group in optimizer.param_groups:
        for p in group['params']:
            master = table.get(p)
            if master is not None and not torch.equal(p.detach(), master.to(torch.bfloat16)):
                bad.append(id(p))
    return bad
