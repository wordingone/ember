"""Bounded CIA trajectory observations and comparisons; no general qualification authority."""
# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import hashlib
import gc
import json
import math
import os
import weakref
from pathlib import Path

import torch

TRAJECTORY = 'reference-noise-floor-64-v1'
UPDATES = 64
RELATIVE_L2_MAX = 0.05
CHUNK_ELEMENTS = 1 << 20
SNAPSHOT_BUDGET_BYTES = 6 * 1024 ** 3


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _inventory(inventory):
    if not isinstance(inventory, dict) or not inventory:
        raise ValueError('nonempty named inventory required')
    for name, value in inventory.items():
        if not isinstance(name, str) or not name or not isinstance(value, torch.Tensor):
            raise ValueError('inventory names and tensors are required')
        if not value.is_floating_point() or not value.is_contiguous():
            raise ValueError('contiguous floating-point inventory required')
    return sorted(inventory.items())


def inventory_sha256(inventory):
    """Hash named, shaped, typed complete bytes without a population-sized host copy."""
    digest = hashlib.sha256()
    for name, value in _inventory(inventory):
        header = _canonical([name, list(value.shape), str(value.dtype)])
        digest.update(len(header).to_bytes(8, 'little'))
        digest.update(header)
        raw = value.detach().reshape(-1).view(torch.uint8)
        digest.update(raw.numel().to_bytes(8, 'little'))
        for start in range(0, raw.numel(), CHUNK_ELEMENTS):
            digest.update(raw[start:start + CHUNK_ELEMENTS].cpu().numpy().tobytes())
    return digest.hexdigest()


def snapshot_plan(inventory, *, budget_bytes=SNAPSHOT_BUDGET_BYTES):
    if type(budget_bytes) is not int or budget_bytes <= 0:
        raise ValueError('positive integer snapshot budget required')
    parameter_bytes = sum(value.numel() * value.element_size() for _, value in _inventory(inventory)
                          if value.requires_grad)
    if not parameter_bytes:
        raise ValueError('nonempty supported population required')
    # Every supported owner may receive a gradient. None at one step is not a capacity discount.
    one = 2 * parameter_bytes
    if 2 * one <= budget_bytes:
        return dict(updates=[1, 64], maximum_snapshot_bytes=2 * one, parameter_bytes=parameter_bytes,
                    budget_bytes=budget_bytes, reason=None)
    if one <= budget_bytes:
        return dict(updates=[64], maximum_snapshot_bytes=one, parameter_bytes=parameter_bytes,
                    budget_bytes=budget_bytes, reason='Two complete parameter-and-gradient snapshots exceed the reserved CPU snapshot budget')
    raise ValueError('one complete final parameter-and-gradient snapshot exceeds the reserved CPU budget')


def take_snapshot(inventory, *, budget_bytes):
    entries = [(name, value) for name, value in _inventory(inventory) if value.requires_grad]
    needed = sum(value.numel() * value.element_size() +
                 (0 if value.grad is None else value.grad.numel() * value.grad.element_size())
                 for _, value in entries)
    if needed > budget_bytes:
        raise ValueError('snapshot would exceed the reserved CPU byte budget')
    tensors = {}
    for name, value in entries:
        tensors[name] = dict(parameter=value.detach().to(device='cpu', copy=True),
                             gradient=None if value.grad is None else value.grad.detach().to(device='cpu', copy=True))
    return dict(tensors=tensors, bytes=needed)


def _file_sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(CHUNK_ELEMENTS), b''):
            digest.update(block)
    return digest.hexdigest()


