#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""#1945 measurement repair: charge repacking and compare captured execution.

Not a new kernel, trainer change, or qualification run. The old receipts stay
unchanged. See docs/domains/lab/research/document-dw-execution-audit-v1.md.
All GPU work requires Ember's existing GPU lock and an owned finite launcher.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import itertools
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass

SCHEMA = 'ember-1945-document-dw-execution-audit-v1'
BASE = '12019f093543016ce1cda4256df6b8908f647684'
OPERAND_SHA256 = 'e49ad84192da8f1f82b759e9360cba18b39eca2a716550048b08d2aa1197dc76'
LENGTHS = (1024, 1024, 1024, 1024)
SHARED_LAYERS = (0, 2, 13, 22)
EXPECTED_SITES = tuple(
    [f'layers.{i}.attention.{p}.weight' for i in (1, 2, 3) for p in ('q', 'o')]
    + [f'layers.{i}.shared.{p}.weight' for i in SHARED_LAYERS for p in ('up', 'gate', 'down')]
)
LABELS = ('reference_a', 'reference_b', 'kernel_only', 'inclusive')
ORDERS = tuple(itertools.permutations(LABELS))
ROUNDS, CALLS, WARM = 24, 16, 3
MIN_TIME_REDUCTION = 0.05
MAX_SITE_REGRESSION = 0.02
GIB = 1024 ** 3
PINNED_BLOBS = {
    'src/ember/model/ember_v0_document_reduction.py': '09e7d61dea81157cd2b4fa5ea7506651ad0f3cfd',
    'src/ember/model/ember_v0_grouped_capture.py': '51533246368eadb02db02423ecfd12d1e7228747',
    'src/ember/model/ember_v0_decoder.py': 'cfab6301484ea44aafd847d61ca234c23b700634',
    'src/ember/governance/scripts/gpu_lock_guard.py': 'fb947cfbfb1cc182040898d5b1d9c27af576e4e7',
    'src/ember/governance/scripts/owned_process.py': '42610c9362b3384cfa8c0a134dadbbe68c0fc8f5',
}


class Refusal(RuntimeError):
    pass


@dataclass
class Case:
    name: str
    values: object
    upstream: object
    expected: object
    reference_origin: str


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def write_new_json(path, value):
    # Serialize before creating the file: invalid floats must not leave a false receipt.
    text = json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n'
    with Path(path).open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())


def git(root, *args):
    result = subprocess.run(['git', '-C', str(root), *args], capture_output=True,
                            text=True, timeout=15, check=False)
    if result.returncode:
        raise Refusal('SOURCE_IDENTITY: ' + result.stderr.strip())
    return result.stdout.strip()


def verify_source(root, expected_commit):
    if len(expected_commit) != 40 or any(c not in '0123456789abcdef' for c in expected_commit):
        raise Refusal('SOURCE_IDENTITY: supply the complete lowercase commit SHA')
    if git(root, 'rev-parse', 'HEAD') != expected_commit:
        raise Refusal('SOURCE_IDENTITY: HEAD does not match --expect-commit')
    git(root, 'merge-base', '--is-ancestor', BASE, 'HEAD')
    if git(root, 'diff', '--name-only') or git(root, 'diff', '--cached', '--name-only'):
        raise Refusal('SOURCE_IDENTITY: tracked changes are not frozen')
    hashes = {}
    script = Path(__file__).resolve().relative_to(root).as_posix()
    paths = list(PINNED_BLOBS) + [script]
    for rel in paths:
        blob = git(root, 'rev-parse', 'HEAD:' + rel)
        if rel in PINNED_BLOBS and blob != PINNED_BLOBS[rel]:
            raise Refusal('SOURCE_IDENTITY: audited dependency changed: ' + rel)
        raw = (root / rel).read_bytes()
        # A committed blob may itself contain CRLF. Exact working bytes must pass
        # before applying the existing CRLF-checkout -> LF-blob allowance.
        current_blob = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
        if current_blob != blob:
            normalized = raw.replace(b'\r\n', b'\n')
            normalized_blob = hashlib.sha1(
                b'blob ' + str(len(normalized)).encode() + b'\0' + normalized).hexdigest()
            if normalized_blob != blob:
                raise Refusal('SOURCE_IDENTITY: working bytes differ from commit: ' + rel)
        hashes[rel] = {'git_blob': blob, 'working_sha256': hashlib.sha256(raw).hexdigest()}
    return hashes


