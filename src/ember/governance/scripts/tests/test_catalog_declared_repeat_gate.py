# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Declared-repeat gate: PASS only when every extension row is admitted catalog membership AND a declared repeat."""
import hashlib
import json

import importlib.util
import sys
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[1] / 'catalog_declared_repeat_gate.py'
SPEC = importlib.util.spec_from_file_location('catalog_declared_repeat_gate', SOURCE)
g = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = g
SPEC.loader.exec_module(g)


def _row(digest):
    return {'spans': [{'sha256': digest, 'token_start': 0, 'token_end': 8}]}


@pytest.fixture
def world(tmp_path, monkeypatch):
    rows = [_row('a' * 64), _row('a' * 64), _row('b' * 64)]
    ledger = tmp_path / 'ledger.jsonl'
    ledger.write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8')
    export = tmp_path / 'export.json'
    export.write_text('{}', encoding='utf-8')
    decl = tmp_path / 'decl.md'
    decl.write_text('declaration\n', encoding='utf-8')
    monkeypatch.setattr(g.catalog, 'read_shard_ledger', lambda path: [json.loads(l) for l in path.read_text().splitlines()])
    monkeypatch.setattr(g.catalog, '_admitted_train_windows',
                        lambda export, ids, tok: ({'d1': [('a' * 64, 8), ('b' * 64, 8)]}, {}))
    monkeypatch.setattr(g.catalog, 'leakage_sets', lambda export: {'heldout': set()})

    def run(labels, **over):
        side = tmp_path / 'side.json'
        side.write_text(json.dumps({'rows': labels}), encoding='utf-8')
        kw = dict(ledger=ledger, sidecar=side, declaration=decl, export_path=export,
                  export_sha256=hashlib.sha256(b'{}').hexdigest(), dataset_ids=['d1'], tokenizer_sha256='t' * 64,
                  parent_rows=2)
        kw.update(over)
        return g.gate(**kw)
    return run, ledger, monkeypatch


REPEAT = {'repeat_declared': True, 'ledger_pass_index': 2}
FRESH = {'repeat_declared': False, 'ledger_pass_index': 0}


def test_pass_binds_extension_and_kind(world):
    run, ledger, _ = world
    r = run([FRESH, REPEAT, REPEAT])
    assert (r['verdict'], r['kind'], r['rows_checked'], r['unadmitted_rows'], r['c1_basis']) == \
        ('PASS', 'declared-repeat', 1, 0, 'catalog-admitted')
    assert r['extension_ledger_sha256'] == hashlib.sha256(ledger.read_bytes().splitlines(keepends=True)[2]).hexdigest()


def test_red_fresh_unadmitted_row_refuses(world):
    run, _, monkeypatch = world
    # the extension row's span is not admitted catalog train membership
    monkeypatch.setattr(g.catalog, '_admitted_train_windows', lambda export, ids, tok: ({'d1': [('a' * 64, 8)]}, {}))
    r = run([FRESH, REPEAT, REPEAT])
    assert r['verdict'] == 'REFUSE' and r['unadmitted_rows'] == 1
    assert 'lacks admitted train membership' in r['unadmitted_sample'][0]['reason']


def test_red_undeclared_row_refuses(world):
    run, _, _ = world
    r = run([FRESH, REPEAT, FRESH])
    assert r['verdict'] == 'REFUSE' and r['undeclared_rows'] == 1


def test_red_protected_overlap_refuses(world):
    run, _, monkeypatch = world
    monkeypatch.setattr(g.catalog, 'leakage_sets', lambda export: {'heldout': {'b' * 64}})
    assert run([FRESH, REPEAT, REPEAT])['verdict'] == 'REFUSE'


def test_export_sha_mismatch_raises(world):
    run, _, _ = world
    with pytest.raises(ValueError, match='catalog export bytes'):
        run([FRESH, REPEAT, REPEAT], export_sha256='0' * 64)