def save_snapshot(inventory, root, *, update, budget_bytes):
    """Persist every supported owner without retaining a complete host snapshot."""
    from safetensors.torch import save_file
    if update not in (1, UPDATES) or type(budget_bytes) is not int or budget_bytes <= 0:
        raise ValueError('bound snapshot update and byte budget required')
    root = Path(root)
    entries, written = {}, 0
    for index, (name, value) in enumerate(_inventory(inventory)):
        if not value.requires_grad:
            continue
        tensors = {'parameter': value.detach().cpu().contiguous()}
        if value.grad is not None:
            tensors['gradient'] = value.grad.detach().cpu().contiguous()
        size = sum(t.numel() * t.element_size() for t in tensors.values())
        # Reserve a bounded safetensors header before writing this owner.
        if written + size + 4096 > budget_bytes:
            raise ValueError('snapshot disk budget would be exceeded')
        path = root / ('t2-update-%02d-owner-%04d.safetensors' % (update, index))
        if path.exists():
            raise ValueError('snapshot custody already exists')
        save_file(tensors, str(path))
        actual = path.stat().st_size
        written += actual
        if actual > size + 4096 or written > budget_bytes:
            raise ValueError('snapshot file exceeds its declared byte bound')
        entries[name] = dict(file=path.name, sha256=_file_sha256(path), bytes=actual,
                             shape=list(value.shape), dtype=str(value.dtype), gradient_present=value.grad is not None)
        del tensors
    if not entries:
        raise ValueError('nonempty supported snapshot required')
    return dict(update=update, tensors=entries, bytes=written)


def load_snapshot(root, manifest):
    """Load exact manifested tensor bytes; never deserialize arbitrary Python objects."""
    from safetensors.torch import load_file
    root = Path(root).resolve(strict=True)
    tensors = {}
    for name, entry in manifest['tensors'].items():
        relative = Path(entry['file'])
        if relative.is_absolute() or relative.name != entry['file']:
            raise ValueError('snapshot file must be a custody-local basename')
        path = (root / relative).resolve(strict=True)
        if path.parent != root or path.stat().st_size != entry['bytes'] or _file_sha256(path) != entry['sha256']:
            raise ValueError('snapshot file hash or custody differs')
        values = load_file(str(path), device='cpu')
        expected = {'parameter', 'gradient'} if entry['gradient_present'] else {'parameter'}
        if set(values) != expected or any(list(t.shape) != entry['shape'] or str(t.dtype) != entry['dtype'] for t in values.values()):
            raise ValueError('snapshot tensor metadata differs')
        tensors[name] = dict(parameter=values['parameter'], gradient=values.get('gradient'))
    return dict(tensors=tensors, bytes=manifest['bytes'])


def _tensor_difference(reference, candidate, *, device, chunk_elements):
    if reference is None or candidate is None:
        same = reference is None and candidate is None
        return dict(relative_l2=0.0 if same else None, passed=same, gradient_presence_equal=same)
    if reference.shape != candidate.shape or reference.dtype != candidate.dtype:
        raise ValueError('comparison tensor shape or dtype differs')
    if type(chunk_elements) is not int or chunk_elements <= 0:
        raise ValueError('positive comparison chunk size required')
    reference, candidate = reference.detach().reshape(-1), candidate.detach().reshape(-1)
    sums = torch.zeros(2, dtype=torch.float64, device=device)
    finite = torch.ones((), dtype=torch.bool, device=device)
    for start in range(0, reference.numel(), chunk_elements):
        # First transfer both original dtypes to the SAME device, then widen for the N63 norm.
        left = reference[start:start + chunk_elements].to(device=device)
        right = candidate[start:start + chunk_elements].to(device=device)
        finite &= torch.isfinite(left).all() & torch.isfinite(right).all()
        left, right = left.float(), right.float()
        sums[0] += (left - right).square().sum(dtype=torch.float64)
        sums[1] += left.square().sum(dtype=torch.float64)
    difference, denominator = sums.cpu().tolist()
    if not bool(finite.cpu()) or not math.isfinite(difference + denominator):
        return dict(relative_l2=None, passed=False, finite=False)
    # Existing N63 uses the absolute difference norm when the reference norm is zero.
    relative = math.sqrt(difference / denominator) if denominator else math.sqrt(difference)
    return dict(relative_l2=relative, passed=relative <= RELATIVE_L2_MAX, finite=True)


