"""Explicit governed-hour input and accounting support for the existing CIA worker."""
# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import math
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time


def bound_json(runner, path, digest):
    path = Path(path).resolve(strict=True)
    if runner.file_sha256(path) != runner.checked_sha(digest) or path.stat().st_size > runner.GIB:
        raise ValueError('hour artifact bytes differ or exceed the metadata bound')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError('hour artifact changed during read')
    return json.loads(raw)


def read_staging(runner, mixture):
    """A present artifact always verifies; absence is an explicit identity variant."""
    if mixture['staging_manifest_path'] is not None:
        manifest = bound_json(runner, mixture['staging_manifest_path'], mixture['staging_manifest_sha256'])
        if mixture.get('staging_manifest_bytes_absent', False) is not False:
            raise ValueError('present staging manifest conflicts with explicit absence')
        return manifest
    if mixture.get('staging_manifest_bytes_absent') is not True:
        raise ValueError('staging absence requires the explicit export-derived variant')
    return None


def map_ledger_spans(ledger, membership, protected, *, staged=None):
    owners = {}
    for dataset, hashes in membership.items():
        for digest in hashes:
            owners.setdefault(digest, set()).add(dataset)
    covered, total, tokens, multiple = set(), 0, 0, 0
    per_dataset = {}
    for row in ledger:
        for span in row['spans']:
            digest = span['sha256']
            total += 1
            if digest not in owners or (staged is not None and digest not in staged):
                raise ValueError('production span sha lacks admitted train membership')
            if digest in protected:
                raise ValueError('production span overlaps protected evaluation objects')
            start, end = span['token_start'], span['token_end']
            if type(start) is not int or type(end) is not int or not 0 <= start < end:
                raise ValueError('production span token arithmetic is invalid')
            tokens += end - start
            multiple += len(owners[digest]) > 1
            for dataset in owners[digest]:
                counts = per_dataset.setdefault(dataset, dict(spans=0, tokens=0))
                counts['spans'] += 1
                counts['tokens'] += end - start
            covered.update(owners[digest])
    if not total:
        raise ValueError('production ledger has no attributable spans')
    return dict(spans_total=total, spans_mapped=total, unmapped_spans=0, span_tokens=tokens,
                per_dataset=per_dataset, multiple_dataset_spans=multiple,
                dataset_attribution='all matching admitted memberships; shared memberships are counted in each dataset',
                dataset_ids=sorted(covered), protected_objects_checked=len(protected), overlaps=0)


def validate_coverage(mixture, proof):
    coverage = mixture['dataset_coverage']
    keys = {'declared_dataset_ids', 'covered_dataset_ids', 'uncovered_dataset_ids',
            'spans_total', 'spans_mapped', 'basis', 'claim'}
    if type(coverage) is not dict or set(coverage) != keys:
        raise ValueError('explicit frozen dataset coverage required')
    declared, covered, uncovered = (coverage[key] for key in
        ('declared_dataset_ids', 'covered_dataset_ids', 'uncovered_dataset_ids'))
    if (any(type(values) is not list or values != sorted(set(values)) for values in (declared, covered, uncovered))
            or declared != mixture['dataset_ids'] or set(covered) & set(uncovered)
            or sorted(set(covered) | set(uncovered)) != declared
            or covered != proof['dataset_ids']
            or any(type(coverage[key]) is not int or coverage[key] != proof[key] for key in ('spans_total','spans_mapped'))):
        raise ValueError('actual dataset coverage differs from the frozen identity')
    proof['declared_dataset_ids'], proof['uncovered_dataset_ids'] = declared, uncovered


def validate_probe_inputs(runner, prior, identity):
    for name in ('source_commit','source_sha256','config_sha256','data','seed','support','production_mixture'):
        if prior.get(name) != identity[name]:
            raise ValueError('checkpoint probe differs from the hour source or inputs: ' + name)
    if runner.attention_selection(prior) != runner.attention_selection(identity):
        raise ValueError('checkpoint probe attention selection differs from the hour')
    if runner.execution_mode(prior) != runner.execution_mode(identity):
        raise ValueError('checkpoint probe execution mode differs from the hour')


def validate_checkpoint_probe(runner, identity):
    """Require a completed same-source probe and reopen its real admitted child."""
    selection = identity['hour']
    if selection['schema'] == 'checkpoint-probe-v1':
        if 'checkpoint_probe' in identity:
            raise ValueError('checkpoint probe cannot consume another probe identity')
        return
    reference = identity.get('checkpoint_probe')
    required = {'custody_root', 'result_sha256', 'prediction_sha256', 'owned_sha256',
                'disk_sha256', 'worker_terminal_sha256'}
    if type(reference) is not dict or set(reference) != required:
        raise ValueError('governed hour requires its completed bound checkpoint probe')
    root = Path(reference['custody_root']).resolve(strict=True)
    if root.drive.upper() != 'B:' or not root.name.startswith('measurement-'):
        raise ValueError('checkpoint probe custody must be a governed B-drive worker')
    result = bound_json(runner, root/'hour-result.json', reference['result_sha256'])
    prediction = bound_json(runner, root/'prediction.json', reference['prediction_sha256'])
    owned = bound_json(runner, root/'owned.json', reference['owned_sha256'])
    disk = bound_json(runner, root/'disk.json', reference['disk_sha256'])
    terminal = bound_json(runner, root/'worker-terminal.json', reference['worker_terminal_sha256'])
    prior = prediction['identity']
    if (prior.get('hour') != dict(schema='checkpoint-probe-v1', arm=selection['arm'], minimum_wall_seconds=0,
                                 minimum_measured_steps=2)
            or result.get('hour') != prior['hour'] or result.get('measured_updates') != 2
            or result.get('applied_positions') != 3*4096 or result.get('restored_state_matches') is not True
            or terminal.get('status') != 'completed' or terminal.get('applied_positions') != 3*4096
            or owned.get('status') != 'completed' or owned.get('returncode') != 0
            or owned.get('cleanup_verified') is not True or owned.get('supervisor_failure') is not None
            or disk.get('outcome') != 'COMPLETED' or disk.get('runner_exit_code') != 0
            or disk.get('child_exit_code') != 0 or disk.get('stop_reason') is not None
            or disk.get('operating_reserve_breaches') != []):
        raise ValueError('checkpoint probe execution or cleanup is incomplete')
    validate_probe_inputs(runner, prior, identity)
    if (result.get('source_commit') != identity['source_commit']
            or runner.file_sha256(root/'rows.jsonl') != result['rows_sha256']):
        raise ValueError('checkpoint probe result source or rows differ')
    child = root/'trained-child'
    receipt = bound_json(runner, child/'checkpoint-manifest.json', result['child_manifest_sha256'])
    receipt['checkpoint_manifest_sha256'] = result['child_manifest_sha256']
    import parameter_counter as counter
    measured = counter._cia_realization_receipt(child, receipt, model_config_sha256=identity['config_sha256'])
    if measured != json.loads((child/'parameter-counter-receipt.json').read_bytes()):
        raise ValueError('probe checkpoint admission differs from reopened complete bytes')