def pack_descending(torch, values, upstream, lengths):
    # Both copies are inside the inclusive candidate's timed/captured callable.
    return (torch.cat(tuple(reversed(values.split(lengths, dim=0))), dim=0),
            torch.cat(tuple(reversed(upstream.split(lengths, dim=0))), dim=0))


def make_arms(torch, case, reduction, launch, lengths=LENGTHS):
    packed_values, packed_upstream = pack_descending(torch, case.values, case.upstream, lengths)

    def reference():
        return reduction(case.values, case.upstream, lengths, 'descending', dtype=case.values.dtype)

    def kernel_only():
        return launch(packed_upstream, packed_values)

    def inclusive():
        values, upstream = pack_descending(torch, case.values, case.upstream, lengths)
        return launch(upstream, values)

    return {'reference_a': reference, 'reference_b': reference,
            'kernel_only': kernel_only, 'inclusive': inclusive}, packed_upstream


def compare_bits(torch, actual, expected):
    if (actual.shape != expected.shape or actual.dtype != expected.dtype
            or actual.dtype != torch.bfloat16):
        raise Refusal('TENSOR_SCHEMA: BF16 tensors of the same shape are required')
    finite = bool(torch.isfinite(actual).all() & torch.isfinite(expected).all())
    # torch.equal on floats considers +0 and -0 equal. Compare stored BF16 bits instead.
    unequal = int(torch.count_nonzero(actual.contiguous().view(torch.int16)
                                     != expected.contiguous().view(torch.int16)))
    # Diagnostics use FP64 outside timing so finite BF16 inputs cannot overflow the norm.
    delta = actual.double() - expected.double()
    relative = (float(delta.norm()) / max(float(expected.double().norm()), 1e-30)) if finite else None
    return {'finite': finite, 'bitwise_equal': finite and unequal == 0,
            'unequal_bits_elements': unequal, 'relative_l2': relative}


def summarize(samples):
    if len(samples) != ROUNDS:
        raise Refusal('SAMPLE_COUNT: every label requires exactly 24 rounds')
    if any(not isinstance(x, (int, float)) or not math.isfinite(x) or x <= 0 for x in samples):
        raise Refusal('TIMING: every duration must be positive and finite')
    return {'n': len(samples), 'median_us': statistics.median(samples),
            'min_us': min(samples), 'max_us': max(samples), 'mean_us': statistics.fmean(samples)}


def adjudicate(rows):
    if set(rows) != set(EXPECTED_SITES):
        raise Refusal('SITE_SET: exactly the preregistered 18 cases are required')
    ref, cand, disagreement = 0.0, 0.0, 0.0
    worst_ratio = 0.0
    for name in EXPECTED_SITES:
        graph = rows[name]['timing']['graph']
        r, c, control = [graph[k]['median_us'] for k in ('reference_a', 'inclusive', 'reference_b')]
        if any(not math.isfinite(x) or x <= 0 for x in (r, c, control)):
            raise Refusal('TIMING: invalid graph duration')
        ref += r
        cand += c
        disagreement += abs(r - control)
        worst_ratio = max(worst_ratio, c / r)
    exact = all(rows[name]['all_checks_pass'] for name in EXPECTED_SITES)
    reduction = 1 - cand / ref
    eligible = (exact and reduction >= MIN_TIME_REDUCTION and
                ref - cand > disagreement and worst_ratio <= 1 + MAX_SITE_REGRESSION)
    status = ('NUMERICAL_OR_REPLAY_FAILURE' if not exact else
              'PROCEED_TO_BLOCK_TEST' if eligible else 'NO_PROGRESSABLE_NET_GAIN')
    return {'status': status, 'all_18_checks_pass': exact,
            'sample_call_sum_reference_us': ref, 'sample_call_sum_inclusive_us': cand,
            'sample_call_sum_speedup': ref / cand, 'sample_time_reduction_fraction': reduction,
            'baseline_duplicate_abs_difference_sum_us': disagreement,
            'worst_inclusive_over_reference_ratio': worst_ratio,
            'interpretation': 'Sum of 18 sampled call medians, NOT a training-step estimate. '
                              'Duplicate-baseline difference is a diagnostic, not a confidence interval.'}


