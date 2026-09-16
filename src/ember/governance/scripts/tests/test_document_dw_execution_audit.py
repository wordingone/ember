# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""CPU tests for the measurement contract; not GPU/kernel validation."""
import importlib.util
import itertools
import math
import sys
from pathlib import Path

import pytest
import torch

PATH = Path(__file__).resolve().parents[1] / 'document_dw_execution_audit.py'


def load():
    assert PATH.is_file(), 'the execution-audit instrument is not implemented'
    spec = importlib.util.spec_from_file_location('document_dw_audit_tested', PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_instrument_exists():
    load()


def test_permutations_balance_labels_in_every_position():
    a = load()
    assert len(a.ORDERS) == 24
    assert set(a.ORDERS) == set(itertools.permutations(a.LABELS))
    for position in range(4):
        for label in a.LABELS:
            assert sum(order[position] == label for order in a.ORDERS) == 6


def test_frozen_sample_set_contains_only_six_qo_and_twelve_shared():
    a = load()
    assert len(a.EXPECTED_SITES) == 18
    assert sum('.attention.' in n for n in a.EXPECTED_SITES) == 6
    assert not any('.attention.k.' in n or '.attention.v.' in n for n in a.EXPECTED_SITES)
    assert len(set(a.EXPECTED_SITES)) == 18


def test_descending_pack_does_not_reverse_rows_within_documents():
    a = load()
    x = torch.arange(16).reshape(8, 2)
    y = x + 100
    px, py = a.pack_descending(torch, x, y, (2, 2, 2, 2))
    assert torch.equal(px, x[[6, 7, 4, 5, 2, 3, 0, 1]])
    assert torch.equal(py, y[[6, 7, 4, 5, 2, 3, 0, 1]])
    assert torch.equal(x, torch.arange(16).reshape(8, 2))


def test_inclusive_arm_rebuilds_from_changed_original_input():
    a = load()
    x = torch.arange(16, dtype=torch.float32).reshape(8, 2)
    y = torch.ones(8, 3)
    lengths = (2, 2, 2, 2)
    def reduction(values, upstream, lengths, order, dtype=None):
        assert order == 'descending'
        total = None
        for i in (3, 2, 1, 0):
            part = upstream[i*2:(i+1)*2].T @ values[i*2:(i+1)*2]
            total = part if total is None else total + part
        return total
    def launch(dy, values):
        total = None
        for i in range(4):
            part = dy[i*2:(i+1)*2].T @ values[i*2:(i+1)*2]
            total = part if total is None else total + part
        return total
    case = a.Case('case', x, y, reduction(x, y, lengths, 'descending'), 'test')
    arms, packed_upstream = a.make_arms(torch, case, reduction, launch, lengths)
    original = arms['kernel_only']().clone()
    assert torch.equal(arms['inclusive'](), original)
    y.zero_()
    assert torch.count_nonzero(arms['inclusive']()) == 0
    assert torch.count_nonzero(arms['reference_a']()) == 0
    assert torch.equal(arms['kernel_only'](), original)  # intentionally stale: diagnostic only
    assert torch.count_nonzero(packed_upstream) != 0


def test_bitwise_check_distinguishes_signed_zero():
    a = load()
    plus = torch.tensor([0.0], dtype=torch.bfloat16)
    minus = torch.tensor([-0.0], dtype=torch.bfloat16)
    assert torch.equal(plus, minus)  # numerical equality is NOT a byte comparison
    result = a.compare_bits(torch, plus, minus)
    assert result['finite']
    assert not result['bitwise_equal']
    assert result['unequal_bits_elements'] == 1


@pytest.mark.parametrize('value', [float('nan'), float('inf'), -float('inf')])
def test_nonfinite_output_fails(value):
    a = load()
    t = torch.tensor([value], dtype=torch.bfloat16)
    assert not a.compare_bits(torch, t, t)['bitwise_equal']


def test_shape_mismatch_refuses():
    a = load()
    with pytest.raises(a.Refusal, match='TENSOR_SCHEMA'):
        a.compare_bits(torch, torch.zeros(2, dtype=torch.bfloat16), torch.zeros(3, dtype=torch.bfloat16))


def sample_rows(a, ref=100.0, candidate=90.0, control=100.0):
    return {name: {'all_checks_pass': True,
                   'timing': {'graph': {
                       'reference_a': {'median_us': ref},
                       'reference_b': {'median_us': control},
                       'kernel_only': {'median_us': candidate/2},
                       'inclusive': {'median_us': candidate}}}}
            for name in a.EXPECTED_SITES}


def test_success_uses_inclusive_graph_not_fast_kernel_only():
    a = load()
    rows = sample_rows(a, candidate=120)
    assert a.adjudicate(rows)['status'] == 'NO_PROGRESSABLE_NET_GAIN'
    assert a.adjudicate(sample_rows(a))['status'] == 'PROCEED_TO_BLOCK_TEST'


def test_no_empty_or_subset_success():
    a = load()
    for rows in ({}, dict(list(sample_rows(a).items())[:-1])):
        with pytest.raises(a.Refusal, match='SITE_SET'):
            a.adjudicate(rows)


def test_one_inexact_site_blocks_progression():
    a = load()
    rows = sample_rows(a)
    rows[a.EXPECTED_SITES[0]]['all_checks_pass'] = False
    assert a.adjudicate(rows)['status'] == 'NUMERICAL_OR_REPLAY_FAILURE'


def test_baseline_disagreement_blocks_spurious_gain():
    a = load()
    assert a.adjudicate(sample_rows(a, candidate=90, control=70))['status'] == 'NO_PROGRESSABLE_NET_GAIN'


def test_one_large_site_regression_blocks_progression():
    a = load()
    rows = sample_rows(a, candidate=70)
    rows[a.EXPECTED_SITES[0]]['timing']['graph']['inclusive']['median_us'] = 103
    assert a.adjudicate(rows)['status'] == 'NO_PROGRESSABLE_NET_GAIN'


@pytest.mark.parametrize('bad', [0.0, -1.0, float('inf'), float('nan')])
def test_invalid_timings_refuse(bad):
    a = load()
    rows = sample_rows(a)
    rows[a.EXPECTED_SITES[0]]['timing']['graph']['inclusive']['median_us'] = bad
    with pytest.raises(a.Refusal, match='TIMING'):
        a.adjudicate(rows)


def test_summary_rejects_missing_rounds():
    a = load()
    with pytest.raises(a.Refusal, match='SAMPLE_COUNT'):
        a.summarize([1.0] * 23)


def test_receipt_creation_refuses_overwrite(tmp_path):
    a = load()
    path = tmp_path / 'receipt.json'
    a.write_new_json(path, {'original': True})
    with pytest.raises(FileExistsError):
        a.write_new_json(path, {'original': False})
    assert 'true' in path.read_text()


def test_json_writer_rejects_nan(tmp_path):
    a = load()
    with pytest.raises(ValueError):
        a.write_new_json(tmp_path / 'bad.json', {'bad': float('nan')})
    assert not (tmp_path / 'bad.json').exists()


def test_shared_replay_collects_internal_operands_and_weight_gradients():
    a = load()
    torch.manual_seed(1)
    lengths = (2, 2, 2, 2)
    layer = 'layers.0.shared'
    record = {'weights': [torch.randn(5, 3, dtype=torch.float64),
                          torch.randn(5, 3, dtype=torch.float64),
                          torch.randn(3, 5, dtype=torch.float64)],
              'chunks': [{'input': torch.randn(2, 3, dtype=torch.float64),
                          'upstream': torch.randn(2, 3, dtype=torch.float64)} for _ in range(4)]}
    # This CPU double exercises orchestration; GPU runtime imports the real CIADecoder methods.
    class DecoderDouble:
        def _document_linear(self, values, name, sizes):
            assert sizes == lengths
            return torch.nn.functional.linear(values, self._weight(name))
        def _document_swiglu(self, values, prefix, sizes):
            up = self._document_linear(values, prefix + '.up.weight', sizes)
            gate = self._document_linear(values, prefix + '.gate.weight', sizes)
            return self._document_linear(torch.nn.functional.silu(gate) * up,
                                         prefix + '.down.weight', sizes)
    cases = a.shared_cases(torch, record, layer, DecoderDouble, torch.device('cpu'), lengths)
    assert len(cases) == 3
    assert [c.name for c in cases] == [layer + '.' + p + '.weight' for p in ('up', 'gate', 'down')]
    for c in cases:
        gradient = c.upstream.T @ c.values
        torch.testing.assert_close(gradient, c.expected, rtol=1e-12, atol=1e-12)
        assert not c.values.requires_grad and not c.upstream.requires_grad
    assert cases[0].values.data_ptr() == cases[1].values.data_ptr()
    assert cases[2].values.shape == (8, 5)


def source_fixture(tmp_path, monkeypatch, *, stored_newline=b'\n'):
    import subprocess
    a = load()
    # This is a disposable repository, not the user's Ember checkout. Isolate its
    # fixture commits from user hooks/signing and make stored line endings explicit.
    hooks = tmp_path / 'empty-hooks'
    hooks.mkdir()
    def git(*args):
        return subprocess.run(
            ['git', '-C', str(tmp_path), '-c', 'core.autocrlf=false',
             '-c', 'core.safecrlf=false', '-c', 'core.hooksPath=' + str(hooks),
             '-c', 'commit.gpgsign=false', *args],
            check=True, capture_output=True, text=True, timeout=5).stdout.strip()
    git('init')
    (tmp_path / '.gitattributes').write_bytes(b'*.py -text\n')
    (tmp_path / 'audit.py').write_bytes(b'# frozen instrument' + stored_newline)
    (tmp_path / 'reference.py').write_bytes(b'# pinned reference' + stored_newline)
    git('add', '.gitattributes', 'audit.py', 'reference.py')
    git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
        'commit', '-m', 'test fixture')
    head = git('rev-parse', 'HEAD')
    blob = git('rev-parse', 'HEAD:reference.py')
    monkeypatch.setattr(a, 'BASE', head)
    monkeypatch.setattr(a, 'PINNED_BLOBS', {'reference.py': blob})
    monkeypatch.setattr(a, '__file__', str(tmp_path / 'audit.py'))
    return a, head, git