def validate_hour_execution(runner, identity):
    mode = runner.execution_mode(identity)
    if mode is not None and (identity['hour']['arm'] != 'treatment' or mode != 'resident-dynamic-capture'):
        raise ValueError('captured hour requires the declared dynamic treatment')


def validate_identity(*, runner, identity):
    from ember.governance.scripts import catalog_train_stream as catalog
    validate_hour_execution(runner, identity)
    hour, geometry = identity['hour'], identity['geometry']
    if geometry['measured_steps'] < hour['minimum_measured_steps']:
        raise ValueError('declared step capacity cannot satisfy hour minimum')
    if hour['schema'] == 'checkpoint-probe-v1' and geometry['measured_steps'] != 2:
        raise ValueError('checkpoint probe requires exactly two measured updates')
    walls = identity['dispatch_resources'].get('disk_write_walls')
    if (not isinstance(walls, list) or len(walls) != 1 or walls[0].get('volume_root') != 'B:/'
            or walls[0].get('maximum_write_bytes') != runner.resource_limits(identity)['max_b_write_gib'] * runner.GIB):
        raise ValueError('hour native disk wall differs from worker envelope')
    mixture, data = identity['production_mixture'], identity['data']
    required = {'admission_receipt_path', 'admission_receipt_sha256', 'catalog_binding',
                'catalog_export_path', 'catalog_export_sha256', 'dataset_ids', 'spans_path', 'spans_sha256',
                'staging_manifest_path', 'staging_manifest_self_sha256', 'staging_manifest_sha256', 'dataset_coverage'}
    variant_fields = {'staging_manifest_bytes_absent', 'intermediate_staging_bytes_verified',
                      'membership_source', 'staging_manifest_sha_recorded_not_verified'}
    if type(mixture) is not dict or set(mixture) not in (required, required | variant_fields):
        raise ValueError('complete frozen production-mixture identity required')
    receipt = bound_json(runner, data['receipt_path'], data['receipt_sha256'])
    manifest = read_staging(runner, mixture)
    export = bound_json(runner, mixture['catalog_export_path'], mixture['catalog_export_sha256'])
    # The historical consumption artifact is bound for provenance; admitted train
    # membership is verified from the catalog and staging bytes below.
    bound_json(runner, mixture['admission_receipt_path'], mixture['admission_receipt_sha256'])
    bound_json(runner, mixture['spans_path'], mixture['spans_sha256'])
    catalog.verify_self_hash(receipt, 'STREAM_RECEIPT')
    binding = receipt.get('catalog_binding')
    if (binding != mixture['catalog_binding'] or not isinstance(binding, dict)
            or binding.get('catalog_export_sha256') != mixture['catalog_export_sha256']
            or binding.get('dataset_ids') != mixture['dataset_ids']
            or binding.get('staging_manifest_raw_sha256') != mixture['staging_manifest_sha256']
            or binding.get('staging_manifest_self_sha256') != mixture['staging_manifest_self_sha256']):
        raise ValueError('production staging, tokenizer, catalog and stream identities differ')
    recorded = dict(raw_sha256=binding['staging_manifest_raw_sha256'], self_sha256=binding['staging_manifest_self_sha256'])
    if manifest is None:
        if (mixture.get('intermediate_staging_bytes_verified') is not False
                or mixture.get('membership_source') != 'catalog-export-admitted-train'
                or mixture.get('staging_manifest_sha_recorded_not_verified') != recorded):
            raise ValueError('absent staging provenance must remain explicitly unverified')
    else:
        catalog.verify_self_hash(manifest, 'STAGING_MANIFEST')
        if (manifest.get('schema_version') != catalog.STAGING_SCHEMA or manifest.get('result') != 'PASS'
                or manifest.get('self_sha256') != mixture['staging_manifest_self_sha256']
                or manifest.get('catalog_export_sha256') != mixture['catalog_export_sha256']
                or manifest.get('tokenizer_sha256') != data['tokenizer_sha256']
                or manifest.get('dataset_ids') != mixture['dataset_ids']):
            raise ValueError('staging artifact does not match its source bindings')
    admitted, _ = catalog._admitted_train_windows(export, mixture['dataset_ids'], data['tokenizer_sha256'])
    membership = {name: {digest for digest, _ in rows} for name, rows in admitted.items()}
    excluded = set().union(*(hashes for name, hashes in catalog.leakage_sets(export).items() if not name.startswith('_')))
    staged = set() if manifest is not None else None
    for row in manifest['rows'] if manifest is not None else []:
        digest = row['sha256']
        if digest in staged or digest in excluded or digest not in membership.get(row['dataset_id'], set()):
            raise ValueError('staged source is not unique admitted training membership')
        staged.add(digest)
    if runner.file_sha256(data['shard_ledger_path']) != data['shard_ledger_sha256']:
        raise ValueError('production shard ledger identity differs')
    ledger = catalog.read_shard_ledger(Path(data['shard_ledger_path']))
    catalog.verify_ledger_genesis(ledger, receipt)
    proof = map_ledger_spans(ledger, membership, excluded, staged=staged)
    validate_coverage(mixture, proof)
    catalog.verify_ledger_shards(Path(data['shards_root']), ledger)
    if runner.file_sha256(data['shard_ledger_path']) != data['shard_ledger_sha256']:
        raise ValueError('production shard ledger changed during admission')
    proof.update(intermediate_staging_bytes_verified=manifest is not None,
        membership_source='catalog-export-admitted-train',
        staging_manifest_sha_recorded_not_verified=recorded if manifest is None else None,
        claim=('frozen admitted production mixture (' + str(len(proof['dataset_ids'])) + ' of '
               + str(len(mixture['dataset_ids'])) + ' admitted datasets present in the frozen ledger; '
               + ('staging intermediate unrecoverable, membership proven from export + shard bytes)'
                  if manifest is None else 'membership proven from export, staging manifest and shard bytes)')))
    return proof


