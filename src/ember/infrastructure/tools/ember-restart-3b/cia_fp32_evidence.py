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
  master_moved_fraction     fraction of sampled master elements that differ from the owner's first observed master (the master path stepped)
  owners, sampled_elements, step_min, step_max
An owner whose optimizer step is still 0 (a gated first step leaves state with step 0 and zero moments) is skipped: its step size is 0/0.
The end record adds the changed fraction of the sampled working weights against the hour's start, the dtypes, the master count and the
schema read back from the written child optimizer-state file. require() refuses the hour when any of it is missing or contradicts the
declaration. `evidence_seconds` is the wall this module itself used (it runs inside the governed hour, so it is reported, not hidden).
"""
from __future__ import annotations

import math
import re
import time

import torch

SCHEMA = 'ember-fp32-master-evidence-v1'
GROUPS = ('embedding', 'attention', 'shared', 'experts', 'other')
SAMPLE = 65536
EVERY = 10000
PROBE_UPDATE = 2   # a checkpoint probe takes one in-loop sample here, so the one GPU probe measures the in-loop cost before a live hour does
KEYS = ('mean_abs_update_over_lr', 'median_sqrt_v_ratio', 'master_residual_fraction', 'master_moved_fraction', 'step_min', 'step_max')
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
        self._m0 = {}          # owner -> the master at its first observation (CPU float32 sample)
        self._cpu_index = {}   # numel -> the strided sample index, shared by every owner of that size
        self._device_index = {}   # (numel, device) -> that index on the device, uploaded once (not once per take)
        pick = track or (lambda name, p: p.requires_grad)
        started = time.perf_counter()
        self._start_sample = {name: take(p, self._index(p)) for name, p in self.inventory.items() if pick(name, p)}
        # The owner groups this hour is expected to report in its first and last row: every group with a tracked owner.
        self.expected_groups = sorted({owner_group(name) for name in self._start_sample})
        self.seconds += time.perf_counter() - started

    def _index(self, tensor):
        key = (tensor.numel(), str(tensor.device))
        index = self._device_index.get(key)
        if index is None:
            cpu = self._cpu_index.get(key[0])
            if cpu is None:
                cpu = self._cpu_index[key[0]] = _positions(key[0])
            index = self._device_index[key] = cpu.to(tensor.device)
        return index

    def observe(self, update):
        """Append one trace row from the live optimizer state (reads only)."""
        from cia_fp32_master import masters
        started = time.perf_counter()
        table = masters(self.optimizer)
        acc = {g: dict(owners=0, elements=0, abs_u=0.0, residual=0, moved=0, ratios=[], steps=[]) for g in GROUPS}
        at_step_zero = 0
        with torch.no_grad():
            for name, p in self.inventory.items():
                state = self.optimizer.state.get(p)
                if not state:
                    continue
                step = float(state['step'])
                if step == 0:
                    at_step_zero += 1
                    continue
                idx = self._index(p)
                m, v = take(state['exp_avg'], idx), take(state['exp_avg_sq'], idx)
                bc1, bc2 = 1 - self.beta1 ** step, 1 - self.beta2 ** step
                u = ((m / bc1) / ((v / bc2).sqrt() + self.eps)).abs()
                sv = v.sqrt()
                if name not in self._v0:
                    self._v0[name] = sv
                ratio = torch.where(self._v0[name] > 0, sv / self._v0[name].clamp_min(1e-30), torch.ones_like(sv))
                master = table.get(p)
                residual = moved = 0
                if master is not None:
                    sample = take(master, self._index(master))
                    residual = int((sample != take(p, idx)).sum())
                    moved = int((sample != self._m0.setdefault(name, sample)).sum())
                bucket = acc[owner_group(name)]
                bucket['owners'] += 1
                bucket['elements'] += int(idx.numel())
                bucket['abs_u'] += float(u.sum())
                bucket['residual'] += residual
                bucket['moved'] += moved
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
                             master_moved_fraction=b['moved'] / b['elements'],
                             step_min=min(b['steps']), step_max=max(b['steps']))
        spent = time.perf_counter() - started
        self.rows.append(dict(update=int(update), seconds=spent, owners_at_step_zero=at_step_zero, groups=groups))
        self.seconds += spent
        return self.rows[-1]

    def due(self, update, *, probe=False):
        """True at every `every` updates; a checkpoint probe also samples once at PROBE_UPDATE and records that row's seconds."""
        return update > 0 and (update % self.every == 0 or (probe and update == PROBE_UPDATE))

    def changed_fraction(self):
        """Fraction of the sampled working-weight elements that differ from their value at construction (a sampled estimate)."""
        total = {g: [0, 0] for g in GROUPS}
        with torch.no_grad():
            for name, before in self._start_sample.items():
                p = self.inventory[name]
                now = take(p, self._index(p))
                bucket = total[owner_group(name)]
                bucket[0] += before.numel()
                bucket[1] += int((now != before).sum())
        out = {g: dict(elements=e, changed_elements=c, changed_fraction=(c / e if e else None)) for g, (e, c) in total.items() if e}
        elements, changed = sum(e for e, _ in total.values()), sum(c for _, c in total.values())
        out['all'] = dict(elements=elements, changed_elements=changed, changed_fraction=(changed / elements if elements else None))
        return out

    def finish(self, update, *, child_optimizer_state_path=None, schema=None):
        """The receipt block: the trace, the changed fraction, dtypes, master count and the written schema."""
        from cia_fp32_master import check_invariant, masters
        self.observe(update)
        started = time.perf_counter()
        table = masters(self.optimizer)
        invariant_violations = len(check_invariant(self.optimizer))   # parameter == bf16(master) for every owner, read back from the live state
        dtypes = {'master': set(), 'exp_avg': set(), 'exp_avg_sq': set(), 'working': set()}
        for p, master in table.items():
            dtypes['master'].add(str(master.dtype))
            dtypes['working'].add(str(p.dtype))
            state = self.optimizer.state.get(p) or {}
            for key in ('exp_avg', 'exp_avg_sq'):
                if key in state:
                    dtypes[key].add(str(state[key].dtype))
        if schema is None and child_optimizer_state_path is not None:
            schema = read_optimizer_schema_version(child_optimizer_state_path)
        changed = self.changed_fraction()
        self.seconds += time.perf_counter() - started
        return dict(schema=SCHEMA, every_updates=self.every, sample_per_owner=SAMPLE, optimizer_schema=schema,
                    master_owner_count=len(table), dtypes={k: sorted(v) for k, v in dtypes.items()},
                    expected_groups=list(self.expected_groups), invariant_violations=invariant_violations,
                    changed=changed, trace=self.rows, evidence_seconds=self.seconds,
                    note='step size is read from the optimizer moments (weight decay excluded); the changed fraction and every trace value '
                         'are estimates over a fixed strided sample of each owner, not a gradient or full-tensor measurement')