@pytest.mark.parametrize('stored_newline', [b'\n', b'\r\n'], ids=['stored-lf', 'stored-crlf'])
def test_source_binding_accepts_exact_commit(tmp_path, monkeypatch, stored_newline):
    a, head, git = source_fixture(tmp_path, monkeypatch, stored_newline=stored_newline)
    import hashlib
    raw = (tmp_path / 'reference.py').read_bytes()
    assert raw == b'# pinned reference' + stored_newline
    # Prove actual working bytes equal the committed blob, with no newline conversion.
    digest = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
    assert digest == git('rev-parse', 'HEAD:reference.py')
    result = a.verify_source(tmp_path, head)
    assert set(result) == {'reference.py', 'audit.py'}
    assert result['reference.py']['working_sha256'] == hashlib.sha256(raw).hexdigest()


def test_source_binding_accepts_crlf_checkout_of_lf_commit(tmp_path, monkeypatch):
    a, _, git = source_fixture(tmp_path, monkeypatch)
    (tmp_path / '.gitattributes').write_bytes(b'*.py text eol=crlf\n')
    git('add', '.gitattributes')
    git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
        'commit', '-m', 'declare CRLF checkout for LF blobs')
    head = git('rev-parse', 'HEAD')
    for name in ('audit.py', 'reference.py'):
        (tmp_path / name).unlink()
    git('checkout', '--', 'audit.py', 'reference.py')
    assert (tmp_path / 'reference.py').read_bytes() == b'# pinned reference\r\n'
    assert git('diff', '--name-only') == ''
    assert set(a.verify_source(tmp_path, head)) == {'reference.py', 'audit.py'}