class HourPacks:
    """Generate only the next complete pack from an already verified immutable shard list."""
    def __init__(self, stream, cursor, *, maximum_steps, sequence=1024, documents=4):
        self.stream = stream
        self.cursor = dict(cursor)
        self.maximum_steps = maximum_steps
        self.sequence, self.documents = sequence, documents
        self.index = 0

    def next_pack(self):
        if self.index >= self.maximum_steps:
            raise ValueError('declared hour input capacity exhausted')
        before = dict(self.cursor)
        pack = dict(token_ids=[], target_ids=[], positions=[], document_starts=[],
                    index=self.index, phase='warm' if self.index == 0 else 'measured')
        for _ in range(self.documents):
            episode, after = self.stream.next_episode(**self.cursor, sequence_length=self.sequence)
            pack['document_starts'].append(len(pack['token_ids']))
            pack['token_ids'].extend(episode['token_ids'])
            pack['target_ids'].extend(episode['target_ids'])
            pack['positions'].extend([[position, 0, 0] for position in range(self.sequence)])
            self.cursor = {key: after[key] for key in ('shard_index', 'token_offset')}
        if len(pack['token_ids']) != self.sequence * self.documents or len(pack['target_ids']) != len(pack['token_ids']):
            raise ValueError('hour pack lost complete decoder targets')
        pack['cursor_before'], pack['cursor_after'] = before, dict(self.cursor)
        self.index += 1
        return pack


def prepare_inputs(runner, data, geometry):
    if data.get('shard_ledger_path') is None or data.get('shard_ledger_sha256') is None:
        raise ValueError('governed hour requires its frozen admitted shard ledger')
    sequence, documents, warm, maximum = runner.geometry_counts(geometry, hour=True)
    stream, receipt, tokenizer, ledger = runner.open_input_stream(data)
    cursor = dict(data['cursor'])
    if set(cursor) != {'shard_index', 'token_offset'}:
        raise ValueError('hour cursor fields differ')
    # Reserve the independently checked next update without adding throughput credit.
    reference_positions = sequence * documents
    positions = (warm + maximum) * sequence * documents + reference_positions
    span = stream.check_cursor_span(**cursor, tokens=positions)
    identity = dict(receipt_sha256=data['receipt_sha256'], tokenizer_sha256=data['tokenizer_sha256'],
                    shard_ledger_sha256=data['shard_ledger_sha256'], cursor_start=cursor,
                    geometry=geometry, span=span, maximum_planned_positions=positions,
                    reference_positions_reserved=reference_positions)
    binding = dict(identity, input_sha256=hashlib.sha256(runner.canonical(identity)).hexdigest(),
                   input_digest_grammar='receipt-ledger-cursor-span-v1', shard_ledger_path=str(ledger))
    packs = HourPacks(stream, cursor, maximum_steps=warm + maximum + 1, sequence=sequence, documents=documents)
    first = packs.next_pack()
    for path, expected in ((receipt, data['receipt_sha256']), (tokenizer, data['tokenizer_sha256']),
                           (ledger, data['shard_ledger_sha256'])):
        if runner.file_sha256(path) != expected:
            raise ValueError('hour inputs changed during preparation')
    return dict(binding=binding, geometry=dict(geometry), first=first, packs=packs)


def hour_complete(*, measured_updates, elapsed_seconds):
    if (type(measured_updates) is not int or measured_updates < 0
            or type(elapsed_seconds) not in (int, float) or not math.isfinite(elapsed_seconds) or elapsed_seconds < 0):
        raise ValueError('finite observed duration and nonnegative measured update count required')
    return measured_updates >= 1024 and elapsed_seconds >= 3600


def require_remaining_hour_capacity(measured_updates, maximum):
    if measured_updates >= maximum:
        raise ValueError('declared measured hour capacity exhausted before completion')


def checkpoint_publisher(runner, model, optimizer, inventory, identity, binding, custody, device):
    import torch
    import checkpoint_artifacts as artifacts
    helper = Path.home() / '.codex/headless-python.ps1'
    if runner.file_sha256(helper) != binding['launch']['helpers'][str(helper.resolve())]:
        raise ValueError('checkpoint counter launcher differs from dispatch')
    cap = 10 * runner.GIB
    def verifier(candidate, receipt):
        command = ['powershell.exe', '-NoLogo', '-NoProfile', '-NonInteractive', '-File', str(helper), '--', '-I',
            str(runner.ROOT / 'src/ember/infrastructure/tools/ember-restart-3b/parameter_counter.py'),
            '--model-config', runner.ROOT / runner.CONFIG,
            '--checkpoint-manifest', candidate / 'checkpoint-manifest.json', '--active-expert', 'all']
        result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True,
            timeout=240, **runner.hidden_kwargs())
        if result.returncode:
            raise ValueError('independent checkpoint counter refused: ' + result.stderr.decode('utf-8', errors='replace')[-2048:])
        measured = json.loads(result.stdout)
        runner._write_new(candidate / 'parameter-counter-receipt.json', measured)
        return measured
    owner_update_counts = {}
    def publish(name, *, steps, tokens, cursor, parent=None):
        torch.cuda.synchronize(device)
        optimizer.zero_grad(set_to_none=True)
        return artifacts.write_checkpoint_artifacts(model, optimizer, custody / name,
            launch_seed=identity['seed'], rng_state={'cpu': torch.get_rng_state(), 'cuda': torch.cuda.get_rng_state(device)},
            data_cursor=dict(shard=str(cursor['shard_index']), record_index=cursor['token_offset'],
                             global_step=steps, tokens_seen=tokens),
            model_config_sha256=identity['config_sha256'],
            contract_sha256=identity['source_sha256']['src/ember/model/ember_v0_contract.py'],
            expert_genesis_sha256={}, max_serialized_bytes=cap, max_transient_scratch_bytes=cap,
            host_commit_reserve_bytes=16 * runner.GIB, pre_publish_verifier=verifier,
            cia_parent_checkpoint=parent, cia_owner_update_counts=dict(owner_update_counts) if parent else None)
    return publish, owner_update_counts


