# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Hour evidence that the fp32 master path ran, and what it did to the step size (#2119, lead rulings 82495 / 82501).

Why: an hour that declares hour.precision_fix = fp32_master_v1 must PROVE the path executed (a lost flag trains native, writes a v2
checkpoint and passes every gate), and must show the size of the effective step, because the stored second moment of a bf16-trained
lineage is stuck high (bf16 cannot hold a 0.1% decay) and un-sticks in fp32: the paired hour is a package of four coupled changes
(weights can move, weight decay no longer rounds away, fp32 moments, v decay raising the step), and the size of the last one is read
from the optimizer, not inferred.

Every value is an estimate over a fixed strided sample (SAMPLE elements per owner, read from whatever device holds the tensor).
Everything here READS the optimizer state; nothing is written to it and no step is run. Python counters are not used as evidence:
under CUDA-graph capture the step's Python runs at capture time only, so the evidence is the device-side state the kernel itself
advanced (state['step']), the moments, the master and the weights.

Per owner group (embedding, attention, shared, experts, other) a trace row holds, at hour start, every `every` updates and hour end:
  mean_abs_update_over_lr   mean |m_hat| / (sqrt(v_hat) + eps) over the sample of each owner (Adam's update size, lr factored out)
  median_sqrt_v_ratio       median of sqrt(v) / sqrt(v at the first observation) over the same sample
  master_residual_fraction  fraction of sampled elements where the fp32 master differs from float(bf16 weight); zero for a native
                            bf16 hour, positive only when the master carries precision the bf16 weight cannot
  owners, sampled_elements, step_min, step_max
The end record adds the changed fraction of the sampled working weights against the hour's start, the dtypes, the master count and the
schema read back from the written child optimizer-state file. require() refuses the hour when any of it is missing or contradicts the
declaration. `evidence_seconds` is the wall this module itself used (it runs inside the governed hour, so it is reported, not hidden).
"""
from __future__ import annotations

import re
import time

import torch

SCHEMA = 'ember-fp32-master-evidence-v1'
GROUPS = ('embedding', 'attention', 'shared', 'experts', 'other')
SAMPLE = 65536
EVERY = 10000
V3 = 'ember-cia-placed-optimizer-state-v3'


def owner_group(name):
    if name.startswith('experts.'):
        return 'experts'
    if name.startswith('embedding'):
        return 'embedding'
    if re.search(r'(^|\.)attention\.', name):
        return 'attention'
    if re.search(r'(^|\.)shared\.', name):
        return 'shared'
    return 'other'


def _positions(numel):
    count = min(SAMPLE, numel)
    return torch.linspace(0, numel - 1, steps=count, dtype=torch.float64).round().long().unique()


def take(tensor, positions):
    """The sampled elements of any tensor as CPU float32, wherever it lives (GPU parameters, CPU expert banks, optimizer state)."""
    flat = tensor.detach().reshape(-1)
    return flat[positions.to(flat.device)].to(device='cpu', dtype=torch.float32)


class Evidence:
    """One per fp32 hour. `inventory` maps owner name to Parameter. `track` limits which owners enter the changed-fraction sample
    (default: every parameter that requires grad)."""

    def __init__(self, optimizer, inventory, *, every=EVERY, track=None):
        group = optimizer.param_groups[0]
        self.optimizer, self.inventory, self.every = optimizer, dict(inventory), every
        self.beta1, self.beta2 = group['betas']
        self.eps = group['eps']
        self.rows = []
        self.seconds = 0.0
        self._v0 = {}          # owner -> sqrt(v) at its first observation (CPU float32 sample)
        self._positions_cache = {}
        pick = track or (lambda name, p: p.requires_grad)
        started = time.perf_counter()
        self._start_sample = {name: take(p, self._positions(name, p)) for name, p in self.inventory.items() if pick(name, p)}
        self.seconds += time.perf_counter() - started

    def _positions(self, name, p):
        if name not in self._positions_cache:
            self._positions_cache[name] = _positions(p.numel())
        return self._positions_cache[name]

    def observe(self, update):
        """Append one trace row from the live optimizer state (reads only)."""
        from cia_fp32_master import masters
        started = time.perf_counter()
        table = masters(self.optimizer)
        acc = {g: dict(owners=0, elements=0, abs_u=0.0, residual=0, ratios=[], steps=[]) for g in GROUPS}
        with torch.no_grad():
            for name, p in self.inventory.items():
                state = self.optimizer.state.get(p)
                if not state:
                    continue
                idx = self._positions(name, p)
                m, v = take(state['exp_avg'], idx), take(state['exp_avg_sq'], idx)
                step = float(state['step'])
                bc1, bc2 = 1 - self.beta1 ** step, 1 - self.beta2 ** step
                u = ((m / bc1) / ((v / bc2).sqrt() + self.eps)).abs()
                sv = v.sqrt()
                if name not in self._v0:
                    self._v0[name] = sv
                ratio = torch.where(self._v0[name] > 0, sv / self._v0[name].clamp_min(1e-30), torch.ones_like(sv))
                master = table.get(p)
                residual = 0 if master is None else int((take(master, idx) != take(p, idx)).sum())
                bucket = acc[owner_group(name)]
                bucket['owners'] += 1
                bucket['elements'] += int(idx.numel())
                bucket['abs_u'] += float(u.sum())
                bucket['residual'] += residual
                bucket['ratios'].append(ratio)
                bucket['steps'].append(step)
        groups = {}
        for g, b in acc.items():
            if not b['owners']:
                continue
            groups[g] = dict(owners=b['owners'], sampled_elements=b['elements'],
                             mean_abs_update_over_lr=b['abs_u'] / b['elements'],
                             median_sqrt_v_ratio=float(torch.cat(b['ratios']).median()),
                             master_residual_fraction=b['residual'] / b['elements'],
                             step_min=min(b['steps']), step_max=max(b['steps']))
        self.rows.append(dict(update=int(update), groups=groups))
        self.seconds += time.perf_counter() - started
        return self.rows[-1]

    def due(self, update):
        return update > 0 and update % self.every == 0

    def changed_fraction(self):
        """Fraction of the sampled working-weight elements that differ from their value at construction (a sampled estimate)."""
        total = {g: [0, 0] for g in GROUPS}
        with torch.no_grad():
            for name, before in self._start_sample.items():
                p = self.inventory[name]
                now = take(p, self._positions(name, p))
                bucket = total[owner_group(name)]
                bucket[0] += before.numel()
                bucket[1] += int((now != before).sum())
        out = {g: dict(elements=e, changed_elements=c, changed_fraction=(c / e if e else None)) for g, (e, c) in total.items() if e}
        elements, changed = sum(e for e, _ in total.values()), sum(c for _, c in total.values())
        out['all'] = dict(elements=elements, changed_elements=changed, changed_fraction=(changed / elements if elements else None))
        return out

    def finish(self, update, *, child_optimizer_state_path=None, schema=None):
        """The receipt block: the trace, the changed fraction, dtypes, master count and the written schema."""
        from cia_fp32_master import masters
        self.observe(update)
        started = time.perf_counter()
        table = masters(self.optimizer)
        dtypes = {'master': set(), 'exp_avg': set(), 'exp_avg_sq': set(), 'working': set()}
        for p, master in table.items():
            dtypes['master'].add(str(master.dtype))
            dtypes['working'].add(str(p.dtype))
            state = self.optimizer.state.get(p) or {}
            for key in ('exp_avg', 'exp_avg_sq'):
                if key in state:
                    dtypes[key].add(str(state[key].dtype))
        if schema is None and child_optimizer_state_path is not None:
            payload = torch.load(child_optimizer_state_path, map_location='cpu', weights_only=True, mmap=True)
            schema = payload.get('schema_version')
        changed = self.changed_fraction()
        self.seconds += time.perf_counter() - started
        return dict(schema=SCHEMA, every_updates=self.every, sample_per_owner=SAMPLE, optimizer_schema=schema,
                    master_owner_count=len(table), dtypes={k: sorted(v) for k, v in dtypes.items()},
                    changed=changed, trace=self.rows, evidence_seconds=self.seconds,
                    note='step size is read from the optimizer moments (weight decay excluded); the changed fraction and every trace value '
                         'are estimates over a fixed strided sample of each owner, not a gradient or full-tensor measurement')


def require(evidence, *, declared):
    """Refuse the hour when it declares fp32_master_v1 and the evidence is missing, v2, bf16 or empty. Returns the evidence."""
    if not declared:
        return evidence
    if not isinstance(evidence, dict) or evidence.get('schema') != SCHEMA:
        raise ValueError('hour declares precision_fix fp32_master_v1 but carries no fp32 master evidence')
    if evidence.get('optimizer_schema') != V3:
        raise ValueError(f"hour declares fp32_master_v1 but the child optimizer state is {evidence.get('optimizer_schema')!r}, not {V3}")
    if not evidence.get('master_owner_count'):
        raise ValueError('hour declares fp32_master_v1 but no owner has a master')
    dtypes = evidence.get('dtypes') or {}
    if (dtypes.get('master') != ['torch.float32'] or dtypes.get('exp_avg') != ['torch.float32']
            or dtypes.get('exp_avg_sq') != ['torch.float32'] or dtypes.get('working') != ['torch.bfloat16']):
        raise ValueError(f'hour declares fp32_master_v1 but the optimizer dtypes are {dtypes}')
    trace = evidence.get('trace') or []
    if len(trace) < 2 or trace[0]['update'] >= trace[-1]['update']:
        raise ValueError('fp32 master trace needs a start row and an end row')
    first, last = trace[0]['groups'], trace[-1]['groups']
    if not first or not last:
        raise ValueError('fp32 master trace has an empty start or end row: no owner carried optimizer state when it was read')
    if any(row['groups'][g].get('mean_abs_update_over_lr') is None for row in trace for g in row['groups']):
        raise ValueError('fp32 master trace has no per-group step size')
    if not any(g['master_residual_fraction'] > 0 for g in last.values()):
        raise ValueError('fp32 master trace shows no master residual: the fp32 path did not execute')
    changed = evidence.get('changed', {}).get('all', {})
    if not changed.get('elements') or not changed.get('changed_elements'):
        raise ValueError('fp32 master evidence shows no changed working weights')
    return evidence
