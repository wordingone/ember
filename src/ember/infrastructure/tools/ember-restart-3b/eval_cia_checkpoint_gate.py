#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""CIA-strict, checkpoint-bound Evaluation minimum gate.

Opens one ADMITTED CIA checkpoint through the complete immutable-payload validator
(``checkpoint_artifacts._cia_validated_checkpoint``: manifest digest, receipt equality, architecture
identity, all 25 expert objects, optimizer and replay components, exact object closure), rebuilds the
CIA-3B CPU reference from the validated tensors only, and scores a frozen fixture of admitted-HELDOUT
catalog objects by next-token loss. Every identity is pinned by the caller and refused on mismatch; the
fixture's leakage assertion is executed against the frozen catalog export at gate time, never inherited.

Claim boundary: an executable minimum gate. It grants no evaluation tier, subject, certificate, learning,
throughput or model-qualification credit. The fixture is the admitted-heldout class (byte-verified against
the export's memberships); it is not the protected-evaluation object set, which is absent from local
custody. CPU reference execution only: the gate never activates CUDA residency, so it cannot be mistaken
for the governed training path. Host cost is two full populations in BF16 (validated tensors plus the
rebuilt reference) and must be scheduled outside a reserved GPU-hour host envelope.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
for _entry in (ROOT / 'src', Path(__file__).resolve().parent):
    if str(_entry) not in sys.path:
        sys.path.insert(0, str(_entry))

FIXTURE_SCHEMA = 'ember-eval-cia-heldout-fixture-v1'
RECEIPT_SCHEMA = 'ember-eval-cia-checkpoint-gate-receipt-v1'
CLAIM = ('executable checkpoint-bound minimum gate; admitted-heldout fixture; CPU reference; '
         'no evaluation tier, learning, throughput or qualification credit')
DERIVED_RECEIPT = '_manifests/derived-connector-receipt.json'


class GateRefusal(ValueError):
    def __init__(self, token: str, detail: str = ''):
        super().__init__(f'{token}:{detail}' if detail else token)
        self.token = token
        self.detail = detail


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')


def _pinned(path: Path, expected: str, token: str) -> bytes:
    raw = Path(path).read_bytes()
    if type(expected) is not str or len(expected) != 64 or sha256_bytes(raw) != expected:
        raise GateRefusal(token, f'{path} differs from pinned sha256')
    return raw


# --- catalog export ---------------------------------------------------------------------------------

def load_export(path: Path, expected_sha256: str) -> dict:
    """Frozen export plus the membership classes the leakage assertion is executed against."""
    from ember.governance.scripts import catalog_train_stream as cts
    export = json.loads(_pinned(path, expected_sha256, 'EXPORT_IDENTITY'))
    _, memberships, _, _ = cts._export_views(export)
    leakage = cts.leakage_sets(export)
    train = {row['exact_sha256'] for row in memberships
             if row.get('split') == 'train' and row.get('admission_state') == 'admitted'}
    return {'sha256': expected_sha256, 'heldout': leakage['heldout'], 'quarantined': leakage['quarantined'],
            'protected_eval': leakage['protected_eval'], 'train': train}


def classify_object(sha256: str, export: dict) -> dict:
    return {'heldout': sha256 in export['heldout'], 'train': sha256 in export['train'],
            'quarantined': sha256 in export['quarantined'], 'protected_eval': sha256 in export['protected_eval']}


def _admissible(classes: dict) -> bool:
    return classes['heldout'] and not (classes['train'] or classes['quarantined'] or classes['protected_eval'])


# --- fixture ----------------------------------------------------------------------------------------

def _document_text(raw: bytes) -> str | None:
    try:
        document = json.loads(raw)
    except ValueError:
        return None
    body = document.get('body_text') if isinstance(document, dict) else None
    if not isinstance(body, list):
        return None
    sentences = [row['sentence'] for row in body if isinstance(row, dict) and isinstance(row.get('sentence'), str)]
    return ' '.join(sentences) if sentences else None


def item_sha256(object_sha256: str, token_ids: list[int]) -> str:
    return sha256_bytes(canonical({'object_sha256': object_sha256, 'token_ids': token_ids}))


def build_fixture(*, export_path: Path, export_sha256: str, corpus_root: Path, tokenizer_path: Path,
                  tokenizer_sha256: str, count: int, sequence: int, output: Path) -> dict:
    """Freeze ``count`` admitted-heldout documents of ``sequence``+1 tokens each from one derived custody."""
    from tokenizers import Tokenizer, __version__ as tokenizers_version
    if type(count) is not int or not 1 <= count <= 4096 or type(sequence) is not int or not 8 <= sequence <= 4095:
        raise GateRefusal('FIXTURE_GEOMETRY', 'count in [1,4096] and sequence in [8,4095] required')
    export = load_export(export_path, export_sha256)
    _pinned(tokenizer_path, tokenizer_sha256, 'TOKENIZER_IDENTITY')
    tokenizer = Tokenizer.from_file(str(tokenizer_path))
    corpus_root = Path(corpus_root)
    receipt_path = corpus_root / DERIVED_RECEIPT
    if not receipt_path.is_file():
        raise GateRefusal('CORPUS_RECEIPT_MISSING', str(receipt_path))
    receipt = json.loads(receipt_path.read_bytes())
    files = [row for row in receipt.get('files', []) if isinstance(row, dict)
             and isinstance(row.get('sha256'), str) and isinstance(row.get('path'), str)]
    items, skipped = [], {'not_admissible': 0, 'missing': 0, 'digest_mismatch': 0, 'no_text': 0, 'short': 0}
    for row in sorted(files, key=lambda row: row['sha256']):
        if len(items) == count:
            break
        classes = classify_object(row['sha256'], export)
        if not _admissible(classes):
            skipped['not_admissible'] += 1
            continue
        path = corpus_root / row['path']
        if not path.is_file():
            skipped['missing'] += 1
            continue
        raw = path.read_bytes()
        if sha256_bytes(raw) != row['sha256']:
            skipped['digest_mismatch'] += 1
            continue
        text = _document_text(raw)
        if text is None:
            skipped['no_text'] += 1
            continue
        ids = tokenizer.encode(text, add_special_tokens=False).ids
        if len(ids) < sequence + 1:
            skipped['short'] += 1
            continue
        ids = [int(value) for value in ids[:sequence + 1]]
        items.append({'object_sha256': row['sha256'], 'path': row['path'], 'token_ids': ids,
                      'item_sha256': item_sha256(row['sha256'], ids)})
    if len(items) != count:
        raise GateRefusal('FIXTURE_UNDERFILLED', f'{len(items)} of {count} admissible documents; skipped {skipped}')
    fixture = {'schema_version': FIXTURE_SCHEMA, 'export_sha256': export_sha256, 'tokenizer_sha256': tokenizer_sha256,
               'tokenizers_version': tokenizers_version, 'corpus_root_name': corpus_root.name,
               'corpus_receipt_sha256': sha256_path(receipt_path), 'count': count, 'sequence': sequence,
               'object_class': 'admitted-heldout', 'items': items, 'skipped': skipped}
    fixture['self_sha256'] = sha256_bytes(canonical(fixture))
    payload = json.dumps(fixture, sort_keys=True, indent=1, ensure_ascii=False).encode('utf-8')
    with Path(output).open('xb') as handle:
        handle.write(payload)
    return {'path': str(output), 'sha256': sha256_bytes(payload), 'self_sha256': fixture['self_sha256'],
            'items': len(items), 'skipped': skipped}


def validate_fixture(path: Path, expected_sha256: str, export: dict) -> dict:
    """Pinned bytes, self digest, per-item digests and an EXECUTED leakage assertion."""
    fixture = json.loads(_pinned(path, expected_sha256, 'FIXTURE_IDENTITY'))
    if type(fixture) is not dict or fixture.get('schema_version') != FIXTURE_SCHEMA:
        raise GateRefusal('FIXTURE_SCHEMA')
    declared = fixture.get('self_sha256')
    body = {key: value for key, value in fixture.items() if key != 'self_sha256'}
    if sha256_bytes(canonical(body)) != declared:
        raise GateRefusal('FIXTURE_SELF_DIGEST')
    if fixture['export_sha256'] != export['sha256']:
        raise GateRefusal('FIXTURE_EXPORT_MISMATCH')
    items = fixture['items']
    if type(items) is not list or len(items) != fixture['count'] or not items:
        raise GateRefusal('FIXTURE_COUNT')
    sequence = fixture['sequence']
    seen = set()
    for item in items:
        ids = item['token_ids']
        if (type(ids) is not list or len(ids) != sequence + 1 or any(type(v) is not int or v < 0 for v in ids)
                or item_sha256(item['object_sha256'], ids) != item['item_sha256']):
            raise GateRefusal('FIXTURE_ITEM_DIGEST', item.get('object_sha256', '?'))
        if item['object_sha256'] in seen:
            raise GateRefusal('FIXTURE_DUPLICATE_OBJECT', item['object_sha256'])
        seen.add(item['object_sha256'])
        classes = classify_object(item['object_sha256'], export)
        if not _admissible(classes):
            raise GateRefusal('FIXTURE_LEAKAGE', f"{item['object_sha256']}:{classes}")
    return {'sha256': expected_sha256, 'self_sha256': declared, 'count': len(items), 'sequence': sequence,
            'tokenizer_sha256': fixture['tokenizer_sha256'], 'object_class': fixture['object_class'],
            'leakage_assertion': {'items_checked': len(items), 'heldout_members': len(items),
                                  'train_overlaps': 0, 'quarantined_overlaps': 0, 'protected_eval_overlaps': 0,
                                  'export_train_hashes': len(export['train']),
                                  'export_heldout_hashes': len(export['heldout']),
                                  'export_protected_eval_hashes': len(export['protected_eval'])},
            'items': items}


# --- checkpoint -------------------------------------------------------------------------------------

def open_checkpoint(root: Path, receipt_path: Path, *, max_restore_bytes: int) -> tuple[dict, dict]:
    """Complete immutable-payload validation; returns the verified manifest facts and retained tensors."""
    import checkpoint_artifacts as artifacts
    receipt = json.loads(Path(receipt_path).read_bytes())
    if type(receipt) is not dict:
        raise GateRefusal('RECEIPT_SCHEMA')
    identity = receipt.get('checkpoint')
    if type(identity) is not dict or identity.get('byte_sha256') != receipt.get('checkpoint_manifest_sha256'):
        raise GateRefusal('RECEIPT_IDENTITY', 'checkpoint.byte_sha256 differs from checkpoint_manifest_sha256')
    if type(max_restore_bytes) is not int or max_restore_bytes < 1:
        raise GateRefusal('RESTORE_BOUND')
    try:
        verified, tensors, optimizer, replay = artifacts._cia_validated_checkpoint(
            Path(root), receipt, retain_model=True, max_restore_payload_bytes=max_restore_bytes)
    except (ValueError, OSError, KeyError, TypeError) as error:
        raise GateRefusal('CHECKPOINT_REFUSED', f'{type(error).__name__}: {error}') from error
    del optimizer, replay
    if verified['checkpoint_manifest_sha256'] != identity['byte_sha256']:
        raise GateRefusal('CHECKPOINT_REFUSED', 'validated manifest digest differs from receipt identity')
    return verified, tensors


def build_reference(verified: dict, tensors: dict):
    """CPU reference materialized once, then overwritten by the validated tensors only."""
    import torch
    from ember.model.ember_v0_contract import validate_cia_architecture, cia_architecture_sha256
    from ember.model.ember_v0_decoder import CIADecoder
    config = verified['architecture_config']
    validate_cia_architecture(config)
    architecture_sha256 = cia_architecture_sha256(config)
    model = CIADecoder(architecture_config=config).materialize_cpu(seed=0)
    parameters = model.parameter_inventory()
    if set(parameters) != set(tensors):
        raise GateRefusal('INVENTORY_MISMATCH', 'validated tensors differ from the declared inventory')
    for name, value in tensors.items():
        target = parameters[name]
        if tuple(value.shape) != tuple(target.shape) or value.dtype != target.dtype:
            raise GateRefusal('INVENTORY_MISMATCH', name)
    with torch.no_grad():
        for name, value in tensors.items():
            parameters[name].copy_(value)
    for parameter in parameters.values():
        parameter.requires_grad_(False)
    model.parameter_inventory()
    model.eval()
    return model, architecture_sha256


def score_item(model, token_ids: list[int]) -> float:
    import torch
    import torch.nn.functional as F
    tokens = torch.tensor(token_ids, dtype=torch.long)
    inputs, targets = tokens[:-1], tokens[1:]
    positions = torch.tensor([[index, 0, 0] for index in range(len(inputs))], dtype=torch.long)
    with torch.no_grad():
        logits = model(model.embed_text(inputs), positions, document_starts=(0,))
        loss = F.cross_entropy(logits.float(), targets, reduction='mean')
    value = float(loss)
    if value != value or value in (float('inf'), float('-inf')):
        raise GateRefusal('NONFINITE_LOSS')
    return value


def run_gate(args) -> dict:
    import torch
    started = time.monotonic()
    export = load_export(args.export, args.export_sha256)
    fixture = validate_fixture(args.fixture, args.fixture_sha256, export)
    if fixture['tokenizer_sha256'] != args.tokenizer_sha256:
        raise GateRefusal('TOKENIZER_IDENTITY', 'fixture tokenizer differs from the pinned tokenizer')
    _pinned(args.tokenizer, args.tokenizer_sha256, 'TOKENIZER_IDENTITY')
    verified, tensors = open_checkpoint(args.checkpoint, args.receipt, max_restore_bytes=args.max_restore_bytes)
    model, architecture_sha256 = build_reference(verified, tensors)
    del tensors
    per_item = []
    for item in fixture['items']:
        per_item.append({'object_sha256': item['object_sha256'], 'item_sha256': item['item_sha256'],
                         'loss': score_item(model, item['token_ids'])})
    repeat = score_item(model, fixture['items'][0]['token_ids'])
    if repeat != per_item[0]['loss']:
        raise GateRefusal('NONDETERMINISTIC_SCORE', f'{repeat} != {per_item[0]["loss"]}')
    mean = sum(row['loss'] for row in per_item) / len(per_item)
    receipt = {
        'schema_version': RECEIPT_SCHEMA, 'result': 'PASS', 'claim': CLAIM,
        'checkpoint': {'root': str(Path(args.checkpoint).resolve()), 'receipt_path': str(Path(args.receipt).resolve()),
                       'manifest_sha256': verified['checkpoint_manifest_sha256'],
                       'architecture_revision': verified['architecture_revision'],
                       'architecture_sha256': architecture_sha256, 'data_cursor': verified['data_cursor'],
                       'expert_objects': len(verified['expert_parameter_sha256']),
                       'active_expert_ids': verified['active_expert_ids'],
                       'descendant': 'lineage' in verified,
                       'qualification': verified['qualification']},
        'fixture': {key: value for key, value in fixture.items() if key != 'items'},
        'export_sha256': export['sha256'], 'tokenizer_sha256': args.tokenizer_sha256,
        'scores': {'per_item': per_item, 'mean_loss': mean, 'items': len(per_item),
                   'tokens_scored': len(per_item) * fixture['sequence']},
        'determinism': {'first_item_repeat_identical': True},
        'environment': {'device': 'cpu', 'torch': torch.__version__, 'python': sys.version.split()[0],
                        'wall_seconds': time.monotonic() - started},
    }
    receipt['self_sha256'] = sha256_bytes(canonical(receipt))
    payload = json.dumps(receipt, sort_keys=True, indent=1).encode('utf-8')
    with Path(args.output).open('xb') as handle:
        handle.write(payload)
    return receipt


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    modes = parser.add_subparsers(dest='mode', required=True)
    fixture = modes.add_parser('build-fixture', help='freeze an admitted-heldout fixture from one derived custody')
    fixture.add_argument('--export', type=Path, required=True)
    fixture.add_argument('--export-sha256', required=True)
    fixture.add_argument('--corpus-root', type=Path, required=True)
    fixture.add_argument('--tokenizer', type=Path, required=True)
    fixture.add_argument('--tokenizer-sha256', required=True)
    fixture.add_argument('--count', type=int, default=16)
    fixture.add_argument('--sequence', type=int, default=512)
    fixture.add_argument('--output', type=Path, required=True)
    run = modes.add_parser('run', help='open one admitted CIA checkpoint and score the pinned fixture')
    run.add_argument('--checkpoint', type=Path, required=True)
    run.add_argument('--receipt', type=Path, required=True)
    run.add_argument('--fixture', type=Path, required=True)
    run.add_argument('--fixture-sha256', required=True)
    run.add_argument('--export', type=Path, required=True)
    run.add_argument('--export-sha256', required=True)
    run.add_argument('--tokenizer', type=Path, required=True)
    run.add_argument('--tokenizer-sha256', required=True)
    run.add_argument('--max-restore-bytes', type=int, default=32 * 1024 ** 3)
    run.add_argument('--output', type=Path, required=True)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.mode == 'build-fixture':
            result = build_fixture(export_path=args.export, export_sha256=args.export_sha256,
                                   corpus_root=args.corpus_root, tokenizer_path=args.tokenizer,
                                   tokenizer_sha256=args.tokenizer_sha256, count=args.count,
                                   sequence=args.sequence, output=args.output)
        else:
            receipt = run_gate(args)
            result = {'result': receipt['result'], 'mean_loss': receipt['scores']['mean_loss'],
                      'items': receipt['scores']['items'], 'manifest_sha256': receipt['checkpoint']['manifest_sha256'],
                      'self_sha256': receipt['self_sha256'], 'output': str(args.output)}
    except GateRefusal as refusal:
        sys.stderr.write(f'REFUSED:{refusal.token}:{refusal.detail}\n')
        return 2
    sys.stdout.write(json.dumps(result, sort_keys=True) + '\n')
    return 0


if __name__ == '__main__':
    os.environ.setdefault('PYTHONDONTWRITEBYTECODE', '1')
    raise SystemExit(main())