def verify_checkpoint_restore(runner, model, optimizer, inventory, identity, custody, child, *, before=None):
    import checkpoint_artifacts as artifacts
    import parameter_counter as counter
    cap = 10 * runner.GIB
    expected = {}
    counter._cia_realization_receipt(custody / 'trained-child', child,
        model_config_sha256=identity['config_sha256'], _facts=expected)
    if before is not None and (before['facts'] != expected
            or before['data_cursor'] != child['data_cursor']
            or before['rng_state_sha256'] != child['rng_state_sha256']):
        raise ValueError('terminal live state differs from independently reopened checkpoint bytes')
    restored = artifacts.load_checkpoint_artifacts(model, optimizer, custody / 'trained-child', child,
        max_transient_scratch_bytes=cap, host_commit_reserve_bytes=16 * runner.GIB)
    if restored['data_cursor'] != child['data_cursor']:
        raise ValueError('checkpoint restore cursor differs')
    # Reopen full model and native moments, including inactive owners, through
    # the existing lineage fact consumer after the codec restore transaction.
    native = artifacts.capture_cia_placed_optimizer_state(model, optimizer, max_state_bytes=cap)
    facts = artifacts._cia_lineage_facts(inventory, native['state'])
    if facts != expected:
        raise ValueError('restored model or optimizer differs from independently reopened checkpoint bytes')


def continuation_state(runner, model, optimizer, cursor, device):
    """Collect complete native state facts at an owned update boundary."""
    import torch
    import checkpoint_artifacts as artifacts
    if device.type == 'cuda':
        torch.cuda.synchronize(device)
    native = artifacts.capture_cia_placed_optimizer_state(
        model, optimizer, max_state_bytes=10 * runner.GIB)
    facts = artifacts._cia_lineage_facts(model.parameter_inventory(), native['state'])
    del native
    states = {'cpu': torch.get_rng_state(),
              'cuda': torch.cuda.get_rng_state(device) if device.type == 'cuda'
              else torch.empty(0, dtype=torch.uint8)}
    rng = {name: hashlib.sha256(value.cpu().numpy().tobytes()).hexdigest()
           for name, value in states.items()}
    return dict(facts=facts, rng_state_sha256=rng, data_cursor=dict(cursor))


def bind_hour_capture(runner, model, identity, lengths, device):
    """Use the same fresh exemplar binding for hour startup and next-update reproduction."""
    mode = runner.execution_mode(identity)
    if mode not in runner.MODE_SOURCES:
        return None, None
    import torch
    buffers = runner.routing_buffers(lengths, device)
    capture = model.bind_segmented_capture(collector=buffers.collector,
        local_routing_mode=runner.local_routing_mode(identity),
        loss_fn=lambda logits, targets: torch.nn.functional.cross_entropy(logits.float(), targets, reduction='mean'),
        static_state=(buffers.raw,), warmup_steps=2,
        **({'capture_experts': True} if mode == 'resident-dynamic-capture' else {}))
    return capture, buffers


def verify_continuation_accounting(runner, custody, hour, identity, physical_positions):
    """Reconcile physical work against a separately bound auxiliary reference."""
    if type(physical_positions) is not int or type(hour['applied_positions']) is not int:
        raise ValueError('continuation position counts must be integers')
    count = identity['geometry']['sequence_length'] * identity['geometry']['documents_per_step']
    descriptor = hour.get('continuation')
    if descriptor is None:
        if physical_positions != hour['applied_positions']:
            raise ValueError('legacy hour physical positions differ')
        return 0
    reference = bound_json(runner, custody/'continuation-reference.json', descriptor['reference_sha256'])
    terminal = bound_json(runner, custody/'continuation-hour.json', descriptor['hour_binding_sha256'])
    pack = bound_json(runner, custody/'continuation-next-pack.json', descriptor['next_pack_sha256'])
    for key in ('hour_binding_sha256', 'next_pack_sha256'):
        if reference[key] != descriptor[key]:
            raise ValueError('continuation reference binding differs')
    geometry = dict(microbatch=identity['geometry']['documents_per_step'],
                    sequence=identity['geometry']['sequence_length'], positions_per_update=count)
    checkpoint = terminal['terminal_checkpoint']
    if (reference['geometry'] != geometry or terminal['geometry'] != geometry
            or reference['run_id'] != identity['run_id']
            or reference['source_identity'] != identity['source_sha256']
            or terminal['source_identity'] != identity['source_sha256']
            or reference['device'] != identity['gpu_uuid'] or terminal['device'] != identity['gpu_uuid']
            or checkpoint != reference['restored_from']
            or checkpoint['run_id'] != identity['run_id']
            or checkpoint['manifest_sha256'] != hour['child_manifest_sha256']
            or checkpoint['tokens_seen'] != hour['applied_positions']
            or checkpoint['global_step'] != identity['geometry']['warm_steps'] + hour['measured_updates']
            or checkpoint['stream_receipt_sha256'] != identity['data']['receipt_sha256']):
        raise ValueError('continuation terminal identity differs')
    for key, value in runner.attention_selection(identity).items():
        default = 'unforced' if key == 'attention_backend' else 'none'
        if reference['execution_path'].get(key, default) != value or terminal.get(key, default) != value:
            raise ValueError('continuation attention selection differs: ' + key)
    before, after = reference['before'], reference['after']
    if (before['facts'] != terminal['terminal_facts']
            or before['rng_state_sha256'] != terminal['terminal_rng_state_sha256']
            or before['data_cursor'] != terminal['terminal_data_cursor']
            or before['data_cursor']['global_step'] != checkpoint['global_step']
            or before['data_cursor']['tokens_seen'] != checkpoint['tokens_seen']
            or after['data_cursor']['global_step'] != checkpoint['global_step'] + 1
            or after['data_cursor']['tokens_seen'] != checkpoint['tokens_seen'] + count
            or len(pack['token_ids']) != count or len(pack['target_ids']) != count
            or reference['executed_input_sha256'] != hashlib.sha256(
                runner.canonical({key: pack[key] for key in runner.INPUT_FIELDS})).hexdigest()):
        raise ValueError('continuation update state or input differs')
    for item in (descriptor, reference['accounting']):
        if (type(item['positions_physically_applied']) is not int or item['positions_physically_applied'] != count
                or type(item['credited_toward_governed_hour']) is not int or item['credited_toward_governed_hour'] != 0
                or item['included_in_published_terminal_lineage'] is not False):
            raise ValueError('continuation auxiliary accounting differs')
    if reference['published_state_restored'] is not True or descriptor['published_state_restored'] is not True:
        raise ValueError('continuation published state was not restored')
    if physical_positions != hour['applied_positions'] + count:
        raise ValueError('continuation physical positions differ')
    return count


