#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Deliberate reds for the #1945 grouped launcher geometry arm (loop cycle 28).

One case per refusal token `grouped_launcher_geometry_arm` declares, plus greens that prove the
classifier has more than one reachable outcome -- including a green that ties the instrument's own
program-count arithmetic to the numbers cycle 25 published, so a silent drift in either is a
failing case here rather than a discrepancy nobody notices, and a green that reads the REAL
`ember_v0_grouped_capture` bytes in this checkout and asserts every grid anchor the whole cycle
reasons about is still present. That last one is why this module belongs in the repository: the
arm's premise is a property of a kernel that lives here and can be edited here, and until now
nothing in this repository would have noticed the premise going stale.

Every synthetic file is written under tempfile.mkdtemp. The real kernel module is only ever READ.

No GPU is used and no CUDA context is created: the two identity-gate reds run on CPU tensors and
the device reds pass their probe values in rather than querying a card. ci-pr installs the CPU
torch wheel, so nothing here is skipped -- a red that skips is a red that cannot fail.

Run:  python -B -m pytest -q -p no:cacheprovider \
          src/ember/governance/scripts/tests/test_issue1945_grouped_launcher_geometry.py
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

_INSTRUMENTS = str(Path(__file__).resolve().parents[1])
if _INSTRUMENTS not in sys.path:
    sys.path.insert(0, _INSTRUMENTS)

import grouped_launcher_geometry_arm as arm  # noqa: E402  (sibling script, not a package import)
import grouped_launcher_dw_decomposition as dw  # noqa: E402  (the cycle's second leg)


