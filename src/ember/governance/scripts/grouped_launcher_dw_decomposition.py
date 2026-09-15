#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Cycle 28, second leg: separate the two things the dW comparison changed at once.

THE CONFOUND THIS EXISTS TO REMOVE. The arm's dW leg found the production partition FASTER than
the single-group one -- 175.5 us against 186.9 us, ratio 0.939, on a floor of 0.33 us -- while
writing four [1024,3072] slabs instead of one. But moving from G=1 to G=4 on that kernel changes
TWO things simultaneously, and the arm cannot tell them apart:

  (a) the GRID. _weights launches on (cdiv(k,64), cdiv(n,128), groups): 16 x 24 x 1 = 384
      programs at G=1 against 1,536 at G=4, on a card with 128 SMs. G=1 may simply be
      occupancy-limited.
  (b) the CHUNK LOOP. NC is a constexpr equal to the per-group chunk count, so the arm ran NC=16
      at G=1 (sixteen 256-row chunks in one group) against NC=4 at G=4 (four per group). Those
      are different kernel specializations with different inner-loop trip counts.

A 2x2 over G in {1,4} and NC in {4,16} separates them. The two off-diagonal cells are timing
probes and nothing else: G=1 with NC=4 reduces four 1,024-row chunks, and G=4 with NC=16 reduces
sixteen 64-row chunks per group. Both are legal chunk-end matrices and neither is production's
chunking, so their dW VALUES are not production's values and no numerical claim is made from
them -- only their durations are read.