@pytest.mark.parametrize('stored_newline', [b'\n', b'\r\n'], ids=['stored-lf', 'stored-crlf'])
def test_source_binding_rejects_changed_bytes_when_git_diff_is_silent(
        tmp_path, monkeypatch, stored_newline):
    a, head, git = source_fixture(tmp_path, monkeypatch, stored_newline=stored_newline)
    git('update-index', '--assume-unchanged', 'reference.py')
    (tmp_path / 'reference.py').write_bytes(b'# altered reference' + stored_newline)
    assert git('diff', '--name-only') == ''
    assert git('diff', '--cached', '--name-only') == ''
    with pytest.raises(a.Refusal, match='working bytes differ from commit: reference.py'):
        a.verify_source(tmp_path, head)


def test_source_binding_rejects_added_bom_when_git_diff_is_silent(tmp_path, monkeypatch):
    a, head, git = source_fixture(tmp_path, monkeypatch)
    git('update-index', '--assume-unchanged', 'reference.py')
    (tmp_path / 'reference.py').write_bytes(b'\xef\xbb\xbf# pinned reference\n')
    assert git('diff', '--name-only') == ''
    with pytest.raises(a.Refusal, match='working bytes differ from commit: reference.py'):
        a.verify_source(tmp_path, head)


def test_source_binding_rejects_changed_instrument_when_git_diff_is_silent(tmp_path, monkeypatch):
    a, head, git = source_fixture(tmp_path, monkeypatch)
    git('update-index', '--assume-unchanged', 'audit.py')
    (tmp_path / 'audit.py').write_bytes(b'# changed instrument\n')
    assert git('diff', '--name-only') == ''
    with pytest.raises(a.Refusal, match='working bytes differ from commit: audit.py'):
        a.verify_source(tmp_path, head)


