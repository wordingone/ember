#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Loop cycle 28: price the empty program slot in the BF16 grouped launcher.

WHAT THIS MEASURES. The production forward grouped-expert site runs [4096,1024] x [4,1024,3072]
at G=4. The only arm this campaign has ever measured against it ran G=1 over all 4,096 rows
(cycle 25's correction, `the-fp8-arm-ran-ONE-group-not-sixteen-the-lengths-field-is-not-the-
partition-20260914`). rows() launches on grid (cdiv(m,64), cdiv(n,128), groups) and every group
re-walks the FULL row count, so at G=4 the same 1,536 units of work are launched as 6,144
programs and 4,608 of them exist only to fail `if first < end:`. That cycle registered the cost
of an empty program as unpriced, with no ceiling, no sign and no arm. This is the arm.

WHY IT IS A VALIDITY REPAIR AND NOT A TREATMENT. It removes no work and can lower no governed
number, so it has NO ceiling against the 0.0512 s terminal and would be refused by
1945-multiplicative-movement-only clause 1 if it were read as a treatment. What it buys is the
BF16 denominator at the group structure production actually runs: the campaign's only FP8 ratio
(1.0597x at the kernel level) is a ratio against a BF16 native measured at G=1, and if that
denominator moves at G=4 the ratio moves for a reason unrelated to FP8.

WHY THE COMPARISON IS CLEAN. The saved operand carries one [1024,3072] weight and 4,096 rows of
one expert in sixteen 256-row chunks -- which is production's own chunk structure, so four groups
of 1,024 rows is four whole chunks per group with no chunk split. Replicating the weight into
four distinct contiguous slabs gives every row the same weight it had at G=1, and the group
offsets are all multiples of BM=64, so the row tiles and the K loop order are unchanged and only
the program that owns each tile differs. The forward and dX results at G=4 must therefore be
BITWISE EQUAL to G=1, and the run REFUSES if they are not: non-identity means the two
configurations did not compute the same arithmetic and no timing difference between them is
attributable to geometry. dW is deliberately not under that check -- at G=4 it writes four
[K,N] slabs against one, which is 4x the store traffic and is exactly production's shape.

THE NOISE FLOOR IS MEASURED AT THE CLAIM'S OWN SAMPLE SIZE. Each leg times four labels -- g1,
g1_control, g4, g4_control -- where each control is an independently built tensor set of
identical geometry. The floor is the control difference at the same round count as the claim, and
it is reported beside the claim rather than assumed.

ROUND-ROBIN OVER ALL 24 ORDER PERMUTATIONS. A replication needs the harness context held
constant, and a label measured always-first or always-last is measured with different neighbours.
Every label occupies every position across the 24 rounds exactly six times.

THE RECEIPT EMITS ITS OWN OFFSETS VECTOR for every configuration, which is the obligation cycle
25 registered verbatim and the field the seat's production_group_partition.py reads
through receipt_partition().

Refusals: KERNEL_MODULE_UNREADABLE, KERNEL_SOURCE_DIGEST_UNPINNED, LAUNCH_GRID_NOT_AS_READ,
OPERAND_UNREADABLE, OPERAND_DIGEST_MISMATCH, SITE_NOT_FOUND, CHUNKS_DO_NOT_PARTITION,
FORWARD_NOT_BITWISE_IDENTICAL, DX_NOT_BITWISE_IDENTICAL, DEVICE_NOT_SINGLE_ADA. Nine tokens, one
deliberate red each. Two further checks -- that the offsets end at the row count and that every
round completed -- are implied by the loops that build them, so they are internal assertions
rather than tokens: a refusal no input can reach is a check that cannot change state.
"""
import argparse
import hashlib
import io
import itertools
import json
import os
import statistics
import sys
import time
from pathlib import Path

SCHEMA = 'ember-1945-grouped-launcher-geometry-arm-v1'

KERNEL_REL = 'src/ember/model/ember_v0_grouped_capture.py'
#: The repository this file is checked into. The instrument reads the kernel's own bytes and pins
#: their digest into the receipt, so it must resolve the module it will actually import rather than
#: a path someone typed: a measurement bound to a different checkout of the same file is a
#: measurement of nothing. `--root` still overrides it, for measuring another worktree's head.
DEFAULT_ROOT = str(Path(__file__).resolve().parents[4])

# The arm's own binding.json pins these. A mismatch means the bytes this cycle measured are not
# the bytes the 1.0597x ratio was measured against, and the denominator claim does not transfer.
OPERAND_SHA256 = 'e49ad84192da8f1f82b759e9360cba18b39eca2a716550048b08d2aa1197dc76'

# Anchored substrings of the launch statements whose geometry this whole cycle reasons about.
# If the source no longer contains them, the premise is not merely stale -- it is unread.
GRID_ANCHORS = (
    '_rows[(triton.cdiv(m, 64), triton.cdiv(n, 128), groups)]',
    'first = start + tl.program_id(0) * BM',
    'if first < end:',
    "_weights[(triton.cdiv(k, 64), triton.cdiv(n, 128), b.shape[0])]",
    'db = torch.empty(b.shape, device=b.device, dtype=b.dtype)',
)

BM = 64
BN = 128
BK = 32
NUM_WARPS = 4

M_TARGET = 4096
GROUPS = 4
ROUNDS = 24
CALLS = 16
WARM = 3

LABELS = ('g1', 'g1_control', 'g4', 'g4_control')


class Refuse(Exception):
    def __init__(self, token, detail):
        Exception.__init__(self, '%s: %s' % (token, detail))
        self.token = token
        self.detail = detail


def sha256_file(path):
    h = hashlib.sha256()
    try:
        with io.open(path, 'rb') as f:
            for chunk in iter(lambda: f.read(8 << 20), b''):
                h.update(chunk)
    except OSError as e:
        raise Refuse('OPERAND_UNREADABLE', '%s: %s' % (path, e))
    return h.hexdigest()


def read_kernel_source(path, expect_sha=None):
    """Read the grouped-capture module, pin it, and prove the grid statements are still there."""
    try:
        raw = io.open(path, 'rb').read()
    except OSError as e:
        raise Refuse('KERNEL_MODULE_UNREADABLE', '%s: %s' % (path, e))
    digest = hashlib.sha256(raw).hexdigest()
    if expect_sha and digest != expect_sha:
        raise Refuse('KERNEL_SOURCE_DIGEST_UNPINNED',
                     '%s is %s against the expected %s; the launch geometry this cycle reasons '
                     'about was read from different bytes' % (path, digest, expect_sha))
    text = raw.decode('utf-8', 'replace')
    missing = [a for a in GRID_ANCHORS if a not in text]
    if missing:
        raise Refuse('LAUNCH_GRID_NOT_AS_READ',
                     '%s lacks %d anchored launch statement(s): %s'
                     % (path, len(missing), ' | '.join(missing)))
    return digest, text


def partition_from_chunks(lengths, groups):
    """Split whole chunks into `groups` equal-row groups, the way production assigns them.

    Returns (offsets, group_partition, per_group_relative_chunk_ends). Refuses rather than
    splitting a chunk or balancing approximately: an unequal or chunk-splitting partition is a
    different experiment and this cycle is not measuring it.
    """
    total = sum(lengths)
    if groups <= 0 or total <= 0:
        raise Refuse('CHUNKS_DO_NOT_PARTITION', 'groups %r over %d rows' % (groups, total))
    if total % groups:
        raise Refuse('CHUNKS_DO_NOT_PARTITION',
                     '%d rows do not divide into %d equal groups' % (total, groups))
    per = total // groups
    offsets = []
    partition = []
    ends = []
    acc = 0
    cur = []
    for length in lengths:
        if length <= 0:
            raise Refuse('CHUNKS_DO_NOT_PARTITION', 'non-positive chunk length %r' % (length,))
        start = len(offsets) * per
        if acc + length > start + per:
            raise Refuse('CHUNKS_DO_NOT_PARTITION',
                         'a chunk of %d rows beginning at row %d straddles the group boundary '
                         'at row %d; production assigns whole chunks and a split chunk is a '
                         'different experiment' % (length, acc, start + per))
        acc += length
        cur.append(acc - start)
        if acc == start + per:
            ends.append(cur)
            offsets.append(acc)
            partition.append(per)
            cur = []
    if cur:
        raise Refuse('CHUNKS_DO_NOT_PARTITION',
                     'chunks left over after %d groups: %r' % (len(offsets), cur))
    if len(offsets) != groups:
        raise Refuse('CHUNKS_DO_NOT_PARTITION',
                     'chunks formed %d groups, not %d' % (len(offsets), groups))
    assert offsets[-1] == total and sum(partition) == total, 'partitioner invariant'
    width = max(len(e) for e in ends)
    ends = [e + [e[-1]] * (width - len(e)) for e in ends]
    return offsets, partition, ends


def verify_identical(name, a, b):
    """Bitwise equality of two tensors, or a refusal naming which leg broke."""
    token = ('FORWARD_NOT_BITWISE_IDENTICAL' if name == 'forward'
             else 'DX_NOT_BITWISE_IDENTICAL')
    if tuple(a.shape) != tuple(b.shape):
        raise Refuse(token, '%s shapes %r against %r' % (name, tuple(a.shape), tuple(b.shape)))
    import torch
    if not bool(torch.equal(a, b)):
        diff = (a.float() - b.float())
        raise Refuse(token,
                     '%s at G=%d is not bitwise equal to G=1: %d of %d elements differ, '
                     'max abs %g. The two configurations did not compute the same arithmetic, so '
                     'no timing difference between them is attributable to launcher geometry.'
                     % (name, GROUPS, int(torch.count_nonzero(diff)), a.numel(),
                        float(diff.abs().max())))


def pin_operand(path, expect):
    """Digest the operand file against the arm's own binding, or refuse."""
    digest = sha256_file(path)
    if expect and digest != expect:
        raise Refuse('OPERAND_DIGEST_MISMATCH',
                     '%s is %s against the expected %s; these are not the bytes the FP8 arm '
                     'measured, so its BF16 denominator does not transfer to this cycle'
                     % (path, digest, expect))
    return digest


def select_site(data, rows, where='<operands>'):
    """The saved expert site with exactly `rows` rows across its chunks, or a refusal."""
    for name, record in (data.get('experts') or {}).items():
        total = sum(c['input'].shape[0] for c in (record.get('chunks') or []))
        if total == rows:
            return name, record
    raise Refuse('SITE_NOT_FOUND',
                 'no saved expert site with %d rows in %s' % (rows, where))


def check_device(available, count, capability):
    """One card, Ada, or a refusal. Split out so the refusal is provable without a card."""
    if not available or count != 1:
        raise Refuse('DEVICE_NOT_SINGLE_ADA',
                     'cuda available %r, device count %r' % (available, count))
    if tuple(capability or ()) != (8, 9):
        raise Refuse('DEVICE_NOT_SINGLE_ADA',
                     'compute capability %r, not Ada (8, 9)' % (capability,))
    return tuple(capability)


def program_counts(m, n, k, groups):
    """Derived, not observed: the grid the source launches at this geometry."""
    cd = lambda x, y: -(-x // y)
    rows_dim0, rows_dim1 = cd(m, BM), cd(n, BN)
    per_group_working = cd(m // groups, BM)
    return {
        'rows_grid': [rows_dim0, rows_dim1, groups],
        'rows_programs_total': rows_dim0 * rows_dim1 * groups,
        'rows_programs_working': per_group_working * rows_dim1 * groups,
        'rows_programs_empty': (rows_dim0 - per_group_working) * rows_dim1 * groups,
        'weights_grid': [cd(k, BM), cd(n, BN), groups],
        'weights_programs_total': cd(k, BM) * cd(n, BN) * groups,
        'weights_output_elements': groups * k * n,
    }


def stats(values):
    v = sorted(values)
    if not v:
        return {}
    def q(p):
        i = min(len(v) - 1, max(0, int(round(p * (len(v) - 1)))))
        return v[i]
    return {'n': len(v), 'median': statistics.median(v), 'p10': q(0.10), 'p90': q(0.90),
            'min': v[0], 'max': v[-1], 'mean': statistics.fmean(v)}


def run(args):
    import torch
    import triton

    sys.path.insert(0, os.path.join(args.root, 'src'))
    kernel_path = os.path.join(args.root, KERNEL_REL).replace('\\', '/')
    kernel_sha, _text = read_kernel_source(kernel_path, args.expect_kernel_sha256)
    from ember.model import ember_v0_grouped_capture as api

    cap = check_device(torch.cuda.is_available(), torch.cuda.device_count(),
                       torch.cuda.get_device_capability(0) if torch.cuda.is_available() else None)

    torch.set_num_threads(2)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False

    operand_sha = pin_operand(args.operands, args.expect_operand_sha256)

    data = torch.load(args.operands, map_location='cpu', weights_only=True)
    name, record = select_site(data, args.rows, args.operands)

    weight, gate, down = [v.cuda() for v in record['weights']]
    xs, ds, lengths = [], [], []
    for chunk in record['chunks']:
        x0, dy = chunk['input'].cuda(), chunk['upstream'].cuda()
        d0 = dy.mm(down) * torch.nn.functional.silu(torch.nn.functional.linear(x0, gate))
        want = chunk['reference_gradients'][0].cuda()
        # The producer's own reconstruction check, reused verbatim rather than trusted.
        assert torch.equal(d0.T.mm(x0), want), 'saved upstream reconstruction differs'
        xs.append(x0)
        ds.append(d0)
        lengths.append(x0.shape[0])
        del dy, want
    x = torch.cat(xs).contiguous()
    d = torch.cat(ds).contiguous()
    del xs, ds, gate, down
    torch.cuda.empty_cache()

    m, k = x.shape
    n = weight.shape[0]
    offsets4, partition4, ends4 = partition_from_chunks(lengths, args.groups)
    cum = []
    acc = 0
    for length in lengths:
        acc += length
        cum.append(acc)

    def build(groups):
        if groups == 1:
            b = weight.T.unsqueeze(0).contiguous()
            off = torch.tensor([m], device='cuda', dtype=torch.int32)
            ends = torch.tensor([cum], device='cuda', dtype=torch.int32).contiguous()
            part = [m]
        else:
            # Four DISTINCT contiguous slabs, not an expand: production holds four real weights
            # and an expanded view would share one slab's cache lines across every group.
            b = weight.T.unsqueeze(0).repeat(groups, 1, 1).contiguous()
            off = torch.tensor(offsets4, device='cuda', dtype=torch.int32)
            ends = torch.tensor(ends4, device='cuda', dtype=torch.int32).contiguous()
            part = list(partition4)
        return {'b': b, 'offsets': off, 'ends': ends, 'partition': part, 'groups': groups}

    cfg = {'g1': build(1), 'g1_control': build(1),
           'g4': build(args.groups), 'g4_control': build(args.groups)}

    def forward_of(c):
        return api.rows(x, c['b'], c['offsets'])

    def dx_of(c):
        return api.rows(d, c['b'].transpose(1, 2), c['offsets'])

    # Preallocated per configuration. An in-loop torch.empty would put a 6 MiB allocation on the
    # G=1 leg against a 24 MiB one on the G=4 leg, which is an allocator asymmetry inside the
    # measurement rather than a launcher one. The forward and dX outputs ARE allocated per call
    # inside rows(), but both configurations allocate the identical [m,n], so that term is common.
    for _c in cfg.values():
        _c['db'] = torch.empty(_c['b'].shape, device=_c['b'].device, dtype=_c['b'].dtype)

    def dw_of(c):
        api._weights[(triton.cdiv(k, BM), triton.cdiv(n, BN), c['groups'])](
            x, d, c['offsets'], c['db'], c['ends'], k, n, *x.stride(), *d.stride(),
            BM=BM, BN=BN, BK=BK, NC=c['ends'].shape[1], num_warps=NUM_WARPS)
        return c['db']

    # ---- identity gate, before a single timing number exists -------------------------------
    y1, y4 = forward_of(cfg['g1']), forward_of(cfg['g4'])
    verify_identical('forward', y4, y1)
    dx1, dx4 = dx_of(cfg['g1']), dx_of(cfg['g4'])
    verify_identical('dx', dx4, dx1)
    dw1, dw4 = dw_of(cfg['g1']), dw_of(cfg['g4'])
    dw_agreement = {
        'g1_shape': list(dw1.shape), 'g4_shape': list(dw4.shape),
        'note': 'dW is NOT under the identity gate: at G=4 the four per-group slabs each round '
                'their own chunk accumulations, so their sum equals the G=1 slab only up to the '
                'BF16 accumulation boundaries the kernel deliberately preserves. Reported as a '
                'sanity number, never as a gate.',
        'relative_l2_sum_vs_g1': float(
            (dw4.float().sum(0) - dw1.float()[0]).norm()
            / dw1.float()[0].norm().clamp_min(1e-30)),
    }
    del y1, y4, dx1, dx4, dw1, dw4
    torch.cuda.empty_cache()

    # ---- timing --------------------------------------------------------------------------
    def time_calls(fn):
        for _ in range(WARM):
            fn()
        torch.cuda.synchronize()
        s = torch.cuda.Event(enable_timing=True)
        e = torch.cuda.Event(enable_timing=True)
        s.record()
        for _ in range(args.calls):
            fn()
        e.record()
        torch.cuda.synchronize()
        return s.elapsed_time(e) * 1000.0 / args.calls

    legs = {'forward': forward_of, 'dx': dx_of, 'dw': dw_of}
    samples = dict((leg, dict((lab, []) for lab in LABELS)) for leg in legs)
    orders = list(itertools.permutations(LABELS))
    rounds_done = 0
    t0 = time.time()
    for r in range(args.rounds):
        order = orders[r % len(orders)]
        for leg, fn in legs.items():
            for lab in order:
                samples[leg][lab].append(time_calls(lambda: fn(cfg[lab])))
        rounds_done += 1
    wall = time.time() - t0
    assert rounds_done == args.rounds, 'round loop invariant'

    out_legs = {}
    for leg in legs:
        s = dict((lab, stats(samples[leg][lab])) for lab in LABELS)
        floor_g1 = abs(s['g1']['median'] - s['g1_control']['median'])
        floor_g4 = abs(s['g4']['median'] - s['g4_control']['median'])
        effect = s['g4']['median'] - s['g1']['median']
        out_legs[leg] = {
            'per_call_us': s,
            'raw_per_round_us': dict((lab, samples[leg][lab]) for lab in LABELS),
            'noise_floor_us': {'g1_vs_g1_control': floor_g1, 'g4_vs_g4_control': floor_g4,
                               'larger': max(floor_g1, floor_g4)},
            'effect_us_g4_minus_g1': effect,
            'ratio_g4_over_g1': s['g4']['median'] / s['g1']['median'],
            'effect_exceeds_floor': abs(effect) > max(floor_g1, floor_g4),
        }

    receipt = {
        'schema': SCHEMA,
        'hypothesis': args.hypothesis,
        'generated_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'claim': 'BF16 grouped launcher geometry at the production group partition against the '
                 'single-group partition the only FP8 arm ran, on identical rows and identical '
                 'arithmetic. Descriptive kernel timings on saved operands. No training update, '
                 'no applied position, no governed step, no FP8 measurement, no qualification.',
        'applied_positions': 0,
        'optimizer_updates': 0,
        'site': name,
        'geometry': {'M': m, 'K': k, 'N': n, 'dtype': 'bfloat16',
                     'chunk_row_counts': list(lengths)},
        'configurations': dict(
            (lab, {'groups': cfg[lab]['groups'],
                   'offsets': [int(v) for v in cfg[lab]['offsets'].tolist()],
                   'group_partition': cfg[lab]['partition'],
                   'weight_operand_shape': list(cfg[lab]['b'].shape),
                   'chunk_ends': [[int(v) for v in row]
                                  for row in cfg[lab]['ends'].tolist()],
                   'NC': int(cfg[lab]['ends'].shape[1])})
            for lab in LABELS),
        'derived_program_counts': {
            'g1': program_counts(m, n, k, 1),
            'g4': program_counts(m, n, k, args.groups),
            'note': 'Derived from the launch statements read at this commit, not observed.',
        },
        'identity_gate': {'forward': 'BITWISE EQUAL', 'dx': 'BITWISE EQUAL',
                          'dw': dw_agreement},
        'protocol': {'rounds': args.rounds, 'calls_per_round': args.calls, 'warmup_calls': WARM,
                     'order': 'round-robin over all 24 permutations of the four labels; each '
                              'label occupies each position exactly six times across 24 rounds',
                     'timer': 'torch.cuda.Event pair around `calls` back-to-back launches, '
                              'divided by `calls`; synchronize before and after',
                     'noise_floor': 'the g1-vs-g1_control and g4-vs-g4_control median difference, '
                                    'measured at the same round count as the claim'},
        'legs': out_legs,
        'binding': {'kernel_module': kernel_path, 'kernel_sha256': kernel_sha,
                    'operands': args.operands, 'operand_sha256': operand_sha,
                    'grid_anchors_present': list(GRID_ANCHORS),
                    'torch': torch.__version__, 'triton': triton.__version__,
                    'cuda': torch.version.cuda,
                    'device': torch.cuda.get_device_name(0), 'capability': list(cap)},
        'wall_seconds': wall,
        'not_a_treatment': 'This arm removes no work and can lower no governed number. It has NO '
                           'ceiling against the 0.0512 s/step terminal and is refused by '
                           '1945-multiplicative-movement-only clause 1 if read as a treatment. It '
                           'is a measurement-validity repair on a class whose FP8 coverage is 0.0 '
                           'us/step of 18,068.1.',
    }
    return receipt


def build_parser():
    """The instrument's arguments, reachable without running the measurement.

    Split out of main() so the defaults -- above all which checkout the measured kernel is read
    from -- can be asserted by a test rather than taken on trust.
    """
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--root', default=DEFAULT_ROOT)
    # No default. The saved operands live in a run custody on the measuring host, not in this
    # repository, so any path written here would be true on one machine and a lie everywhere
    # else. What binds instead is the digest below: name the custody, and the instrument
    # refuses unless the bytes there hash to OPERAND_SHA256.
    ap.add_argument('--operands', required=True,
                    help='path to the saved-operand file whose sha256 is OPERAND_SHA256')
    ap.add_argument('--expect-operand-sha256', default=OPERAND_SHA256)
    ap.add_argument('--expect-kernel-sha256', default=None)
    ap.add_argument('--rows', type=int, default=M_TARGET)
    ap.add_argument('--groups', type=int, default=GROUPS)
    ap.add_argument('--rounds', type=int, default=ROUNDS)
    ap.add_argument('--calls', type=int, default=CALLS)
    ap.add_argument('--hypothesis', default='the-empty-program-slot-is-free-bf16-grouped-rows-'
                                            'at-g4-costs-what-g1-costs-20260915')
    ap.add_argument('--out', default=None)
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        receipt = run(args)
    except Refuse as r:
        sys.stderr.write('REFUSED %s\n' % r)
        payload = {'schema': SCHEMA, 'refused': r.token, 'detail': r.detail,
                   'generated_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
        if args.out:
            io.open(args.out, 'w', encoding='utf-8', newline='').write(
                json.dumps(payload, indent=1, sort_keys=True))
        return 2
    if args.out:
        io.open(args.out, 'w', encoding='utf-8', newline='').write(
            json.dumps(receipt, indent=1, sort_keys=True))
    for leg, v in receipt['legs'].items():
        print('%-8s g1 %9.2f us | g4 %9.2f us | effect %+8.2f us | floor %6.2f us | %s'
              % (leg, v['per_call_us']['g1']['median'], v['per_call_us']['g4']['median'],
                 v['effect_us_g4_minus_g1'], v['noise_floor_us']['larger'],
                 'EXCEEDS FLOOR' if v['effect_exceeds_floor'] else 'within floor'))
    print('wall %.1f s -> %s' % (receipt['wall_seconds'], args.out))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
