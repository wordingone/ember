#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Tests for the #1945 H38 decode-prefetch refuter.

WHAT THIS GUARDS. H34 ran an hour whose every row said the two-ahead image decode never hit, and no reader existed
to say so. The refuter is that reader. The cases pin: the three buckets (hit, miss, residual) with the residual
printed as a first-class number; the SUPPORTED / REFUTED verdict at the N - 2 threshold, where 2 is the upper bound on
structural misses (update 2 under two-ahead; update 1 is covered by the record step's one-ahead prefetch); the refusal on fewer rows than requested; the warm row skipped; the stream stopping
at N (so a 200 MB rows file is never read whole); and one deliberate red through main() proving the tool exits 3 on
the H34 shape rather than printing a tidy count and exiting 0.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[5]
REFUTER = REPO_ROOT / 'src' / 'ember' / 'governance' / 'scripts' / 'issue1945_h38_prefetch_refuter.py'


@pytest.fixture(scope='module')
def refuter():
    assert REFUTER.is_file(), 'refuter source is missing: %s' % REFUTER
    spec = importlib.util.spec_from_file_location('h38_prefetch_refuter_under_test', REFUTER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_rows(path: Path, count: int, *, misses=(), without_field=(), trailing=''):
    """index 0 warm, then `count` measured rows; updates 1 and 2 modelled in-step (the allowance's upper bound)."""
    lines = []
    for index in range(count + 1):
        row = dict(index=index, phase='warm' if index == 0 else 'measured', wall_seconds=0.05)
        if index not in without_field:
            row['image_patches_source'] = ('decoded-in-this-step' if index in (1, 2) or index in misses
                                           else 'decoded-in-previous-step-wall')
        lines.append(json.dumps(row, sort_keys=True))
    path.write_text('\n'.join(lines) + '\n' + trailing, encoding='utf-8')
    return path


def test_constants_are_the_contract(refuter):
    assert refuter.HIT == 'decoded-in-previous-step-wall'
    assert refuter.MISS == 'decoded-in-this-step'
    assert refuter.DEFAULT_ROWS == 1200
    assert refuter.STRUCTURAL_MISSES == 2
    assert (refuter.EXIT_SUPPORTED, refuter.EXIT_INSUFFICIENT, refuter.EXIT_REFUTED) == (0, 2, 3)


def test_a_cured_run_is_supported_with_exactly_the_two_structural_misses(refuter, tmp_path):
    rows = write_rows(tmp_path / 'rows.jsonl', 1200)
    counts = refuter.census(rows, 1200)
    assert (counts['hit'], counts['miss'], counts['residual'], counts['measured']) == (1198, 2, 0, 1200)
    assert counts['first_miss_indices'] == [1, 2]
    assert counts['skipped_non_measured'] == 1  # the warm row
    assert refuter.verdict(counts) == ('SUPPORTED', 0)


def test_the_h34_shape_is_refuted_with_exit_3_through_main(refuter, tmp_path, capsys):
    rows = write_rows(tmp_path / 'rows.jsonl', 1200, misses=range(1, 1201))
    out = tmp_path / 'verdict.json'
    code = refuter.main(['--rows', str(rows), '--json', str(out)])
    printed = capsys.readouterr().out
    assert code == 3
    assert printed.rstrip().endswith('REFUTED')
    assert 'decoded-in-previous-step-wall 0' in printed
    assert 'decoded-in-this-step 1200' in printed
    assert 'residual 0 (rows with neither value)' in printed
    payload = json.loads(out.read_text(encoding='utf-8'))
    assert payload['status'] == 'REFUTED' and payload['hit'] == 0 and payload['miss'] == 1200


def test_one_miss_past_the_allowance_refutes(refuter, tmp_path):
    rows = write_rows(tmp_path / 'rows.jsonl', 1200, misses=(700,))
    counts = refuter.census(rows, 1200)
    assert (counts['hit'], counts['miss']) == (1197, 3)
    assert refuter.verdict(counts) == ('REFUTED', 3)


def test_the_residual_is_counted_as_its_own_bucket_and_never_as_a_hit(refuter, tmp_path, capsys):
    rows = write_rows(tmp_path / 'rows.jsonl', 100, without_field=(10, 20, 30))
    code = refuter.main(['--rows', str(rows), '--rows-count', '100'])
    printed = capsys.readouterr().out
    counts = refuter.census(rows, 100)
    assert (counts['hit'], counts['miss'], counts['residual']) == (95, 2, 3)
    assert counts['first_residual_indices'] == [10, 20, 30]
    assert 'residual 3 (rows with neither value)  first indices [10, 20, 30]' in printed
    assert code == 3  # 95 < 98: the residual rows are not hits


def test_fewer_measured_rows_than_requested_is_a_refusal_not_a_verdict(refuter, tmp_path, capsys):
    rows = write_rows(tmp_path / 'rows.jsonl', 50)
    code = refuter.main(['--rows', str(rows), '--rows-count', '100'])
    printed = capsys.readouterr().out
    assert code == 2
    assert printed.rstrip().endswith('REFUSED insufficient-measured-rows')
    assert 'measured rows read 50 (requested 100' in printed


def test_the_stream_stops_at_n_and_never_reads_the_rest_of_the_file(refuter, tmp_path):
    # A malformed line after the Nth measured row would raise if the reader went past N.
    rows = write_rows(tmp_path / 'rows.jsonl', 64, trailing='this is not json\n')
    counts = refuter.census(rows, 64)
    assert counts['measured'] == 64
    assert refuter.verdict(counts) == ('SUPPORTED', 0)
    with pytest.raises(json.JSONDecodeError):
        refuter.census(rows, 65)


def test_row_count_must_exceed_the_structural_allowance(refuter, tmp_path):
    rows = write_rows(tmp_path / 'rows.jsonl', 10)
    for bad in (2, 0, -1, 2.5, '10'):
        with pytest.raises(ValueError):
            refuter.census(rows, bad)