def validate_continuation(runner, identity):
    """Open a completed hour through its bound native outcomes and retained artifacts."""
    request = identity['continuation']
    if not isinstance(request, dict) or set(request) != {'source_hour_result_path', 'source_hour_result_sha256'}:
        raise ValueError('continuation source hour fields differ')
    path = Path(request['source_hour_result_path']).resolve(strict=True)
    if path.name != 'hour-result.json':
        raise ValueError('continuation source must name the hour result')
    hour = bound_json(runner, path, request['source_hour_result_sha256'])
    root = path.parent
    prior_prediction = bound_json(runner, root/'prediction.json', hour['prediction_sha256'])
    prior = prior_prediction['identity']
    if (root.name != 'measurement-' + prior['run_id'] or hour['run_id'] != prior['run_id']
            or prior['run_id'] == identity['run_id'] or 'continuation' in prior
            or hour['hour']['schema'] != 'governed-hour-v1'
            or not hour_complete(measured_updates=hour['measured_updates'], elapsed_seconds=hour['pre_checkpoint_wall_seconds'])
            or hour['restored_state_matches'] is not True):
        raise ValueError('continuation requires a completed separate governed hour')
    for key in ('source_commit', 'source_sha256', 'config_sha256', 'data', 'seed', 'support',
                'optimizer', 'geometry', 'batch_documents', 'input_binding', 'gpu_uuid', 'hour',
                'production_mixture', 'checkpoint_probe', 'execution_mode', 'local_routing_mode'):
        if prior.get(key) != identity.get(key):
            raise ValueError('continuation source hour identity differs: ' + key)
    if runner.attention_selection(prior) != runner.attention_selection(identity):
        raise ValueError('continuation source hour attention selection differs')
    outcome_path = root.parent/'operator/operator-outcome.json'
    outcome = json.loads(outcome_path.read_bytes())
    if (outcome['run_id'] != prior['run_id'] or outcome['success'] is not True
            or outcome['daemon_cleanup_verified'] is not True
            or outcome['measurement_files']['hour-result.json'] != request['source_hour_result_sha256']):
        raise ValueError('continuation hour native outcome differs')
    for name in ('owned.json', 'disk.json', 'worker-terminal.json', 'rows.jsonl'):
        if runner.file_sha256(root/name) != outcome['measurement_files'][name]:
            raise ValueError('continuation hour terminal bytes differ')
    owned = json.loads((root/'owned.json').read_bytes())
    disk = json.loads((root/'disk.json').read_bytes())
    terminal = json.loads((root/'worker-terminal.json').read_bytes())
    if (owned['status'] != 'completed' or owned['returncode'] != 0 or owned['cleanup_verified'] is not True
            or owned.get('supervisor_failure') is not None
            or disk['outcome'] != 'COMPLETED' or disk['stop_reason'] is not None
            or disk['runner_exit_code'] != 0 or disk['child_exit_code'] != 0
            or disk['operating_reserve_breaches'] != []
            or terminal['status'] != 'completed'):
        raise ValueError('continuation source hour did not complete its resource envelope')
    rows = [json.loads(line) for line in (root/'rows.jsonl').read_bytes().splitlines()]
    geometry = identity['geometry']
    count = geometry['sequence_length'] * geometry['documents_per_step']
    if (len(rows) != geometry['warm_steps'] + hour['measured_updates']
            or hour['rows_sha256'] != runner.file_sha256(root/'rows.jsonl')
            or [row['phase'] for row in rows] != ['warm'] * geometry['warm_steps'] + ['measured'] * hour['measured_updates']
            or any(row['run_id'] != prior['run_id'] or row['prediction_sha256'] != hour['prediction_sha256']
                   or type(row['applied_positions']) is not int or row['applied_positions'] != count for row in rows)
            or sum(row['applied_positions'] for row in rows) != hour['applied_positions']):
        raise ValueError('continuation source hour rows differ')
    verify_continuation_accounting(runner, root, hour, prior, terminal['applied_positions'])
    if hour.get('continuation') is None:
        raise ValueError('continuation requires the independently bound next-update reference')
    descriptor = hour['continuation']
    reference = bound_json(runner, root/'continuation-reference.json', descriptor['reference_sha256'])
    hour_binding = bound_json(runner, root/'continuation-hour.json', descriptor['hour_binding_sha256'])
    pack = bound_json(runner, root/'continuation-next-pack.json', descriptor['next_pack_sha256'])
    child = bound_json(runner, root/'trained-child/checkpoint-manifest.json', hour['child_manifest_sha256'])
    child['checkpoint_manifest_sha256'] = hour['child_manifest_sha256']
    if child['data_cursor'] != hour_binding['terminal_data_cursor']:
        raise ValueError('continuation checkpoint cursor differs from the hour terminal')
    stream, receipt, tokenizer, ledger = runner.open_input_stream(identity['data'])
    cursor = dict(shard_index=int(child['data_cursor']['shard']), token_offset=child['data_cursor']['record_index'])
    geometry = identity['geometry']
    regenerated = HourPacks(stream, cursor, maximum_steps=1, sequence=geometry['sequence_length'],
                            documents=geometry['documents_per_step']).next_pack()
    for key in (*runner.INPUT_FIELDS, 'cursor_before', 'cursor_after'):
        if regenerated[key] != pack[key]:
            raise ValueError('continuation pack differs from the admitted stream: ' + key)
    return dict(root=root, hour=hour, reference=reference, hour_binding=hour_binding, pack=pack, child=child)