def test_source_binding_rejects_staged_change(tmp_path, monkeypatch):
    a, head, git = source_fixture(tmp_path, monkeypatch)
    (tmp_path / 'reference.py').write_bytes(b'# staged replacement\n')
    git('add', 'reference.py')
    assert git('diff', '--name-only') == ''
    with pytest.raises(a.Refusal, match='tracked changes are not frozen'):
        a.verify_source(tmp_path, head)


def test_source_binding_rejects_dirty_file(tmp_path, monkeypatch):
    a, head, _ = source_fixture(tmp_path, monkeypatch)
    (tmp_path / 'reference.py').write_text('# changed after freeze\n')
    with pytest.raises(a.Refusal, match='SOURCE_IDENTITY'):
        a.verify_source(tmp_path, head)


def test_source_binding_rejects_wrong_commit(tmp_path, monkeypatch):
    a, head, _ = source_fixture(tmp_path, monkeypatch)
    with pytest.raises(a.Refusal, match='SOURCE_IDENTITY'):
        a.verify_source(tmp_path, '0' * 40)


def test_source_binding_rejects_committed_dependency_change(tmp_path, monkeypatch):
    a, head, git = source_fixture(tmp_path, monkeypatch)
    (tmp_path / 'reference.py').write_text('# changed dependency\n')
    git('add', 'reference.py')
    git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-m', 'change')
    with pytest.raises(a.Refusal, match='audited dependency changed'):
        a.verify_source(tmp_path, git('rev-parse', 'HEAD'))


def test_finite_large_bf16_error_has_finite_diagnostic():
    a = load()
    plus = torch.tensor([1e38], dtype=torch.bfloat16)
    minus = -plus
    result = a.compare_bits(torch, plus, minus)
    assert result['finite'] and not result['bitwise_equal']
    assert math.isfinite(result['relative_l2'])