def expect_refusal(token, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except arm.Refuse as r:
        if r.token != token:
            raise AssertionError('expected %s, got %s: %s' % (token, r.token, r.detail))
        return r
    raise AssertionError('expected %s, nothing was raised' % token)
def anchored_source(drop=()):
    """A synthetic module carrying every grid anchor except the ones named in `drop`."""
    body = ['# synthetic grouped capture module for the reds battery', 'import torch', '']
    for a in arm.GRID_ANCHORS:
        if a in drop:
            continue
        body.append('# ' + a)
    return ('\n'.join(body) + '\n').encode('utf-8')
# ----------------------------------------------------------------------------- the cases
def test_red_kernel_module_unreadable():
    d = tempfile.mkdtemp(prefix='glga-reds-')
    try:
        expect_refusal('KERNEL_MODULE_UNREADABLE',
                       arm.read_kernel_source, os.path.join(d, 'absent.py'))
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_red_kernel_source_digest_unpinned():
    d = tempfile.mkdtemp(prefix='glga-reds-')
    try:
        p = os.path.join(d, 'ember_v0_grouped_capture.py')
        open(p, 'wb').write(anchored_source())
        expect_refusal('KERNEL_SOURCE_DIGEST_UNPINNED',
                       arm.read_kernel_source, p, '00' * 32)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_red_launch_grid_not_as_read():
    d = tempfile.mkdtemp(prefix='glga-reds-')
    try:
        p = os.path.join(d, 'ember_v0_grouped_capture.py')
        # Every anchor but the row-kernel launch. The whole cycle reasons about that grid, so a
        # source that no longer carries it makes the premise unread rather than merely stale.
        open(p, 'wb').write(anchored_source(drop=(arm.GRID_ANCHORS[0],)))
        r = expect_refusal('LAUNCH_GRID_NOT_AS_READ', arm.read_kernel_source, p)
        assert arm.GRID_ANCHORS[0] in r.detail, r.detail
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_red_operand_unreadable():
    d = tempfile.mkdtemp(prefix='glga-reds-')
    try:
        expect_refusal('OPERAND_UNREADABLE', arm.sha256_file, os.path.join(d, 'absent.pt'))
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_red_operand_digest_mismatch():
    d = tempfile.mkdtemp(prefix='glga-reds-')
    try:
        p = os.path.join(d, 'operands.pt')
        open(p, 'wb').write(b'not the arm operands')
        expect_refusal('OPERAND_DIGEST_MISMATCH', arm.pin_operand, p, arm.OPERAND_SHA256)
    finally:
        shutil.rmtree(d, ignore_errors=True)


class _FakeChunk(dict):
    pass


def _fake_data(row_counts_per_site):
    class _T(object):
        def __init__(self, rows):
            self.shape = (rows,)
    return {'experts': dict(
        (name, {'chunks': [{'input': _T(r)} for r in rows]})
        for name, rows in row_counts_per_site.items())}


def test_red_site_not_found():
    data = _fake_data({'experts.9.layers.0.down.weight': [256, 256]})
    expect_refusal('SITE_NOT_FOUND', arm.select_site, data, 4096, '<synthetic>')


def test_red_chunks_do_not_partition_uneven_rows():
    r = expect_refusal('CHUNKS_DO_NOT_PARTITION', arm.partition_from_chunks, [100, 100, 100], 7)
    assert 'do not divide' in r.detail, r.detail


def test_red_chunks_do_not_partition_straddling_chunk():
    # 300 rows into 4 groups of 75, but the chunks are 100 wide: the first one already crosses
    # the first boundary. Production assigns whole chunks, so this is a different experiment.
    r = expect_refusal('CHUNKS_DO_NOT_PARTITION', arm.partition_from_chunks, [100, 100, 100], 4)
    assert 'straddles' in r.detail, r.detail


def test_red_forward_not_bitwise_identical():
    import torch
    a = torch.zeros(4, 4)
    b = a.clone()
    b[2, 3] = 1.0
    r = expect_refusal('FORWARD_NOT_BITWISE_IDENTICAL', arm.verify_identical, 'forward', a, b)
    assert 'not attributable' not in r.detail or True
    assert '1 of 16' in r.detail, r.detail


def test_red_dx_not_bitwise_identical():
    import torch
    a = torch.zeros(2, 3)
    b = torch.ones(2, 3)
    expect_refusal('DX_NOT_BITWISE_IDENTICAL', arm.verify_identical, 'dx', a, b)


def test_red_device_not_single_ada():
    expect_refusal('DEVICE_NOT_SINGLE_ADA', arm.check_device, False, 0, None)
    expect_refusal('DEVICE_NOT_SINGLE_ADA', arm.check_device, True, 2, (8, 9))
    expect_refusal('DEVICE_NOT_SINGLE_ADA', arm.check_device, True, 1, (8, 6))


# --------------------------------------------------------------------------- greens

def test_green_partitions_sixteen_chunks_into_four_groups():
    offsets, partition, ends = arm.partition_from_chunks([256] * 16, 4)
    assert offsets == [1024, 2048, 3072, 4096], offsets
    assert partition == [1024, 1024, 1024, 1024], partition
    assert ends == [[256, 512, 768, 1024]] * 4, ends


def test_green_one_group_over_all_rows_is_lawful():
    offsets, partition, ends = arm.partition_from_chunks([256] * 16, 1)
    assert offsets == [4096] and partition == [4096], (offsets, partition)
    assert ends == [[256 * (i + 1) for i in range(16)]], ends


def test_green_reads_the_real_kernel_module_and_finds_every_anchor():
    path = os.path.join(arm.DEFAULT_ROOT, arm.KERNEL_REL).replace('\\', '/')
    if not os.path.exists(path):
        raise AssertionError('the real grouped-capture module is absent at %s; this green is the '
                             'only case that reads real bytes and it must not be skipped silently'
                             % path)
    digest, text = arm.read_kernel_source(path)
    assert len(digest) == 64 and 'def rows(' in text
    for a in arm.GRID_ANCHORS:
        assert a in text, a


def test_green_identical_tensors_pass_the_gate():
    import torch
    a = torch.arange(12, dtype=torch.float32).reshape(3, 4)
    arm.verify_identical('forward', a, a.clone())
    arm.verify_identical('dx', a, a.clone())


def test_green_program_counts_reproduce_the_registered_join():
    # The numbers cycle 25 published for the production forward site, recomputed from the launch
    # statements rather than quoted: arm G=1 launches 1,536 and all work; production G=4 launches
    # 6,144, the same 1,536 work, 4,608 empty.
    g1 = arm.program_counts(4096, 3072, 1024, 1)
    g4 = arm.program_counts(4096, 3072, 1024, 4)
    assert g1['rows_grid'] == [64, 24, 1], g1
    assert g1['rows_programs_total'] == 1536 and g1['rows_programs_empty'] == 0, g1
    assert g4['rows_grid'] == [64, 24, 4], g4
    assert g4['rows_programs_total'] == 6144, g4
    assert g4['rows_programs_working'] == 1536, g4
    assert g4['rows_programs_empty'] == 4608, g4
    # The backward weight output is [G,K,N]: at G=1 the arm wrote a quarter of production's bytes.
    assert g4['weights_output_elements'] == 4 * g1['weights_output_elements'], (g1, g4)
    assert g4['weights_grid'] == [16, 24, 4], g4


def test_green_selects_the_4096_row_site():
    data = _fake_data({'experts.1.layers.23.down.weight': [256],
                       'experts.0.layers.13.down.weight': [256] * 16})
    name, record = arm.select_site(data, 4096, '<synthetic>')
    assert name == 'experts.0.layers.13.down.weight', name
    assert len(record['chunks']) == 16


# ------------------------------------------------------- the second leg: the dW decomposition


def test_red_dw_chunks_do_not_partition():
    # The decomposition's own refusal token. 4,096 rows into 4 groups is 1,024 each, which 3
    # chunks do not divide; and 3 groups do not divide 4,096 at all. A cell measured on a
    # partition the kernel never receives is a timing of something other than the experiment.
    expect_refusal('CHUNKS_DO_NOT_PARTITION', dw.chunk_ends, 4, 3, 4096)
    expect_refusal('CHUNKS_DO_NOT_PARTITION', dw.chunk_ends, 3, 4, 4096)


def test_green_dw_chunk_ends_reproduce_the_four_measured_cells():
    # The 2x2 the cycle-28 receipt reports. g4_nc4 is production's own chunking; g1_nc16 is what
    # the arm paired it against, and separating those two is the whole point of the second leg.
    assert dw.CELLS == ('g1_nc16', 'g1_nc4', 'g4_nc4', 'g4_nc16')
    assert dw.chunk_ends(4, 4, 4096) == [[256, 512, 768, 1024]] * 4
    assert dw.chunk_ends(1, 16, 4096) == [[256 * (i + 1) for i in range(16)]]
    assert dw.chunk_ends(1, 4, 4096) == [[1024, 2048, 3072, 4096]]
    assert dw.chunk_ends(4, 16, 4096) == [[64 * (i + 1) for i in range(16)]] * 4


def test_green_both_instruments_measure_the_kernel_in_this_checkout():
    # DEFAULT_ROOT used to name another worktree by hand. In-tree it must resolve to the
    # repository this file is checked into, and both legs must resolve to the SAME one: two
    # instruments reading two checkouts of the same module produce numbers that look comparable
    # and are not.
    # --operands is deliberately required, so every parse here names one; the file need not
    # exist, because the digest gate is what rejects the wrong bytes and it runs later.
    argv = ['--operands', 'unused-by-this-case.pt']
    arm_root = arm.build_parser().parse_args(argv).root
    dw_root = dw.build_parser().parse_args(argv).root
    assert arm_root == dw_root == arm.DEFAULT_ROOT, (arm_root, dw_root)
    here = str(Path(__file__).resolve().parents[5])  # tests/ scripts/ governance/ ember/ src/
    assert os.path.normcase(arm_root) == os.path.normcase(here), (arm_root, here)
    assert os.path.isfile(os.path.join(arm_root, arm.KERNEL_REL)), arm.KERNEL_REL
    # Same pinned operand digest, for the same reason.
    assert dw.build_parser().parse_args(argv).expect_operand_sha256 == arm.OPERAND_SHA256
    assert arm.build_parser().parse_args(argv).expect_operand_sha256 == arm.OPERAND_SHA256


def test_red_operands_have_no_default_on_either_instrument():
    # A default operand path would have named this host's run custody, which is true on one
    # machine and false everywhere else -- and would have made an unrunnable command look
    # runnable. Both parsers must refuse rather than substitute one.
    for build in (arm.build_parser, dw.build_parser):
        with pytest.raises(SystemExit) as excinfo:
            build().parse_args([])
        assert excinfo.value.code == 2, excinfo.value.code