def run_continuation(*, runner, config, prepared, prediction, binding, custody, device, compiler, applied):
    """A new native worker restores the hour checkpoint and independently executes its next update."""
    import torch
    from ember.model.ember_v0_decoder import CIADecoder
    identity = prediction['identity']
    source = prepared['continuation']
    model = CIADecoder(architecture_config=config, **runner.decoder_kwargs(identity)).materialize_cpu(seed=identity['seed'])
    lengths = runner.document_lengths(tuple(source['pack']['document_starts']), len(source['pack']['token_ids']))
    def optimizer_factory(inventory):
        if sum(parameter.numel() for parameter in inventory.values()) != runner.POPULATION:
            raise ValueError('continuation optimizer population is incomplete')
        return torch.optim.AdamW(list(inventory.values()), **runner.optimizer_kwargs(identity['optimizer']))
    inventory, optimizer = runner.prepare_model(model, identity, lengths, device,
        mode=runner.execution_mode(identity), optimizer_factory=optimizer_factory)
    verify_checkpoint_restore(runner, model, optimizer, inventory, identity, source['root'], source['child'])
    before = continuation_state(runner, model, optimizer, source['child']['data_cursor'], device)
    expected = source['reference']['before']
    if before != expected:
        raise ValueError('fresh continuation restore differs from the hour terminal')
    reproduced = next_update_reference(runner, model, optimizer, inventory, identity, source['pack'],
        source['child'], before, device, applied)
    reproduced.update(restored_from=source['hour_binding']['terminal_checkpoint'],
        hour_binding_sha256=source['hour']['continuation']['hour_binding_sha256'],
        reference_sha256=source['hour']['continuation']['reference_sha256'],
        next_pack_sha256=source['hour']['continuation']['next_pack_sha256'],
        source_hour_result_sha256=identity['continuation']['source_hour_result_sha256'],
        c_compiler=compiler, prediction_sha256=binding['launch']['prediction_sha256'],
        claim='Observed next update from a separate owned worker; independent comparison remains required.')
    if any(runner.file_sha256(runner.ROOT/name) != digest for name, digest in identity['source_sha256'].items()):
        raise ValueError('source changed during continuation reproduction')
    if runner.file_sha256(source['root']/'trained-child/checkpoint-manifest.json') != source['child']['checkpoint_manifest_sha256']:
        raise ValueError('source checkpoint manifest changed during continuation reproduction')
    runner._write_new(custody/'continuation-reproduced.json', reproduced)


def next_update_reference(runner, model, optimizer, inventory, identity, pack, child,
                          terminal_state, device, applied):
    """Execute one uncredited auxiliary update from the published terminal state."""
    cursor = child['data_cursor']
    if pack['cursor_before'] != dict(shard_index=int(cursor['shard']), token_offset=cursor['record_index']):
        raise ValueError('continuation pack does not start at the published cursor')
    geometry = identity['geometry']
    positions = geometry['sequence_length'] * geometry['documents_per_step']
    if len(pack['token_ids']) != positions or len(pack['target_ids']) != positions:
        raise ValueError('continuation pack geometry differs')
    before = continuation_state(runner, model, optimizer, cursor, device)
    if before != terminal_state:
        raise ValueError('continuation starting state differs from the verified terminal state')
    lengths = runner.document_lengths(tuple(pack['document_starts']), positions)
    capture, buffers = bind_hour_capture(runner, model, identity, lengths, device)
    path = dict(mode=runner.execution_mode(identity), local_routing_mode=runner.local_routing_mode(identity),
                capture_phase='fresh-record' if capture is not None else 'eager',
                optimizer='torch-adamw-fused' if identity['hour']['arm'] == 'treatment' else 'torch-adamw',
                **runner.attention_selection(identity))
    try:
        row = runner.measure_step(model, optimizer, pack, device=device, batch_documents=True,
            run_id=identity['run_id'], capture=capture, record=capture is not None,
            expert_owners=runner.expert_owner_index(inventory))
        # The real resource callback records physical work even though no hour
        # throughput or published checkpoint credit is assigned to this update.
        applied(row['applied_positions'])
        if row['applied_positions'] != positions:
            raise ValueError('continuation applied position count differs')
        present = sorted(name for name, parameter in inventory.items() if parameter.grad is not None)
        if not present:
            raise ValueError('continuation observed no participating gradients')
        next_cursor = dict(shard=str(pack['cursor_after']['shard_index']),
            record_index=pack['cursor_after']['token_offset'], global_step=cursor['global_step']+1,
            tokens_seen=cursor['tokens_seen']+positions)
        after = continuation_state(runner, model, optimizer, next_cursor, device)
        return dict(run_id=identity['run_id'], source_identity=identity['source_sha256'], device=identity['gpu_uuid'],
            geometry=dict(microbatch=geometry['documents_per_step'], sequence=geometry['sequence_length'],
                          positions_per_update=positions), execution_path=path,
            executed_input_sha256=hashlib.sha256(runner.canonical({key: pack[key] for key in runner.INPUT_FIELDS})).hexdigest(),
            gradient_present=present, gradient_present_source='parameter.grad is not None after runner.measure_step with torch.optim.AdamW',
            loss=row['loss'], before=before, after=after,
            accounting=dict(positions_physically_applied=positions, credited_toward_governed_hour=0,
                            included_in_published_terminal_lineage=False))
    finally:
        if capture is not None:
            capture.invalidate()
        optimizer.zero_grad(set_to_none=True)