def validate_case(torch, case):
    x, dy, expected = case.values, case.upstream, case.expected
    if (x.ndim != 2 or dy.ndim != 2 or x.shape[0] != sum(LENGTHS) or dy.shape[0] != sum(LENGTHS)
            or expected.shape != (dy.shape[1], x.shape[1])
            or any(t.dtype != torch.bfloat16 for t in (x, dy, expected))
            or any(t.device != x.device for t in (dy, expected))
            or not x.is_cuda):
        raise Refusal('CASE_SCHEMA: invalid saved/reconstructed subject: ' + case.name)
    if not all(bool(torch.isfinite(t).all()) for t in (x, dy, expected)):
        raise Refusal('CASE_NONFINITE: ' + case.name)
    if not bool(torch.count_nonzero(expected)):
        raise Refusal('CASE_ZERO_REFERENCE: liveness check would be vacuous: ' + case.name)


def shared_cases(torch, record, layer, decoder_cls, device, lengths=LENGTHS):
    """Reuse the decoder's real shared method; let autograd produce its internal operands.

    Only local block replay on saved input. No complete model is constructed.
    Expected gradients come from current-source local replay, not a newly loaded R1 snapshot.
    """
    names = tuple(layer + '.' + p + '.weight' for p in ('up', 'gate', 'down'))
    weights = [w.detach().to(device).requires_grad_(True) for w in record['weights']]
    x = torch.cat([c['input'].to(device) for c in record['chunks']], dim=0).requires_grad_(True)
    dy = torch.cat([c['upstream'].to(device) for c in record['chunks']], dim=0)

    class Adapter:
        _DOCUMENT_REDUCTION_ORDER = 'descending'
        def __init__(self):
            self.weights, self.seen = dict(zip(names, weights)), {}
        def _weight(self, name):
            return self.weights[name]
        def _document_linear(self, values, name, sizes):
            output = decoder_cls._document_linear(self, values, name, sizes)
            self.seen[name] = (values, output)
            return output

    with torch.enable_grad():
        adapter = Adapter()
        output = decoder_cls._document_swiglu(adapter, x, layer, lengths)
        intermediates = tuple(adapter.seen[name][1] for name in names)
        gradients = torch.autograd.grad(output, intermediates + tuple(weights), grad_outputs=dy)
    return [Case(name, adapter.seen[name][0].detach(), gradients[i].detach(),
                 gradients[i + 3].detach(), 'current-source merged shared-block replay on saved inputs')
            for i, name in enumerate(names)]


def cases_from_data(torch, data, decoder_cls):
    if set(data.get('shared', {})) != {f'layers.{i}.shared' for i in SHARED_LAYERS}:
        raise Refusal('SITE_SET: shared operand subjects differ from the frozen set')
    device = torch.device('cuda:0')
    for name in EXPECTED_SITES[:6]:
        record = data['attention'][name]
        if len(record['chunks']) != 4:
            raise Refusal('DOCUMENTS: ' + name)
        for c in record['chunks']:
            if c['input'].shape[0] != 1024 or c['upstream'].shape[0] != 1024:
                raise Refusal('DOCUMENT_LENGTH: ' + name)
        yield Case(name,
                   torch.cat([c['input'].to(device) for c in record['chunks']], dim=0),
                   torch.cat([c['upstream'].to(device) for c in record['chunks']], dim=0),
                   record['actual_gradient'].to(device),
                   'saved actual attention gradient; ascending merged input reconstructed from saved documents')
    for i in SHARED_LAYERS:
        layer = f'layers.{i}.shared'
        record = data['shared'][layer]
        shapes = [(2048, 1024), (2048, 1024), (1024, 2048)]
        if (len(record['chunks']) != 4 or [tuple(w.shape) for w in record['weights']] != shapes
                or any(tuple(c[k].shape) != (1024, 1024)
                       for c in record['chunks'] for k in ('input', 'upstream'))):
            raise Refusal('SHARED_SCHEMA: ' + layer)
        yield from shared_cases(torch, record, layer, decoder_cls, device)