This leg does not touch cycle 28's frozen criterion, which is the FORWARD alone. dW was declared
measured-but-not-under-the-criterion at predict time, and this sharpens that secondary
measurement rather than changing what would refute the hypothesis.
"""
import argparse
import io
import itertools
import json
import os
import sys
import time

_SIBLING_SCRIPTS = os.path.dirname(os.path.abspath(__file__))
if _SIBLING_SCRIPTS not in sys.path:
    sys.path.insert(0, _SIBLING_SCRIPTS)

import grouped_launcher_geometry_arm as arm  # noqa: E402

SCHEMA = 'ember-1945-grouped-launcher-dw-decomposition-v1'
CELLS = ('g1_nc16', 'g1_nc4', 'g4_nc4', 'g4_nc16')


def chunk_ends(groups, chunks_per_group, rows):
    """Relative cumulative chunk ends, groups x chunks_per_group, over an equal row split."""
    per_group = rows // groups
    width = per_group // chunks_per_group
    if per_group * groups != rows or width * chunks_per_group != per_group:
        raise arm.Refuse('CHUNKS_DO_NOT_PARTITION',
                         '%d rows into %d groups of %d chunks' % (rows, groups, chunks_per_group))
    return [[width * (c + 1) for c in range(chunks_per_group)] for _ in range(groups)]


def run(args):
    import torch
    import triton

    sys.path.insert(0, os.path.join(args.root, 'src'))
    kernel_path = os.path.join(args.root, arm.KERNEL_REL).replace('\\', '/')
    kernel_sha, _ = arm.read_kernel_source(kernel_path, args.expect_kernel_sha256)
    from ember.model import ember_v0_grouped_capture as api

    cap = arm.check_device(torch.cuda.is_available(), torch.cuda.device_count(),
                           torch.cuda.get_device_capability(0) if torch.cuda.is_available()
                           else None)
    torch.set_num_threads(2)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False

    operand_sha = arm.pin_operand(args.operands, args.expect_operand_sha256)
    data = torch.load(args.operands, map_location='cpu', weights_only=True)
    name, record = arm.select_site(data, args.rows, args.operands)
    weight, gate, down = [v.cuda() for v in record['weights']]
    xs, ds = [], []
    for chunk in record['chunks']:
        x0, dy = chunk['input'].cuda(), chunk['upstream'].cuda()
        d0 = dy.mm(down) * torch.nn.functional.silu(torch.nn.functional.linear(x0, gate))
        assert torch.equal(d0.T.mm(x0), chunk['reference_gradients'][0].cuda()), \
            'saved upstream reconstruction differs'
        xs.append(x0)
        ds.append(d0)
        del dy
    x = torch.cat(xs).contiguous()
    d = torch.cat(ds).contiguous()
    del xs, ds, gate, down
    torch.cuda.empty_cache()

    m, k = x.shape
    n = weight.shape[0]

    def build(groups, nc):
        b = weight.T.unsqueeze(0).repeat(groups, 1, 1).contiguous()
        off = torch.tensor([(i + 1) * (m // groups) for i in range(groups)],
                           device='cuda', dtype=torch.int32)
        ends = torch.tensor(chunk_ends(groups, nc, m), device='cuda',
                            dtype=torch.int32).contiguous()
        return {'b': b, 'offsets': off, 'ends': ends, 'groups': groups, 'nc': nc,
                'db': torch.empty((groups, k, n), device='cuda', dtype=b.dtype)}

    cfg = {'g1_nc16': build(1, 16), 'g1_nc4': build(1, 4),
           'g4_nc4': build(4, 4), 'g4_nc16': build(4, 16)}

    def dw_of(c):
        api._weights[(triton.cdiv(k, arm.BM), triton.cdiv(n, arm.BN), c['groups'])](
            x, d, c['offsets'], c['db'], c['ends'], k, n, *x.stride(), *d.stride(),
            BM=arm.BM, BN=arm.BN, BK=arm.BK, NC=c['nc'], num_warps=arm.NUM_WARPS)
        return c['db']

    def time_calls(fn):
        for _ in range(arm.WARM):
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

    samples = dict((c, []) for c in CELLS)
    orders = list(itertools.permutations(CELLS))
    t0 = time.time()
    for r in range(args.rounds):
        for cell in orders[r % len(orders)]:
            samples[cell].append(time_calls(lambda: dw_of(cfg[cell])))
    wall = time.time() - t0

    s = dict((c, arm.stats(samples[c])) for c in CELLS)
    med = dict((c, s[c]['median']) for c in CELLS)
    receipt = {
        'schema': SCHEMA,
        'hypothesis': args.hypothesis,
        'generated_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'claim': 'Duration of the grouped backward weight kernel across a 2x2 of group count and '
                 'per-group chunk count, on saved operands. The two off-diagonal cells use chunk '
                 'boundaries production does not use and their dW VALUES are not production '
                 'values; only durations are read. No training update, no applied position, no '
                 'governed step, no qualification.',
        'applied_positions': 0,
        'optimizer_updates': 0,
        'site': name,
        'geometry': {'M': m, 'K': k, 'N': n, 'dtype': 'bfloat16'},
        'configurations': dict(
            (c, {'groups': cfg[c]['groups'], 'NC': cfg[c]['nc'],
                 'offsets': [int(v) for v in cfg[c]['offsets'].tolist()],
                 'group_partition': [m // cfg[c]['groups']] * cfg[c]['groups'],
                 'chunk_ends': [[int(v) for v in row] for row in cfg[c]['ends'].tolist()],
                 'weight_gradient_shape': list(cfg[c]['db'].shape),
                 'weights_grid': [-(-k // arm.BM), -(-n // arm.BN), cfg[c]['groups']],
                 'production_chunking': c in ('g4_nc4',),
                 'arm_chunking': c in ('g1_nc16',)})
            for c in CELLS),
        'per_call_us': s,
        'raw_per_round_us': samples,
        'decomposition': {
            'total_g4nc4_minus_g1nc16': med['g4_nc4'] - med['g1_nc16'],
            'grid_term_at_nc4': med['g4_nc4'] - med['g1_nc4'],
            'grid_term_at_nc16': med['g4_nc16'] - med['g1_nc16'],
            'chunkloop_term_at_g1': med['g1_nc4'] - med['g1_nc16'],
            'chunkloop_term_at_g4': med['g4_nc4'] - med['g4_nc16'],
            'interaction': ((med['g4_nc4'] - med['g1_nc4'])
                            - (med['g4_nc16'] - med['g1_nc16'])),
            'note': 'Each term is a median difference in us/call. The grid term holds NC fixed '
                    'and moves G; the chunk-loop term holds G fixed and moves NC. A large '
                    'interaction means the two do not separate additively and the decomposition '
                    'reports that rather than hiding it.',
        },
        'protocol': {'rounds': args.rounds, 'calls_per_round': args.calls,
                     'warmup_calls': arm.WARM,
                     'order': 'round-robin over all 24 permutations of the four cells',
                     'timer': 'torch.cuda.Event pair around `calls` back-to-back launches'},
        'binding': {'kernel_module': kernel_path, 'kernel_sha256': kernel_sha,
                    'operands': args.operands, 'operand_sha256': operand_sha,
                    'torch': torch.__version__, 'triton': triton.__version__,
                    'cuda': torch.version.cuda,
                    'device': torch.cuda.get_device_name(0), 'capability': list(cap)},
        'wall_seconds': wall,
    }
    return receipt


def build_parser():
    """The instrument's arguments, reachable without running the measurement.

    Split out of main() so the defaults -- above all which checkout the measured kernel is read
    from -- can be asserted by a test rather than taken on trust.
    """
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--root', default=arm.DEFAULT_ROOT)
    ap.add_argument('--operands', required=True,
                    help='path to the saved-operand file whose sha256 is arm.OPERAND_SHA256')
    ap.add_argument('--expect-operand-sha256', default=arm.OPERAND_SHA256)
    ap.add_argument('--expect-kernel-sha256', default=None)
    ap.add_argument('--rows', type=int, default=arm.M_TARGET)
    ap.add_argument('--rounds', type=int, default=arm.ROUNDS)
    ap.add_argument('--calls', type=int, default=arm.CALLS)
    ap.add_argument('--hypothesis', default='the-empty-program-slot-is-free-bf16-grouped-rows-'
                                            'at-g4-costs-what-g1-costs-20260915')
    ap.add_argument('--out', default=None)
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        receipt = run(args)
    except arm.Refuse as r:
        sys.stderr.write('REFUSED %s\n' % r)
        if args.out:
            io.open(args.out, 'w', encoding='utf-8', newline='').write(json.dumps(
                {'schema': SCHEMA, 'refused': r.token, 'detail': r.detail}, indent=1))
        return 2
    if args.out:
        io.open(args.out, 'w', encoding='utf-8', newline='').write(
            json.dumps(receipt, indent=1, sort_keys=True))
    for c in CELLS:
        print('%-9s med %8.3f us  (G=%d NC=%2d)'
              % (c, receipt['per_call_us'][c]['median'], receipt['configurations'][c]['groups'],
                 receipt['configurations'][c]['NC']))
    dc = receipt['decomposition']
    for key in ('total_g4nc4_minus_g1nc16', 'grid_term_at_nc4', 'grid_term_at_nc16',
                'chunkloop_term_at_g1', 'chunkloop_term_at_g4', 'interaction'):
        print('%-26s %+8.3f us' % (key, dc[key]))
    print('wall %.1f s -> %s' % (receipt['wall_seconds'], args.out))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