def publish_continuation_reference(runner, model, optimizer, inventory, identity, custody, child,
                                   terminal_state, prepared, device, applied, governed_wall, energy_binding):
    positions_per_update = identity['geometry']['sequence_length'] * identity['geometry']['documents_per_step']
    total_steps, positions = child['data_cursor']['global_step'], child['data_cursor']['tokens_seen']
    checkpoint_identity = dict(manifest_sha256=child['checkpoint_manifest_sha256'],
        run_id=identity['run_id'], global_step=total_steps, tokens_seen=positions,
        stream_receipt_sha256=identity['data']['receipt_sha256'])
    hour_binding = dict(source_identity=identity['source_sha256'], device=identity['gpu_uuid'],
        geometry=dict(microbatch=identity['geometry']['documents_per_step'],
                      sequence=identity['geometry']['sequence_length'], positions_per_update=positions_per_update),
        terminal_checkpoint=checkpoint_identity, terminal_facts=terminal_state['facts'],
        **runner.attention_selection(identity),
        terminal_rng_state_sha256=terminal_state['rng_state_sha256'], terminal_data_cursor=terminal_state['data_cursor'],
        live_state_verified_before_restore=True, governed_wall_seconds=governed_wall, energy=energy_binding)
    runner._write_new(custody / 'continuation-hour.json', hour_binding)
    saved_cursor, saved_index = dict(prepared['packs'].cursor), prepared['packs'].index
    reference_started = time.perf_counter()
    try:
        next_pack = prepared['packs'].next_pack()
        runner._write_new(custody / 'continuation-next-pack.json', next_pack)
        reference = next_update_reference(runner, model, optimizer, inventory, identity, next_pack,
                                          child, terminal_state, device, applied)
    finally:
        # S+1 is never published. Restore S even when the reference step refuses.
        try:
            verify_checkpoint_restore(runner, model, optimizer, inventory, identity, custody, child)
        finally:
            prepared['packs'].cursor, prepared['packs'].index = saved_cursor, saved_index
        if continuation_state(runner, model, optimizer, child['data_cursor'], device) != terminal_state:
            raise ValueError('continuation cleanup failed to restore the published terminal state')
    reference.update(restored_from=checkpoint_identity, published_state_restored=True,
        auxiliary_wall_seconds=time.perf_counter()-reference_started,
        hour_binding_sha256=runner.file_sha256(custody / 'continuation-hour.json'),
        next_pack_sha256=runner.file_sha256(custody / 'continuation-next-pack.json'))
    if any(runner.file_sha256(runner.ROOT / name) != digest for name, digest in identity['source_sha256'].items()):
        raise ValueError('hour source changed during continuation execution')
    runner._write_new(custody / 'continuation-reference.json', reference)
    continuation = dict(reference_sha256=runner.file_sha256(custody / 'continuation-reference.json'),
        hour_binding_sha256=reference['hour_binding_sha256'], next_pack_sha256=reference['next_pack_sha256'],
        positions_physically_applied=positions_per_update, credited_toward_governed_hour=0,
        included_in_published_terminal_lineage=False, published_state_restored=True,
        auxiliary_wall_seconds=reference['auxiliary_wall_seconds'])
    return continuation


