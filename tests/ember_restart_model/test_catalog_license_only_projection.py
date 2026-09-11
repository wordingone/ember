# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Keep heldout licence evidence out of training catalog membership."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/ember/infrastructure/tools/ember-restart-3b'))
import catalog_admission as catalog
import mint_github_license_partition as partition_producer


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture
def projection(tmp_path, monkeypatch):
    helper_path = ROOT / 'tests/ember_restart_model/domain-governance/test_mint_github_license_partition.py'
    loader = importlib.util.spec_from_file_location('partition_projection_fixture', helper_path)
    helper = importlib.util.module_from_spec(loader)
    loader.loader.exec_module(helper)
    rows = []
    for split in ('train', 'heldout'):
        source = tmp_path / split
        source.mkdir()
        connector, connector_sha = helper._connector(source, extra_files=int(split == 'heldout'))
        output = source / 'partition'
        source_id = f'candidate-software_engineering-{split}-1'
        partition_producer.mint_partition(
            connector_receipt_path=connector, connector_receipt_sha256=connector_sha,
            output=output, source_commit='1' * 40, source_id=source_id,
            connector_slot=f'H-{split}-2', split=split,
            domain='software_engineering', expected_topic='testing',
        )
        receipt = output / 'partition-receipt.json'
        row = dict(license_partition_receipt_path=str(receipt),
                   license_partition_receipt_sha256=digest(receipt.read_bytes()),
                   source_id=source_id, domain='software_engineering', split=split,
                   supporting_receipts=[])
        if split == 'heldout':
            row['license_only'] = True
        rows.append(row)
    # The production path classifier already recognizes this fixture's LICENSE files.
    # Receipt and blob validation remain the actual production functions.
    monkeypatch.setattr(catalog, '_load_partition_media_type_table', lambda _sha=None: {
        'classes': {}})
    monkeypatch.setattr(catalog, '_load_predecessor_media_type_table',
                        lambda: {'media_types_by_object_id': {}})
    return dict(schema_version='ember-issue1581-catalog-projection-spec-v1',
                tokenizer_sha256='4' * 64, created_at_ms=1, rows=rows)


def test_heldout_license_only_reaches_index_without_training_membership(projection):
    expected_manifest = catalog.project_catalog_spec(spec_raw=canonical({
        **projection, 'rows': projection['rows'][:1]}))
    license_rows = []
    manifest = catalog.project_catalog_spec(spec_raw=canonical(projection), license_rows=license_rows)
    assert manifest == expected_manifest
    index = json.loads(catalog.build_object_license_index(license_rows))
    heldout_only = digest(b'fixture-0\n')
    objects = {entry['sha256']: entry for entry in index['objects']}
    assert heldout_only in objects
    assert objects[heldout_only]['source_ids'] == [projection['rows'][1]['source_id']]
    assert heldout_only.encode() not in manifest
    shared = objects[digest(b'alpha bytes\n')]
    assert set(shared['source_ids']) == {row['source_id'] for row in projection['rows']}
    assert index['object_count'] == 4 and index['unnamed_count'] == 0


def test_heldout_without_marker_is_still_refused(projection):
    projection['rows'][1].pop('license_only')
    with pytest.raises(ValueError, match='PARTITION_PROJECTION_SPLIT_REFUSED'):
        catalog.project_catalog_spec(spec_raw=canonical(projection), license_rows=[])


def test_train_row_cannot_claim_license_only(projection):
    projection['rows'][0]['license_only'] = True
    with pytest.raises(ValueError, match='PARTITION_PROJECTION_SPLIT_REFUSED'):
        catalog.project_catalog_spec(spec_raw=canonical(projection), license_rows=[])


def test_license_only_keeps_real_partition_authority_refusal(projection):
    row = projection['rows'][1]
    path = Path(row['license_partition_receipt_path'])
    receipt = json.loads(path.read_bytes())
    receipt['repository_count'] += 1
    path.write_bytes(canonical(receipt))
    row['license_partition_receipt_sha256'] = digest(path.read_bytes())
    output = []
    with pytest.raises(ValueError, match='PARTITION_PROJECTION_AUTHORITY_REFUSED'):
        catalog.project_catalog_spec(spec_raw=canonical(projection), license_rows=output)
    assert output == []


@pytest.mark.parametrize('marker', [False, None, 1, 'true'])
def test_license_only_marker_requires_literal_true(projection, marker):
    projection['rows'][1]['license_only'] = marker
    with pytest.raises(ValueError, match='LICENSE_ONLY'):
        catalog.project_catalog_spec(spec_raw=canonical(projection), license_rows=[])


def test_license_only_requires_an_index_consumer(projection):
    with pytest.raises(ValueError, match='LICENSE_ONLY'):
        catalog.project_catalog_spec(spec_raw=canonical(projection))


def test_license_only_does_not_publish_partial_index_on_manifest_refusal(projection):
    projection['rows'] = projection['rows'][1:]
    output = []
    with pytest.raises(ValueError, match='catalog dataset rows'):
        catalog.project_catalog_spec(spec_raw=canonical(projection), license_rows=output)
    assert output == []


def test_license_only_cli_emits_separate_manifest_and_index(projection, tmp_path):
    spec = tmp_path / 'projection.json'
    spec.write_bytes(canonical(projection))
    manifest = tmp_path / 'manifest.json'
    index = tmp_path / 'license-index.json'
    assert catalog.main(['project', '--spec', str(spec), '--output', str(manifest),
                         '--license-index', str(index)]) == 0
    heldout_only = digest(b'fixture-0\n')
    assert heldout_only.encode() not in manifest.read_bytes()
    assert heldout_only.encode() in index.read_bytes()


def test_license_only_cli_requires_index_output(projection, tmp_path):
    spec = tmp_path / 'projection.json'
    spec.write_bytes(canonical(projection))
    manifest = tmp_path / 'manifest.json'
    assert catalog.main(['project', '--spec', str(spec), '--output', str(manifest)]) == 2
    assert not manifest.exists()
