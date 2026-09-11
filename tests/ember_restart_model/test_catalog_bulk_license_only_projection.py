# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Keep heldout BULK connector licence evidence out of training catalog membership (#1581).

Mirror of test_catalog_license_only_projection.py for the bulk connector route: a heldout
connector row marked ``license_only: true`` reaches the object licence index and never the
dataset manifest; a heldout row without the marker still cannot share a manifest with train
rows; a train row cannot claim the marker; the marker is a literal ``True`` and needs an index
consumer; a marked row whose receipt authority fails publishes nothing.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/ember/infrastructure/tools/ember-restart-3b'))
import catalog_admission as catalog  # noqa: E402

TOKENIZER = '2c557e7ffe64706112ea947d056be503005d90b16f64c57ec354267c7e9e9c97'
TRAIN_ID = 'candidate-formal_logic-train-3'
HELDOUT_ID = 'candidate-formal_logic-heldout-9'
SHARED = b'theorem shared : True := trivial\n'
HELDOUT_ONLY = b'theorem heldout_only : True := trivial\n'
TRAIN_ONLY = b'theorem train_only : True := trivial\n'


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def write_connector(root, *, source, files):
    rows = []
    for name, raw in files:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        rows.append({'path': name, 'bytes': len(raw), 'sha256': digest(raw)})
    payload = {
        'canonical_url': f'https://example.test/{source}',
        'connector': {'name': 'fixture', 'version': 'v1'},
        'fetched_at': '2026-09-06T00:00:00Z',
        'files': rows,
        'license': 'CC-BY-4.0',
        'schema': 'corpus-connector-receipt-v1',
        'sha256_manifest': digest('\n'.join(sorted(row['sha256'] for row in rows)).encode()),
        'source': 'fixture',
        'source_id': source,
        'total_bytes': sum(row['bytes'] for row in rows),
        'dest_root': str(root),
    }
    path = root / 'connector.json'
    path.write_bytes(canonical(payload))
    return path, digest(path.read_bytes())


def bulk_row(receipt_path, receipt_sha, source_id, split, **extra):
    row = {
        'receipt_path': str(receipt_path),
        'expected_receipt_sha256': receipt_sha,
        'source_id': source_id,
        'expected_source_selector': source_id,
        'expected_license_text_sha256': digest(b'CC-BY-4.0'),
        'domain': 'formal_logic',
        'split': split,
        'supporting_receipts': [],
    }
    row.update(extra)
    return row


@pytest.fixture
def projection(tmp_path):
    train_path, train_sha = write_connector(
        tmp_path / 'train', source=TRAIN_ID, files=[('Shared.lean', SHARED), ('Train.lean', TRAIN_ONLY)])
    heldout_path, heldout_sha = write_connector(
        tmp_path / 'heldout', source=HELDOUT_ID, files=[('Shared.lean', SHARED), ('Heldout.lean', HELDOUT_ONLY)])
    rows = [
        bulk_row(train_path, train_sha, TRAIN_ID, 'train'),
        bulk_row(heldout_path, heldout_sha, HELDOUT_ID, 'heldout', license_only=True),
    ]
    return dict(schema_version='ember-issue1581-catalog-projection-spec-v1',
                tokenizer_sha256=TOKENIZER, created_at_ms=1, rows=rows)


def test_heldout_bulk_license_only_reaches_index_without_training_membership(projection):
    expected_manifest = catalog.project_catalog_spec(spec_raw=canonical({
        **projection, 'rows': projection['rows'][:1]}))
    license_rows = []
    manifest = catalog.project_catalog_spec(spec_raw=canonical(projection), license_rows=license_rows)
    assert manifest == expected_manifest
    index = json.loads(catalog.build_object_license_index(license_rows))
    objects = {entry['sha256']: entry for entry in index['objects']}
    assert objects[digest(HELDOUT_ONLY)]['source_ids'] == [HELDOUT_ID]
    assert objects[digest(TRAIN_ONLY)]['source_ids'] == [TRAIN_ID]
    assert set(objects[digest(SHARED)]['source_ids']) == {TRAIN_ID, HELDOUT_ID}
    assert digest(HELDOUT_ONLY).encode() not in manifest
    assert index['object_count'] == 3 and index['unnamed_count'] == 0


def test_heldout_bulk_without_marker_cannot_share_a_training_manifest(projection):
    projection['rows'][1].pop('license_only')
    with pytest.raises(ValueError, match='one admitted split'):
        catalog.project_catalog_spec(spec_raw=canonical(projection), license_rows=[])


def test_train_bulk_row_cannot_claim_license_only(projection):
    projection['rows'][0]['license_only'] = True
    with pytest.raises(ValueError, match='BULK_PROJECTION_LICENSE_ONLY_SPLIT_REFUSED'):
        catalog.project_catalog_spec(spec_raw=canonical(projection), license_rows=[])


def test_marked_row_with_train_split_and_heldout_identity_is_refused(projection):
    # The split declared on the row must be heldout; the source identity alone does not qualify.
    projection['rows'][1]['split'] = 'train'
    with pytest.raises(ValueError, match='BULK_PROJECTION_LICENSE_ONLY_SPLIT_REFUSED'):
        catalog.project_catalog_spec(spec_raw=canonical(projection), license_rows=[])


@pytest.mark.parametrize('marker', [1, 'true', False, None])
def test_bulk_license_only_marker_requires_literal_true(projection, marker):
    projection['rows'][1]['license_only'] = marker
    with pytest.raises(ValueError, match='LICENSE_ONLY_MARKER_REFUSED'):
        catalog.project_catalog_spec(spec_raw=canonical(projection), license_rows=[])


def test_bulk_license_only_requires_an_index_consumer(projection):
    with pytest.raises(ValueError, match='LICENSE_ONLY'):
        catalog.project_catalog_spec(spec_raw=canonical(projection))


def test_bulk_license_only_keeps_receipt_authority_refusal(projection, tmp_path):
    row = projection['rows'][1]
    forged = tmp_path / 'heldout' / 'connector.json'
    payload = json.loads(forged.read_bytes())
    payload['license'] = 'MIT'
    forged.write_bytes(canonical(payload))
    row['expected_receipt_sha256'] = digest(forged.read_bytes())
    output = []
    with pytest.raises(ValueError, match='license does not match the frozen authority'):
        catalog.project_catalog_spec(spec_raw=canonical(projection), license_rows=output)
    assert output == []


def test_bulk_license_only_does_not_publish_partial_index_on_manifest_refusal(projection):
    projection['rows'] = projection['rows'][1:]
    output = []
    with pytest.raises(ValueError, match='catalog dataset rows'):
        catalog.project_catalog_spec(spec_raw=canonical(projection), license_rows=output)
    assert output == []


def test_bulk_license_only_cli_emits_separate_manifest_and_index(projection, tmp_path):
    spec = tmp_path / 'projection.json'
    spec.write_bytes(canonical(projection))
    manifest = tmp_path / 'manifest.json'
    index = tmp_path / 'license-index.json'
    assert catalog.main(['project', '--spec', str(spec), '--output', str(manifest),
                         '--license-index', str(index)]) == 0
    assert digest(HELDOUT_ONLY).encode() not in manifest.read_bytes()
    assert digest(HELDOUT_ONLY).encode() in index.read_bytes()
    assert catalog.main(['project', '--spec', str(spec), '--output', str(tmp_path / 'm2.json')]) == 2
    assert not (tmp_path / 'm2.json').exists()