def read_optimizer_schema_version(path):
    """The `schema_version` of a child optimizer-state.pt, read from its small `data.pkl` member alone: the file is never mapped and no tensor is
    read. It was `torch.load(..., mmap=True)` of the whole 5.3 GiB file for this one string; the job's commit rose by about the size of that file
    between the first restore verify and the S+1 update (39.12 against 34.25 GiB), and the mapped view is the suspect (#2119, review r1 item 4).
    The metadata unpickler is the counter's own: it admits shapes, storage references and plain values only."""
    import zipfile
    import parameter_counter
    with zipfile.ZipFile(path) as archive:
        payload = parameter_counter._load_checkpoint_metadata(archive)
    return payload.get('schema_version') if isinstance(payload, dict) else None


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def require(evidence, *, declared, probe=False):
    """Refuse the hour when it declares fp32_master_v1 and the evidence is missing, v2, bf16, empty, non-finite or shows the master path
    did not step. `probe` additionally demands the in-loop sample row. Returns the evidence."""
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
    expected = evidence.get('expected_groups')
    if not expected or not set(expected) <= set(GROUPS):
        raise ValueError(f'fp32 master evidence names no valid expected owner groups: {expected!r}')
    trace = evidence.get('trace') or []
    if len(trace) < 2 or trace[0]['update'] >= trace[-1]['update']:
        raise ValueError('fp32 master trace needs a start row and an end row')
    if probe and len(trace) < 3:
        raise ValueError('a checkpoint probe must carry an in-loop sample row between its start and end rows')
    first, last = trace[0]['groups'], trace[-1]['groups']
    if not first or not last:
        raise ValueError('fp32 master trace has an empty start or end row: no owner carried optimizer state when it was read')
    for label, row in (('start', first), ('end', last)):
        missing = sorted(set(expected) - set(row))
        if missing:
            raise ValueError(f'fp32 master trace {label} row lacks owner group(s) {missing}')
    for row in trace:
        for group, values in row['groups'].items():
            for key in KEYS:
                if not _finite(values.get(key)):
                    raise ValueError(f"fp32 master trace row at update {row.get('update')} group {group}: {key} is {values.get(key)!r}, not a finite number")
    for group in expected:
        if not last[group]['step_max'] > first[group]['step_max']:
            raise ValueError(f"fp32 master trace: group {group} optimizer step did not advance ({first[group]['step_max']} -> "
                             f"{last[group]['step_max']}): the master path did not step it")
    if not any(g['master_residual_fraction'] > 0 for g in last.values()):
        raise ValueError('fp32 master trace shows no master residual: the fp32 path did not execute')
    if not any(g['master_moved_fraction'] > 0 for g in last.values()):
        raise ValueError('fp32 master trace shows no sampled master that moved from its start value: the master path did not step')
    violations = evidence.get('invariant_violations')
    if not isinstance(violations, int) or isinstance(violations, bool) or violations != 0:
        raise ValueError(f'fp32 master invariant parameter == bf16(master) read back {violations!r} violating owner(s), not 0')
    changed = evidence.get('changed', {}).get('all', {})
    if not changed.get('elements') or not changed.get('changed_elements'):
        raise ValueError('fp32 master evidence shows no changed working weights')
    for group in expected:
        entry = evidence['changed'].get(group)
        if not entry or not _finite(entry.get('changed_fraction')):
            raise ValueError(f'fp32 master changed fraction is missing or not finite for group {group}')
    if not _finite(evidence.get('evidence_seconds')):
        raise ValueError('fp32 master evidence_seconds is not a finite number')
    return evidence