def run_hour(*, runner, config, prepared, prediction, binding, custody, device, compiler, applied):
    """One complete-model worker shared by the explicit probe and both hour arms."""
    import torch
    from ember.model.ember_v0_decoder import CIADecoder
    identity = prediction['identity']
    positions_per_update = identity['geometry']['sequence_length'] * identity['geometry']['documents_per_step']
    import cia_hour_energy
    energy = cia_hour_energy.load(runner=runner, identity=identity, custody=custody, device=device)
    hour = identity['hour']
    mode = runner.execution_mode(identity)
    probe = hour['schema'] == 'checkpoint-probe-v1'
    model = CIADecoder(architecture_config=config, **runner.decoder_kwargs(identity)).materialize_cpu(seed=identity['seed'])
    first = prepared['first']
    lengths = runner.document_lengths(tuple(first['document_starts']), len(first['token_ids']))
    definition = identity['optimizer']
    def optimizer_factory(inventory):
        if sum(parameter.numel() for parameter in inventory.values()) != runner.POPULATION:
            raise ValueError('hour optimizer population is incomplete')
        return torch.optim.AdamW(list(inventory.values()), lr=definition['lr'], betas=tuple(definition['betas']),
            eps=definition['eps'], weight_decay=definition['weight_decay'], foreach=False,
            **({'fused': True} if hour['arm'] == 'treatment' else {}))
    inventory, optimizer = runner.prepare_model(model, identity, lengths, device,
        mode=mode, optimizer_factory=optimizer_factory)
    if {id(p) for group in optimizer.param_groups for p in group['params']} != {id(p) for p in inventory.values()}:
        raise ValueError('hour optimizer owner membership differs')
    runner._write_new(custody / 'model.json', dict(population=runner.POPULATION,
        optimizer_membership=list(inventory), trainable_parameters=sum(p.numel() for p in inventory.values() if p.requires_grad),
        input_binding=prepared['binding'], hour=hour, c_compiler=compiler,
        **runner.attention_selection(identity),
        claim='Complete-model execution inventory; no model qualification'))
    publish, owner_update_counts = checkpoint_publisher(
        runner, model, optimizer, inventory, identity, binding, custody, device)
    parent = publish('zero-parent', steps=0, tokens=0, cursor=identity['data']['cursor'])
    runner._write_new(custody / 'checkpoint-parent.json', dict(
        manifest_sha256=parent['checkpoint_manifest_sha256'], published=True))
    capture, buffers = bind_hour_capture(runner, model, identity, lengths, device)
    owners = runner.expert_owner_index(inventory)
    measured, positions, total_steps = 0, 0, 0
    started = None
    step_rates = []
    gc_identity = dict(run_id=identity['run_id'], prediction_sha256=binding['launch']['prediction_sha256'])
    with runner.GcPauseMeter().bind(**gc_identity) as gc_meter, (custody / 'rows.jsonl').open('xb') as rows, \
            (custody / 'gc-events.jsonl').open('xb') as gc_rows:
        pack = first
        while True:
            call_started = time.perf_counter()
            row = runner.measure_step(model, optimizer, pack, device=device, batch_documents=True,
                run_id=identity['run_id'], capture=capture, record=(capture is not None and total_steps == 0), expert_owners=owners)
            call_finished = time.perf_counter()
            row.update(run_id=identity['run_id'], prediction_sha256=binding['launch']['prediction_sha256'],
                input_sha256=prepared['binding']['input_sha256'], cursor_before=pack['cursor_before'],
                cursor_after=pack['cursor_after'], hour=hour)
            rows.write(runner.canonical(row) + b'\n')
            rows.flush()
            os.fsync(rows.fileno())
            # Collections since the previous row, classified in-step / outside-step against this step call's window;
            # filed beside (never inside) the row.
            gc_rows.write(runner.canonical(gc_meter.file(total_steps, row['phase'], call_started=call_started,
                                                         call_finished=call_finished)) + b'\n')
            gc_rows.flush()
            applied(row['applied_positions'])
            total_steps += 1
            positions += row['applied_positions']
            for name, parameter in inventory.items():
                if parameter.grad is not None:
                    owner_update_counts[name] = owner_update_counts.get(name, 0) + 1
            if total_steps == 1:
                if capture is not None:
                    optimizer.zero_grad(set_to_none=False)
                    capture.zero_grad()
                    buffers.capturing = True
                    try:
                        capture.capture(optimizer=optimizer)
                    finally:
                        buffers.capturing = False
                    runner._write_new(custody / 'capture.json', capture.receipt())
                # Warm-to-measured transition (the hour's single warm update is step 1), outside every timed interval,
                # eager control and captured treatment alike; the governed clock starts after it.
                runner._write_new(custody / 'gc-freeze.json', runner.freeze_resident_object_graph(**gc_identity))
                energy.begin()
                started = time.perf_counter()
            else:
                measured += 1
                step_rates.append(row['positions_per_second'])
                elapsed = time.perf_counter() - started
                if ((probe and measured == 2) or
                        (not probe and hour_complete(measured_updates=measured, elapsed_seconds=elapsed))):
                    break
            # Keep the one independently checked continuation pack reserved.
            # The finite measured allowance is not the hour completion condition.
            require_remaining_hour_capacity(measured, identity['geometry']['measured_steps'])
            pack = prepared['packs'].next_pack()
        closing_instant = time.perf_counter()
        gc_rows.write(runner.canonical(gc_meter.file(None, 'after-last-step', call_started=closing_instant,
                                                     call_finished=closing_instant)) + b'\n')
    elapsed_before_checkpoint = time.perf_counter() - started
    # Drop capture storage before the real codec's quiescence and restore checks.
    if capture is not None:
        capture.invalidate()
    optimizer.zero_grad(set_to_none=True)
    torch.cuda.synchronize(device)
    child = publish('trained-child', steps=total_steps, tokens=positions,
                    cursor=pack['cursor_after'], parent=custody / 'zero-parent')
    checkpoint_finished = time.perf_counter()
    terminal_state = continuation_state(runner, model, optimizer, child['data_cursor'], device)
    verify_checkpoint_restore(runner, model, optimizer, inventory, identity, custody, child, before=terminal_state)
    restore_finished = time.perf_counter()
    if any(runner.file_sha256(runner.ROOT / name) != digest for name, digest in identity['source_sha256'].items()):
        raise ValueError('hour source changed during execution')
    governed_wall = time.perf_counter() - started
    energy_binding = energy.end()
    # These endpoints are immutable before auxiliary work. The additional update
    # belongs only to the resource ledger and the continuation comparison.
    continuation = None if probe else publish_continuation_reference(
        runner, model, optimizer, inventory, identity, custody, child, terminal_state, prepared,
        device, applied, governed_wall, energy_binding)
    # Nearest-rank p10 is named so the statistic can be independently recomputed.
    p10 = sorted(step_rates)[max(0, math.ceil(.1 * len(step_rates)) - 1)]
    runner._write_new(custody / 'hour-result.json', dict(schema='ember-cia-hour-result-v1', hour=hour,
        measured_updates=measured, measured_positions=measured * positions_per_update, applied_positions=positions,
        governed_wall_seconds=governed_wall, pre_checkpoint_wall_seconds=elapsed_before_checkpoint,
        checkpoint_write_seconds=checkpoint_finished - started - elapsed_before_checkpoint,
        restore_and_verification_seconds=restore_finished - checkpoint_finished,
        complete_step_p10_positions_per_second=p10, quantile='nearest-rank-p10',
        overall_measured_positions_per_second=measured * positions_per_update / governed_wall,
        parent_manifest_sha256=parent['checkpoint_manifest_sha256'],
        child_manifest_sha256=child['checkpoint_manifest_sha256'], lineage=child['lineage'],
        rows_sha256=runner.file_sha256(custody / 'rows.jsonl'), restored_state_matches=True,
        gc_events_sha256=runner.file_sha256(custody / 'gc-events.jsonl'),
        gc_freeze_sha256=runner.file_sha256(custody / 'gc-freeze.json'),
        input_binding=prepared['binding'], source_commit=identity['source_commit'], run_id=identity['run_id'],
        prediction_sha256=binding['launch']['prediction_sha256'],
        energy=energy_binding,
        continuation=continuation,
        production_mixture_validation=prepared['mixture_validation'],
        claim='Checkpoint probe only' if probe else 'Observed hour and checkpoint mechanics; remaining qualification gates are separate'))