def compare_snapshot(snapshot, inventory, *, device, chunk_elements=CHUNK_ELEMENTS):
    supported = {name: value for name, value in _inventory(inventory) if value.requires_grad}
    if set(snapshot['tensors']) != set(supported):
        raise ValueError('complete supported comparison membership differs')
    tensors = {}
    for name, value in supported.items():
        reference = snapshot['tensors'][name]
        tensors[name] = {kind: _tensor_difference(reference[kind], actual, device=device,
                                                  chunk_elements=chunk_elements)
                         for kind, actual in (('parameter', value), ('gradient', value.grad))}
    return dict(tensors=tensors, passed=all(result['passed'] for item in tensors.values() for result in item.values()),
                bound=RELATIVE_L2_MAX, grammar='n63-relative-l2-per-tensor-v1')


def _finite_values(values):
    if len(values) != UPDATES or any(type(value) not in (int, float) or not math.isfinite(value) for value in values):
        raise ValueError('exactly 64 finite trajectory values required')
    return [float(value) for value in values]


def _trajectory_difference(reference, candidate):
    errors = [abs(left - right) / abs(left) if left else abs(left - right)
              for left, right in zip(reference, candidate)]
    denominator = sum(value * value for value in reference)
    squared = sum((left - right) ** 2 for left, right in zip(reference, candidate))
    return max(errors), math.sqrt(squared / denominator) if denominator else math.sqrt(squared)


def compare_loss_trajectories(reference1, reference2, treatment):
    reference1, reference2, treatment = map(_finite_values, (reference1, reference2, treatment))
    floor_max, floor_l2 = _trajectory_difference(reference1, reference2)
    treatment_max, treatment_l2 = _trajectory_difference(reference1, treatment)
    max_bound, l2_bound = max(floor_max, RELATIVE_L2_MAX), max(floor_l2, RELATIVE_L2_MAX)
    return dict(passed=treatment_max <= max_bound and treatment_l2 <= l2_bound,
                regime='ruled-0.05' if floor_max <= RELATIVE_L2_MAX and floor_l2 <= RELATIVE_L2_MAX else 'observed-reference-floor-exceeds-0.05',
                reference_max=floor_max, reference_l2=floor_l2, treatment_max=treatment_max,
                treatment_l2=treatment_l2, max_bound=max_bound, l2_bound=l2_bound, updates=UPDATES)


def _checked_rows(rows):
    if len(rows) != UPDATES or [row.get('update') for row in rows] != list(range(1, UPDATES + 1)):
        raise ValueError('one ordered row for every update 1 through 64 required')
    for row in rows:
        census = row.get('census')
        if not isinstance(census, list) or len(census) != 12:
            raise ValueError('complete sparse-layer census required')
        if any(not isinstance(layer, list) or len(layer) != 25 or
               any(type(count) is not int or count < 0 for count in layer) or sum(layer) != 4096 for layer in census):
            raise ValueError('census must count every packed row once per sparse layer')
    _finite_values([row['loss'] for row in rows])
    return rows


def compare_rows(reference1, reference2, treatment):
    reference1, reference2, treatment = map(_checked_rows, (reference1, reference2, treatment))
    differences = [index + 1 for index, (left, repeat, right) in enumerate(zip(reference1, reference2, treatment))
                   if left['census'] != repeat['census'] or left['census'] != right['census']]
    loss = compare_loss_trajectories(*[[row['loss'] for row in rows] for rows in (reference1, reference2, treatment)])
    return dict(passed=not differences and loss['passed'], loss=loss, census_identical=not differences,
                census_difference_updates=differences,
                claim='Loss and routing-census comparison only; full tensors and other qualification gates are separate')