def capture(torch, fn):
    stream = torch.cuda.Stream()
    stream.wait_stream(torch.cuda.current_stream())
    with torch.cuda.stream(stream):
        for _ in range(WARM):
            output = fn()
    torch.cuda.current_stream().wait_stream(stream)
    torch.cuda.synchronize()
    graph = torch.cuda.CUDAGraph()
    with torch.cuda.graph(graph):
        for _ in range(CALLS):
            output = fn()
    graph.replay()
    torch.cuda.synchronize()
    return graph, output  # retain output and graph-private storage together


def measure(torch, arms, graphs, mode):
    samples = {label: [] for label in LABELS}
    start, end = torch.cuda.Event(enable_timing=True), torch.cuda.Event(enable_timing=True)
    for order in ORDERS:
        for label in order:
            for _ in range(WARM):
                if mode == 'graph':
                    graphs[label][0].replay()
                else:
                    arms[label]()
            torch.cuda.synchronize()
            start.record()
            if mode == 'graph':
                graphs[label][0].replay()  # one launch containing CALLS repetitions
            else:
                for _ in range(CALLS):
                    arms[label]()
            end.record()
            end.synchronize()
            samples[label].append(start.elapsed_time(end) * 1000.0 / CALLS)
    return {label: summarize(samples[label]) for label in LABELS}, samples


def audit_case(torch, triton, grouped, reduction, case):
    validate_case(torch, case)
    k, n = case.upstream.shape[1], case.values.shape[1]
    offsets = torch.tensor([4096], device=case.values.device, dtype=torch.int32)
    ends = torch.tensor([[1024, 2048, 3072, 4096]], device=case.values.device, dtype=torch.int32)

    def launch(upstream, values):
        # Allocation belongs to the callable for BOTH paths. No preallocated-output advantage.
        out = torch.empty((1, k, n), device=values.device, dtype=torch.bfloat16)
        grouped._weights[(triton.cdiv(k, 64), triton.cdiv(n, 128), 1)](
            upstream, values, offsets, out, ends, k, n, *upstream.stride(), *values.stride(),
            BM=64, BN=128, BK=32, NC=4, num_warps=4)
        return out[0]

    with torch.no_grad():
        arms, packed_upstream = make_arms(torch, case, reduction, launch)
        checks = {'eager': {name: compare_bits(torch, fn(), case.expected) for name, fn in arms.items()}}
        # Refuse a drifting baseline; a wrong candidate is retained as a negative result.
        if not checks['eager']['reference_a']['bitwise_equal']:
            raise Refusal('BASELINE_DRIFT: ' + case.name)
        graphs = {label: capture(torch, arms[label]) for label in LABELS}
        checks['graph'] = {label: compare_bits(torch, value[1], case.expected)
                           for label, value in graphs.items()}
        # A graph that accidentally captured stale/precomputed values must fail.
        saved = case.upstream.clone()
        saved_packed = packed_upstream.clone()
        case.upstream.zero_()
        packed_upstream.zero_()
        liveness = {}
        for label, (graph, output) in graphs.items():
            graph.replay()
            torch.cuda.synchronize()
            liveness[label] = bool(torch.isfinite(output).all()) and int(torch.count_nonzero(output)) == 0
        case.upstream.copy_(saved)
        packed_upstream.copy_(saved_packed)
        restored = {}
        for label, (graph, output) in graphs.items():
            graph.replay()
            torch.cuda.synchronize()
            restored[label] = compare_bits(torch, output, case.expected)
        del saved, saved_packed
        checks['restored_graph'] = restored
        checks['changed_upstream_zero_replay'] = liveness

        timing, raw = {}, {}
        # Fixed ordering, not a post-result choice. Eager is diagnostic; graph is primary.
        for mode in ('eager', 'graph'):
            timing[mode], raw[mode] = measure(torch, arms, graphs, mode)
        post = {}
        for label, (graph, output) in graphs.items():
            graph.replay()
            torch.cuda.synchronize()
            post[label] = compare_bits(torch, output, case.expected)
        checks['post_timing_graph'] = post
        all_pass = all(liveness.values()) and all(
            row['bitwise_equal'] for section in ('eager', 'graph', 'restored_graph', 'post_timing_graph')
            for row in checks[section].values())
        peak = int(torch.cuda.max_memory_allocated())
        torch.cuda.synchronize()
        del graphs, arms
    return {'reference_origin': case.reference_origin,
            'layout_scope': 'sampled local replay; not proof of every live-trainer stride or invocation',
            'geometry': {'documents': list(LENGTHS), 'values_shape': list(case.values.shape),
                         'upstream_shape': list(case.upstream.shape),
                         'values_stride': list(case.values.stride()),
                         'upstream_stride': list(case.upstream.stride()),
                         'values_storage_offset': case.values.storage_offset(),
                         'upstream_storage_offset': case.upstream.storage_offset()},
            'all_checks_pass': all_pass, 'checks': checks, 'timing': timing,
            'raw_per_round_us': raw, 'peak_allocated_bytes_cumulative': peak}