def compare_start_identity(reference, candidate, *, arm):
    left, right = dict(reference), dict(candidate)
    left_sources, right_sources = left.pop('source_sha256'), right.pop('source_sha256')
    if not set(left_sources) <= set(right_sources) or any(right_sources[k] != v for k, v in left_sources.items()):
        raise ValueError('starting source identities differ')
    if arm == 'Tfused':
        right['optimizer'] = dict(right['optimizer'])
        if right['optimizer'].pop('fused', None) is not True:
            raise ValueError('explicit fused optimizer treatment required')
    if left != right:
        raise ValueError('complete starting population, RNG, data or optimizer identities differ')


def compare_saved_snapshots(reference_root, reference, candidate_root, candidate):
    """Compare one pair of owners at a time with bounded host memory."""
    if reference['update'] != candidate['update'] or set(reference['tensors']) != set(candidate['tensors']):
        raise ValueError('snapshot update or complete supported membership differs')
    comparisons = {}
    for name in sorted(reference['tensors']):
        def one(root, manifest):
            return load_snapshot(root, dict(manifest, tensors={name: manifest['tensors'][name]}))['tensors'][name]
        left, right = one(reference_root, reference), one(candidate_root, candidate)
        comparisons[name] = {kind: _tensor_difference(left[kind], right[kind], device='cpu',
            chunk_elements=CHUNK_ELEMENTS) for kind in ('parameter', 'gradient')}
        del left, right
    return dict(tensors=comparisons, bound=RELATIVE_L2_MAX,
                passed=all(value['passed'] for entry in comparisons.values() for value in entry.values()))


def adjudicate_arms(roots, arm_sha256):
    """Compare independently identified completed arm artifacts; native receipts are checked by the caller."""
    if set(roots) != set(arm_sha256) or not {'R1', 'R2'} < set(roots) or not set(roots) <= {'R1', 'R2', 'Tsegmented', 'Tdynamic', 'Tfused'}:
        raise ValueError('two references and declared treatment arms required')
    arms = {}
    for name, root in roots.items():
        root = Path(root)
        path = root / ('t2-arm-' + name + '.json')
        if _file_sha256(path) != arm_sha256[name]:
            raise ValueError('arm artifact hash differs')
        arm = json.loads(path.read_bytes())
        terminal = json.loads((root / 'worker-terminal.json').read_bytes())
        if (arm['arm'] != name or arm['frozen_owners_unchanged'] is not True
                or terminal['status'] != 'completed' or terminal['applied_positions'] != UPDATES * 4096):
            raise ValueError('complete applied trajectory and unchanged frozen owners required')
        _checked_rows(arm['rows'])
        if arm['snapshot_updates'] not in ([1, 64], [64]) or set(arm['snapshots']) != set(map(str, arm['snapshot_updates'])):
            raise ValueError('complete declared snapshot updates required')
        arms[name] = arm
    reference = arms['R1']
    tensors, rows = {}, {}
    for name, arm in arms.items():
        compare_start_identity(reference['start'], arm['start'], arm=name)
        if arm['snapshot_updates'] != reference['snapshot_updates']:
            raise ValueError('snapshot plans differ')
        if name == 'R1':
            continue
        tensors[name] = {update: compare_saved_snapshots(roots['R1'], reference['snapshots'][update],
            roots[name], arm['snapshots'][update]) for update in reference['snapshots']}
        if name != 'R2':
            rows[name] = compare_rows(reference['rows'], arms['R2']['rows'], arm['rows'])
    return dict(schema='ember-cia-trajectory-comparison-v1', arm_sha256=arm_sha256,
        passed=all(item['passed'] for group in tensors.values() for item in group.values())
            and all(item['passed'] for item in rows.values()), tensors=tensors, rows=rows,
        claim='Bounded tensor, loss and routing comparison only; native receipts and all other qualification gates remain separate')