def execute(args, root, output, report):
    os.environ['TRITON_CACHE_DIR'] = str(output / 'cache' / 'triton')
    os.environ['CUDA_CACHE_PATH'] = str(output / 'cache' / 'cuda')
    os.environ['TORCHINDUCTOR_CACHE_DIR'] = str(output / 'cache' / 'inductor')
    temp = output / 'cache' / 'tmp'
    temp.mkdir(parents=True)
    os.environ['TEMP'] = os.environ['TMP'] = str(temp)
    sys.path.insert(0, str(root / 'src'))
    sys.path.insert(0, str(root / 'src/ember/governance/scripts'))
    import gpu_lock_guard
    if not os.environ.get('EMBER_GPU_LOCK_PATH', '').strip():
        raise Refusal('GPU_LOCK_UNCONFIGURED: use the existing shared lock; do not invent a new lock path')
    with gpu_lock_guard.acquire(script=Path(__file__).name):
        import torch
        import triton
        from ember.model import ember_v0_document_reduction as production
        from ember.model import ember_v0_grouped_capture as grouped
        from ember.model import ember_v0_decoder as decoder
        for module, rel in ((production, 'src/ember/model/ember_v0_document_reduction.py'),
                            (grouped, 'src/ember/model/ember_v0_grouped_capture.py'),
                            (decoder, 'src/ember/model/ember_v0_decoder.py')):
            if Path(module.__file__).resolve() != (root / rel).resolve():
                raise Refusal('IMPORT_IDENTITY: wrong checkout imported for ' + rel)
        if (torch.__version__ != '2.10.0+cu126' or triton.__version__ != '3.5.0'
                or torch.version.cuda != '12.6'):
            raise Refusal('ENVIRONMENT: match the earlier receipts: torch 2.10.0+cu126, Triton 3.5.0, CUDA 12.6')
        if (not torch.cuda.is_available() or torch.cuda.device_count() != 1
                or torch.cuda.get_device_capability(0) != (8, 9)
                or 'RTX 4090' not in torch.cuda.get_device_name(0)):
            raise Refusal('DEVICE: exactly one visible RTX 4090 is required')
        free, total = torch.cuda.mem_get_info()
        if free < 6 * GIB:
            raise Refusal('HEADROOM: less than 6 GiB free; do not retry by relaxing the budget')
        torch.cuda.set_per_process_memory_fraction(4 * GIB / total, 0)
        torch.set_num_threads(2)
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
        compiler = decoder.bind_triton_c_compiler()
        report['environment'] = {'torch': torch.__version__, 'triton': triton.__version__,
                                 'cuda': torch.version.cuda, 'device': torch.cuda.get_device_name(0),
                                 'gpu_lock': gpu_lock_guard.LOCK_PATH, 'compiler': compiler,
                                 'allocator_cap_bytes': 4 * GIB,
                                 'allow_bf16_reduced_precision_reduction':
                                     torch.backends.cuda.matmul.allow_bf16_reduced_precision_reduction}
        observed = sha256_file(args.operands)
        if observed != OPERAND_SHA256:
            raise Refusal('OPERAND_IDENTITY: operand SHA256 differs')
        report['operand_sha256'] = observed
        data = torch.load(args.operands, map_location='cpu', weights_only=True)
        for case in cases_from_data(torch, data, decoder.CIADecoder):
            row = audit_case(torch, triton, grouped, production.reduce_weight_gradient, case)
            report['sites'][case.name] = row
            write_new_json(output / (case.name + '.json'), row)
            graph = row['timing']['graph']
            ratio = graph['reference_a']['median_us'] / graph['inclusive']['median_us']
            print(f'{case.name:40} checks={row["all_checks_pass"]!s:5} '
                  f'graph-inclusive={ratio:.4f}x', flush=True)
            del case
            torch.cuda.empty_cache()
    return adjudicate(report['sites'])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[4])
    parser.add_argument('--expect-commit', required=True)
    parser.add_argument('--operands', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args(argv)
    root = args.root.resolve(strict=True)
    hashes = verify_source(root, args.expect_commit)
    output = args.output_dir.resolve()
    if os.name != 'nt' or output.drive.upper() != 'B:':
        raise Refusal('PLATFORM_CUSTODY: this run is frozen to native Windows and new B: custody')
    output.mkdir(parents=False, exist_ok=False)
    report = {'schema': SCHEMA, 'source_commit': args.expect_commit, 'source_files': hashes,
              'operands': str(args.operands), 'sites': {}, 'applied_positions': 0, 'optimizer_updates': 0,
              'claim': 'Sampled reduction audit only. No production integration, step-speed, '
                       'learning, model-admission, or #1945 terminal credit.',
              'protocol': {'rounds': ROUNDS, 'calls_per_sample': CALLS, 'warmup': WARM,
                           'labels': list(LABELS), 'orders': [list(o) for o in ORDERS],
                           'primary': 'graph inclusive vs graph reference_a',
                           'graph_capture': '16 repeated complete calls in each label-specific graph; private pools',
                           'eager': 'diagnostic only; events include possible host submission gaps',
                           'frozen_sites': list(EXPECTED_SITES),
                           'minimum_sample_time_reduction': MIN_TIME_REDUCTION,
                           'maximum_sample_site_regression': MAX_SITE_REGRESSION,
                           'require_gain_above_duplicate_baseline_difference': True}}
    write_new_json(output / 'plan.json', report)
    started = time.time()
    try:
        verdict = execute(args, root, output, report)
        if verify_source(root, args.expect_commit) != hashes:
            raise Refusal('SOURCE_IDENTITY: source changed during execution')
        report['verdict'] = verdict
        report['status'] = 'COMPLETED'
        exit_code = 0 if verdict['status'] == 'PROCEED_TO_BLOCK_TEST' else 2
    except BaseException as error:
        report['status'] = 'REFUSED_OR_INTERRUPTED'
        report['error'] = {'type': type(error).__name__, 'message': str(error)}
        exit_code = 2
    report['elapsed_wall_seconds'] = time.time() - started
    report['finished_utc'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    write_new_json(output / 'result.json', report)
    print(json.dumps(report.get('verdict', report.get('error')), indent=2, allow_nan=False))
    print('receipt:', output / 'result.json')
    return exit_code


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Refusal as exc:
        print('REFUSED:', exc, file=sys.stderr)
        raise SystemExit(2)