class ReferenceRouting:
    """Retain only the existing observer's decision-time fields for the fixed 4x1024 geometry."""
    def __init__(self):
        self.globals = {}
        self.locals = {}

    def __call__(self, observation):
        if hasattr(observation, 'log_prior'):
            key = (observation.document, observation.epoch_start)
            if key not in {(document, 0) for document in range(4)} or key in self.globals:
                raise ValueError('duplicate or unexpected reference global report')
            prior = observation.log_prior.detach().cpu()
            if tuple(prior.shape) != (25,) or prior.dtype != torch.float32 or not torch.isfinite(prior).all():
                raise ValueError('complete finite reference prior required')
            ranked = tuple(observation.experts)
            if len(ranked) != 2 or len(set(ranked)) != 2 or any(type(i) is not int or not 0 <= i < 25 for i in ranked):
                raise ValueError('two distinct reference expert identities required')
            self.globals[key] = dict(prior=prior.tolist(), ranked=list(ranked), candidates=sorted(ranked))
            return
        key = (observation.document, observation.layer, observation.segment_start)
        if (key[0] not in range(4) or key[1] not in range(1, 24, 2) or key[2] not in (0, 256, 512, 768)
                or key in self.locals):
            raise ValueError('duplicate or unexpected reference local report')
        candidates, logits, chosen = tuple(observation.candidates), tuple(observation.logits), observation.chosen
        if (len(candidates) != 2 or candidates != tuple(sorted(set(candidates)))
                or type(chosen) is not int or chosen not in candidates
                or len(logits) != 2 or any(not math.isfinite(value) for value in logits)):
            raise ValueError('finite reference local decision required')
        self.locals[key] = dict(candidates=candidates, winner=chosen, logits=logits)

    def finish(self):
        from ember.model.ember_v0_routing import unit_task_gate_batch
        expected = {(document, layer, start) for document in range(4)
                    for layer in range(1, 24, 2) for start in (0, 256, 512, 768)}
        if set(self.globals) != {(document, 0) for document in range(4)} or set(self.locals) != expected:
            raise ValueError('incomplete reference routing reports')
        winners, logits, gates = [], [], []
        for layer in range(1, 24, 2):
            local = [self.locals[(document, layer, start)] for document in range(4) for start in (0, 256, 512, 768)]
            if any(list(row['candidates']) != self.globals[(index // 4, 0)]['candidates']
                   for index, row in enumerate(local)):
                raise ValueError('reference local candidates differ from the global declaration')
            layer_logits = torch.tensor([row['logits'] for row in local], dtype=torch.float32)
            slots = torch.tensor([row['candidates'].index(row['winner']) for row in local], dtype=torch.long)
            # Derive observation-only gates through the existing native gate function, without replacing model gates.
            layer_gates = unit_task_gate_batch(layer_logits, slots)
            winners.append([row['winner'] for row in local])
            logits.append(layer_logits.tolist())
            gates.append(layer_gates.tolist())
        return dict(priors=[self.globals[(document, 0)]['prior'] for document in range(4)],
                    ranked=[self.globals[(document, 0)]['ranked'] for document in range(4)],
                    candidates=[self.globals[(document, 0)]['candidates'] for document in range(4)],
                    winners=winners, logits=logits, gates=gates, valid=[True] * 12,
                    gate_observation='native gate re-evaluated from decision-time reference logits and slots')


def device_routing(buffers, snapshot):
    if buffers.lengths != (1024, 1024, 1024, 1024) or len(snapshot) != buffers.nbytes:
        raise ValueError('trajectory requires complete 4x1024 device routing state')
    buffers.complete(snapshot)
    decoded = buffers._decode(snapshot)
    return {name: decoded[name].tolist() for name in ('priors', 'ranked', 'candidates', 'winners', 'logits', 'gates', 'valid')}


def routing_metrics(data, *, previous=None):
    winners = data['winners']
    logits = torch.tensor(data['logits'], dtype=torch.float64)
    gates = torch.tensor(data['gates'], dtype=torch.float64)
    candidates = data['candidates']
    if (len(winners) != 12 or any(len(row) != 16 for row in winners)
            or tuple(logits.shape) != (12, 16, 2) or tuple(gates.shape) != (12, 16)
            or len(candidates) != 4 or any(len(pair) != 2 for pair in candidates)
            or data['valid'] != [True] * 12 or not torch.isfinite(logits).all() or not torch.isfinite(gates).all()
            or bool(((gates < 0) | (gates > 1)).any())):
        raise ValueError('complete finite routing metrics required')
    census, switch, load = [], [], []
    for layer, row in enumerate(winners):
        counts = [0] * 25
        for index, expert in enumerate(row):
            if type(expert) is not int or not 0 <= expert < 25 or expert not in candidates[index // 4]:
                raise ValueError('winner differs from the declared candidate pair')
            counts[expert] += 256
        census.append(counts)
        load.append(25 * sum((count / 4096) ** 2 for count in counts) - 1)
        if previous is None:
            switch.append(0.0)
        else:
            old = previous['winners'][layer]
            if len(old) != len(row):
                raise ValueError('previous routing geometry differs')
            switch.append(sum(left != right for left, right in zip(old, row)) / len(row))
    def entropy(probabilities):
        return -torch.where(probabilities > 0, probabilities * probabilities.clamp_min(1e-300).log(),
                            torch.zeros_like(probabilities))
    gate_entropy = (entropy(gates) + entropy(1 - gates)).mean(dim=1).tolist()
    probability_entropy = entropy(logits.softmax(-1)).sum(-1).mean(-1).tolist()
    return dict(census=census, gate_entropy=gate_entropy, local_probability_entropy=probability_entropy,
                load_balance_cv_squared=load, switch_rate=switch,
                health_claim='Reported observations only; no invented health-metric acceptance bound')


def execute_steps(packs, *, step, record, applied, observe):
    """Bind each consumed pack and count a completed, persisted update before optional observations."""
    if len(packs) != UPDATES or [pack['index'] for pack in packs] != list(range(UPDATES)):
        raise ValueError('complete ordered 64-update input plan required')
    def digest(pack):
        return hashlib.sha256(_canonical({name: pack[name] for name in
            ('token_ids', 'target_ids', 'positions', 'document_starts', 'index', 'phase')})).hexdigest()
    bound = [digest(pack) for pack in packs]
    for index, pack in enumerate(packs):
        if digest(pack) != bound[index]:
            raise ValueError('bound trajectory input changed before its update')
        row = step(index, pack)
        if row['index'] != index or row['applied_positions'] != len(pack['token_ids']):
            raise ValueError('completed update count differs from the consumed input')
        record(row)
        applied(row['applied_positions'])
        observe(index, row)


def _stream_row(stream, row):
    stream.write(_canonical(row) + b'\n')
    stream.flush()
    os.fsync(stream.fileno())


def _update_delta(before, inventory, *, device):
    supported = {name: value for name, value in inventory.items() if value.requires_grad}
    if set(before) != set(supported):
        raise ValueError('update-norm support changed')
    sums = torch.zeros(2, dtype=torch.float64, device=device)
    finite = torch.ones((), dtype=torch.bool, device=device)
    for name, original in before.items():
        current = supported[name].detach()
        if original.dtype != current.dtype or original.shape != current.shape:
            raise ValueError('update-norm owner shape or dtype changed')
        left, right = original.reshape(-1), current.reshape(-1)
        for start in range(0, left.numel(), CHUNK_ELEMENTS):
            a = left[start:start + CHUNK_ELEMENTS].to(device=device).float()
            b = right[start:start + CHUNK_ELEMENTS].to(device=device).float()
            finite &= torch.isfinite(a).all() & torch.isfinite(b).all()
            sums[0] += (a - b).square().sum(dtype=torch.float64)
            sums[1] += a.square().sum(dtype=torch.float64)
    difference, denominator = sums.cpu().tolist()
    if not bool(finite.cpu()) or not math.isfinite(difference + denominator):
        raise ValueError('nonfinite update-norm observation')
    return math.sqrt(difference / denominator) if denominator else math.sqrt(difference)


def _rng_identity(device):
    cpu = hashlib.sha256(torch.get_rng_state().numpy().tobytes()).hexdigest()
    cuda = [hashlib.sha256(state.cpu().numpy().tobytes()).hexdigest() for state in torch.cuda.get_rng_state_all()] if device.type == 'cuda' else []
    return dict(cpu_sha256=cpu, cuda_sha256=cuda)


def _run_arm(*, runner, config, prepared, prediction, binding, custody, device, compiler,
             name, mode, row_stream, metric_stream, applied):
    from ember.model.ember_v0_decoder import CIADecoder
    identity = prediction['identity']
    runner.verify_prepared_inputs(prepared)
    model = CIADecoder(architecture_config=config).materialize_cpu(seed=identity['seed'])
    definition = identity['optimizer']
    def optimizer_factory(inventory):
        if sum(value.numel() for value in inventory.values()) != runner.POPULATION:
            raise ValueError('trajectory requires the complete CIA population')
        return torch.optim.AdamW(list(inventory.values()), lr=definition['lr'], betas=tuple(definition['betas']),
                                 eps=definition['eps'], weight_decay=definition['weight_decay'], foreach=False,
                                 **({'fused': True} if definition.get('fused') is True else {}))
    first = prepared['packs'][0]
    lengths = runner.document_lengths(tuple(first['document_starts']), len(first['token_ids']))
    inventory, optimizer = runner.prepare_model(model, identity, lengths, device, mode=mode,
                                                 optimizer_factory=optimizer_factory)
    membership = [parameter for group in optimizer.param_groups for parameter in group['params']]
    if len(membership) != len(inventory) or {id(p) for p in membership} != {id(p) for p in inventory.values()}:
        raise ValueError('trajectory optimizer membership differs from the complete population')
    population_sha = inventory_sha256(inventory)
    plan = snapshot_plan(inventory)
    if plan['parameter_bytes'] > 2 * 1024 ** 3:
        raise ValueError('update-norm copy would exceed its reserved two GiB')
    frozen = {key: value for key, value in inventory.items() if not value.requires_grad}
    frozen_sha = inventory_sha256(frozen) if frozen else hashlib.sha256(b'[]').hexdigest()
    # Reset after materialization and placement, immediately before the first update; a mismatch never triggers reseeding.
    torch.manual_seed(identity['seed'])
    start = dict(population_sha256=population_sha, population=runner.POPULATION, seed=identity['seed'],
                 rng=_rng_identity(device), cursor=identity['data']['cursor'], support=identity['support'],
                 geometry=identity['geometry'], input_binding=prepared['binding'],
                 shard_ledger_sha256=identity['data']['shard_ledger_sha256'], source_commit=identity['source_commit'],
                 source_sha256=identity['source_sha256'], optimizer=definition, snapshot_plan=plan)
    start['comparison_id'] = identity['trajectory']['comparison_id']
    start['frozen_population_sha256'] = frozen_sha
    runner._write_new(custody / ('t2-start-' + name + '.json'), dict(start, arm=name, execution_mode=mode))
    runner._write_new(custody / 'model.json', dict(population=runner.POPULATION, parameter_count=len(inventory),
        execution_mode=mode, trajectory=identity['trajectory'], c_compiler=compiler,
        resident_experts=list(identity['support']['experts']), input_binding=prepared['binding'],
        snapshot_plan=plan, claim=runner.CLAIM))
    expert_owners = runner.expert_owner_index(inventory)
    capture = None
    if mode is not None:
        buffers = runner.routing_buffers(lengths, device)
        dynamic = {'capture_experts': True} if mode == 'resident-dynamic-capture' else {}
        capture = model.bind_segmented_capture(collector=buffers.collector,
            loss_fn=lambda logits, targets: torch.nn.functional.cross_entropy(logits.float(), targets, reduction='mean'),
            static_state=(buffers.raw,), warmup_steps=2, **dynamic)
    arm_rows, snapshots, held = [], {}, {}
    previous = None
    def step(index, pack):
        held['before'] = {key: value.detach().clone() for key, value in inventory.items() if value.requires_grad}
        held['observer'] = ReferenceRouting() if mode is None else None
        held['routing'] = {} if mode is not None else None
        return runner.measure_step(model, optimizer, pack, device=device, batch_documents=True,
            run_id=identity['run_id'], expert_owners=expert_owners, capture=capture,
            record=capture is not None and index == 0, route_observer=held['observer'], route_snapshot=held['routing'])
    def record(row):
        row.update(arm=name, run_id=identity['run_id'], prediction_sha256=binding['launch']['prediction_sha256'],
                   input_sha256=prepared['binding']['input_sha256'])
        _stream_row(row_stream, row)
    def observe(index, row):
        nonlocal previous
        update = index + 1
        data = held['observer'].finish() if mode is None else device_routing(**held['routing'])
        metrics = routing_metrics(data, previous=previous)
        metrics.update(update=update, arm=name, loss=row['loss'], wall_seconds=row['wall_seconds'],
                       update_delta_relative_l2=_update_delta(held['before'], inventory, device=device),
                       routing_sha256=hashlib.sha256(_canonical(data)).hexdigest())
        held['before'].clear()
        held.clear()
        previous = data
        _stream_row(metric_stream, metrics)
        arm_rows.append(metrics)
        if update in plan['updates']:
            remaining = SNAPSHOT_BUDGET_BYTES - sum(item['bytes'] for item in snapshots.values())
            snapshots[str(update)] = save_snapshot(inventory, custody, update=update, budget_bytes=remaining)
            runner._write_new(custody / ('t2-snapshot-%02d.json' % update), snapshots[str(update)])
        if capture is not None and index == 0:
            optimizer.zero_grad(set_to_none=False)
            capture.zero_grad()
            buffers.capturing = True
            try:
                capture.capture(optimizer=optimizer)
            finally:
                buffers.capturing = False
            runner._write_new(custody / 'capture.json', dict(capture.receipt(), arm=name, claim=runner.CLAIM))
    execute_steps(prepared['packs'], step=step, record=record, applied=applied, observe=observe)
    runner.verify_prepared_inputs(prepared)
    if frozen and inventory_sha256(frozen) != frozen_sha:
        raise ValueError('a frozen owner changed during the trajectory')
    result = dict(arm=name, execution_mode=mode, start=start, rows=arm_rows, snapshots=snapshots,
                  frozen_owners_unchanged=True, snapshot_updates=plan['updates'])
    runner._write_new(custody / ('t2-arm-' + name + '.json'), result)
    return result


def run_trajectory_arm(*, runner, config, prepared, prediction, binding, custody, device, compiler, applied):
    """Run exactly one arm inside its authenticated worker and unchanged native job."""
    identity = prediction['identity']
    if not runner.trajectory_mode(identity) or runner.geometry_counts(identity['geometry'], trajectory=True) != (1024, 4, 1, 63):
        raise ValueError('explicit bound 64-update trajectory identity required')
    if device.type == 'cuda':
        from ember.governance.scripts import cia_conformance_resources as resources
        resources.require_owned_job(identity['run_id'], namespace=runner.JOB_NAMESPACE,
                                    host_memory_bytes=runner.LIMITS['host_memory_bytes'])
    with (custody / 'rows.jsonl').open('xb') as row_stream, (custody / 't2-rows.jsonl').open('xb') as metric_stream:
        return _run_arm(runner=runner, config=config, prepared=prepared, prediction=prediction,
            binding=binding, custody=custody, device=device, compiler=compiler,
            name=identity['trajectory']['arm'], mode=runner.execution_mode(identity),
            row_stream=row_stream, metric_stream=metric_stream, applied=applied)
