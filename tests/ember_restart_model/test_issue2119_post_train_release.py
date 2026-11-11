# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""The hour hands back its training-only memory before the end-of-hour verification (#2119; H50 published its child and then died in the
restore verify, 40 GiB job commit with the whole training footprint still charged).

Three things are pinned. (1) The release is real and harmless: `release_training_buffers` collects cyclic garbage that the gated timed loop
left behind, touches CUDA only where torch already initialised it, and `verify_checkpoint_restore` calls it before it reads or restores
anything. (2) `run_hour` drops the capture, the static buffers and the last pack before the verify and reads none of them afterwards. (3)
The release changes no byte: a fixed-seed tiny hour's published child (every object, the optimizer state, the replay state, the manifest)
has the sha256 the PRE-change writer produced (computed on origin/master 7e8b19fa), and the state restored by the verify equals the state
before it bit for bit. The parameter-counter receipt is the one file that moves, and only in its counter_sha256 field (the streaming
counter is a new source file; its previous source is kept in counter-history). CPU only, 26 tiny owners."""
import ast
import gc
import hashlib
import importlib.util
import inspect
import json
import shutil
import sys
import tempfile
import unittest
import warnings
import weakref
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'src/ember/infrastructure/tools/ember-restart-3b'))
with warnings.catch_warnings():
    warnings.filterwarnings('ignore', message='`torch.jit.script_method` is deprecated', category=DeprecationWarning)
    import checkpoint_artifacts as artifacts  # noqa: E402
    import parameter_counter as counter  # noqa: E402
    from ember.model import ember_v0_inventory as cia_inventory, ember_v0_decoder as cia_decoder  # noqa: E402
    from ember.model.ember_v0_contract import cia_architecture_config, validate_cia_architecture  # noqa: E402
    import cia_hour  # noqa: E402
import cia_fp32_master as M  # noqa: E402

ZERO = torch.zeros(())
GIB = 1 << 30
# The sha256 over the decoded tensor content of every .pt the fixed-seed tiny hour publishes (26 model objects, the optimizer state, the replay
# state), in sorted order of their own digests. Computed on the PRE-change tree (origin/master 7e8b19fa) and on this branch: identical. The
# decoded content, not the file bytes, so a torch version that frames its zip differently does not move it.
GOLDEN_TENSOR_DIGEST = 'b597ce056eae5df5c2e2f3a1c24cee8e9e9ed61380c779ebc9441e2871aca9a6'
GOLDEN_TENSOR_FILES = 28


def feed(value, digest):
    if isinstance(value, torch.Tensor):
        digest.update(('T|%s|%s|' % (value.dtype, tuple(value.shape))).encode())
        digest.update(value.detach().contiguous().cpu().reshape(-1).view(torch.uint8).numpy().tobytes())
    elif isinstance(value, dict):
        digest.update(b'D|')
        for key in sorted(value, key=repr):
            digest.update(repr(key).encode())
            feed(value[key], digest)
    elif isinstance(value, (list, tuple)):
        digest.update(b'L|')
        for item in value:
            feed(item, digest)
    else:
        digest.update(('S|%r|' % (value,)).encode())


def tensor_digest(root):
    parts = []
    for path in sorted(Path(root).rglob('*.pt')):
        digest = hashlib.sha256()
        feed(torch.load(path, map_location='cpu', weights_only=True), digest)
        parts.append(digest.hexdigest())
    top = hashlib.sha256()
    for part in sorted(parts):
        top.update(part.encode())
    return len(parts), top.hexdigest()


class Fixture(unittest.TestCase):
    def build(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.custody = Path(self.temp.name) / 'custody'
        self.custody.mkdir()
        self.root = self.custody / 'trained-child'
        self.config_path = Path(self.temp.name) / 'config.json'
        self.config_path.write_text(json.dumps(cia_architecture_config()), encoding='utf-8')
        specs = (cia_inventory.TensorSpec('embedding.weight', (8,), 'core'),) + tuple(
            cia_inventory.TensorSpec(f'experts.{i}.weight', (8,), 'expert', i) for i in range(25))
        self.parameters = {s.name: torch.nn.Parameter(torch.full(s.shape, i, dtype=torch.bfloat16)) for i, s in enumerate(specs)}
        self.model = type('Fixture', (), {'parameter_inventory': lambda _: self.parameters})()
        self.model.config = validate_cia_architecture(cia_architecture_config())
        self.model._cuda_execution = None
        self.optimizer = torch.optim.AdamW(self.parameters.values(), lr=.01, foreach=False, fused=True)
        M.enable(self.optimizer)
        identity = {'param_groups': [{'params': list(self.parameters), 'hyperparameters': {'amsgrad': False}}]}
        for target, attr, kwargs in ((cia_decoder, 'CIADecoder', dict(new=type(self.model))),
                                     (cia_inventory, 'equation_inventory', dict(return_value=specs)),
                                     (artifacts, 'cia_optimizer_identity', dict(return_value=identity)),
                                     # the verified load reads the host commit headroom, a Windows-only probe; the fixture's tiny child
                                     # needs no real headroom, so the Linux wiring runner sees a large fixed value (not under test here)
                                     (artifacts, 'available_host_commit_bytes', dict(return_value=1 << 50))):
            mocking = patch.object(target, attr, **kwargs)
            mocking.start()
            self.addCleanup(mocking.stop)
        for round_ in range(3):
            generator = torch.Generator().manual_seed(40 + round_)
            for p in self.parameters.values():
                p.grad = (torch.randn(p.shape, generator=generator) * 0.1).to(torch.bfloat16)
            for group in self.optimizer.param_groups:
                M.step(self.optimizer, group, [p for p in group['params'] if p.grad is not None], ZERO)
        self.optimizer.zero_grad(set_to_none=True)
        torch.manual_seed(5)
        self.child = artifacts.write_checkpoint_artifacts(
            self.model, self.optimizer, self.root, launch_seed=7,
            rng_state={'cpu': torch.get_rng_state(), 'cuda': torch.empty(0, dtype=torch.uint8)},
            data_cursor={'shard': 'fixture', 'record_index': 0, 'global_step': 0, 'tokens_seen': 0},
            model_config_sha256=hashlib.sha256(self.config_path.read_bytes()).hexdigest(), contract_sha256='2' * 64,
            expert_genesis_sha256={}, max_serialized_bytes=4 * 1024 * 1024, max_transient_scratch_bytes=1024 * 1024,
            pre_publish_verifier=self.verifier)

    def verifier(self, candidate, receipt):
        result = counter.execute_counter(model_config=self.config_path, checkpoint_manifest=candidate / 'checkpoint-manifest.json',
                                         active_expert='all')
        (candidate / 'parameter-counter-receipt.json').write_text(json.dumps(result), encoding='utf-8')
        return result

    def snapshot(self):
        masters = M.masters(self.optimizer)
        return dict(weights={n: p.detach().clone() for n, p in self.parameters.items()},
                    masters={n: masters[p].clone() for n, p in self.parameters.items()},
                    exp_avg={n: self.optimizer.state[p]['exp_avg'].clone() for n, p in self.parameters.items()},
                    exp_avg_sq={n: self.optimizer.state[p]['exp_avg_sq'].clone() for n, p in self.parameters.items()},
                    step={n: float(self.optimizer.state[p]['step']) for n, p in self.parameters.items()})


class ReleaseIsHarmless(Fixture):
    # The content pin is defined on Windows only (lead ruling 82965): GOLDEN_TENSOR_DIGEST is a Windows CPU value (the Linux CI runner decodes
    # the same tree to 7c577149..., the fixture's fused CPU AdamW / fp32-master arithmetic is not bit-identical across platforms) and no
    # pre-change tree exists on Linux to pin another. A test that passes with the fix reverted is not shipped as a pin on a platform where it cannot
    # be one: on Linux this method is not defined (not skipped, not deselected). It runs on Windows with the local reproduction command in the PR body.
    if sys.platform == 'win32':
        def test_the_published_child_has_the_pre_change_content(self):
            self.build()
            count, digest = tensor_digest(self.root)
            self.assertEqual((count, digest), (GOLDEN_TENSOR_FILES, GOLDEN_TENSOR_DIGEST),
                             'the published child differs from the pre-change tensor content; this is the digest the new tree produced: ' + digest)
            receipt = json.loads((self.root / 'parameter-counter-receipt.json').read_text(encoding='utf-8'))
            # the one file that moves is the counter receipt, and only because the counter is a new source file
            self.assertEqual(receipt['counter_sha256'], hashlib.sha256(Path(counter.__file__).read_bytes()).hexdigest())

    def test_the_verify_restores_the_state_bit_for_bit_and_releases_first(self):
        self.build()
        before = self.snapshot()
        order = []
        real_release, real_receipt = cia_hour.release_training_buffers, counter._cia_realization_receipt
        runner = SimpleNamespace(GIB=GIB)
        identity = {'config_sha256': hashlib.sha256(self.config_path.read_bytes()).hexdigest()}
        with patch.object(cia_hour, 'release_training_buffers', side_effect=lambda: (order.append('release'), real_release())[1]), \
                patch.object(counter, '_cia_realization_receipt',
                             side_effect=lambda *a, **k: (order.append('counter'), real_receipt(*a, **k))[1]):
            cia_hour.verify_checkpoint_restore(runner, self.model, self.optimizer, self.parameters, identity, self.custody, self.child)
        self.assertEqual(order, ['release', 'counter'])
        after = self.snapshot()
        for group in before:
            for name in before[group]:
                left, right = before[group][name], after[group][name]
                if isinstance(left, torch.Tensor):
                    self.assertTrue(torch.equal(left, right), (group, name))
                else:
                    self.assertEqual(left, right, (group, name))

    def test_a_restore_that_differs_is_still_refused_after_the_release(self):
        self.build()
        runner = SimpleNamespace(GIB=GIB)
        identity = {'config_sha256': hashlib.sha256(self.config_path.read_bytes()).hexdigest()}
        with patch.object(artifacts, 'load_checkpoint_artifacts', return_value={'data_cursor': {'different': True}}):
            with self.assertRaisesRegex(ValueError, 'checkpoint restore cursor differs'):
                cia_hour.verify_checkpoint_restore(runner, self.model, self.optimizer, self.parameters, identity, self.custody, self.child)


class HistoryCounterDifferential(Fixture):
    """A kept counter with the streaming reader bound onto it (`_counter_for`) derives the same facts, writes the same receipt bytes and
    refuses a tampered byte the same way as that counter's verbatim whole-file reading: its source bytes are untouched and only the IO
    mechanism differs. Both arms run on one real child written by the real writer."""
    HISTORY = Path(counter.__file__).parent / 'counter-history'
    PREVIOUS = 'b8704a16d577a9ce90edbbb2835ff85e04fcec62c95d45085ab4c396d895f1ba'

    def verbatim(self, digest):
        path = self.HISTORY / ('parameter_counter-%s.py' % digest)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest, 'a kept counter is verbatim')
        spec = importlib.util.spec_from_file_location('verbatim_counter_%s' % digest[:16], path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def outcome(self, module, root):
        try:
            result = module.execute_counter(model_config=self.config_path, checkpoint_manifest=Path(root) / 'checkpoint-manifest.json',
                                            active_expert='all')
        except Exception as error:
            return ('refused', type(error).__name__, str(error))
        return ('ok', json.dumps(result).encode())

    def digests(self):
        found = sorted(p.name[len('parameter_counter-'):-len('.py')] for p in self.HISTORY.glob('parameter_counter-*.py'))
        self.assertGreaterEqual(len(found), 5)
        return found

    def test_facts_and_receipt_bytes_are_equal_and_the_history_source_is_untouched(self):
        self.build()
        outcomes = {}
        for digest in self.digests():
            with self.subTest(counter=digest[:8]):
                before = hashlib.sha256((self.HISTORY / ('parameter_counter-%s.py' % digest)).read_bytes()).hexdigest()
                whole, streaming = self.outcome(self.verbatim(digest), self.root), self.outcome(counter._counter_for(digest), self.root)
                self.assertEqual(whole, streaming)
                outcomes[digest] = whole[0] if whole[0] == 'ok' else 'refused: %s' % whole[2][:70]
                self.assertEqual(hashlib.sha256((self.HISTORY / ('parameter_counter-%s.py' % digest)).read_bytes()).hexdigest(), before)
        self.assertEqual(outcomes[self.PREVIOUS], 'ok', 'the counter that wrote the H50 child must measure the fixture child')
        print('HISTORY_DIFFERENTIAL', {digest[:8]: kind for digest, kind in sorted(outcomes.items())})
        self.assertEqual({d for d, kind in outcomes.items() if kind == 'ok'}, {self.PREVIOUS})

    def test_a_tampered_byte_is_refused_the_same_way(self):
        self.build()
        for name in ('optimizer-state.pt', next(self.root.joinpath('objects').glob('*.pt')).relative_to(self.root).as_posix()):
            copy = Path(self.temp.name) / ('tamper-' + hashlib.sha256(name.encode()).hexdigest()[:8])
            shutil.copytree(self.root, copy)
            data = bytearray((copy / name).read_bytes())
            data[len(data) // 2] ^= 1
            (copy / name).write_bytes(bytes(data))
            for digest in self.digests():
                with self.subTest(counter=digest[:8], tampered=name):
                    whole, streaming = self.outcome(self.verbatim(digest), copy), self.outcome(counter._counter_for(digest), copy)
                    self.assertEqual(whole[0], 'refused')
                    self.assertEqual(whole, streaming)


class ReleaseBehaviour(unittest.TestCase):
    def test_cyclic_garbage_left_by_the_gated_loop_is_collected(self):
        class Holder:
            pass
        gc.disable()
        try:
            holder = Holder()
            holder.tensor = torch.zeros(1 << 20)
            holder.self = holder    # a reference cycle: only the collector can free it
            ref = weakref.ref(holder.tensor)
            del holder
            self.assertIsNotNone(ref())
            cia_hour.release_training_buffers()
            self.assertIsNone(ref())
        finally:
            gc.enable()

    def test_cuda_is_touched_only_where_torch_initialised_it_and_in_order(self):
        calls = []
        with patch.object(torch.cuda, 'is_available', return_value=False), patch.object(torch.cuda, 'is_initialized', side_effect=AssertionError):
            cia_hour.release_training_buffers()
        with patch.object(torch.cuda, 'is_available', return_value=True), patch.object(torch.cuda, 'is_initialized', return_value=False), \
                patch.object(torch.cuda, 'synchronize', side_effect=AssertionError), patch.object(torch.cuda, 'empty_cache', side_effect=AssertionError):
            cia_hour.release_training_buffers()
        with patch.object(torch.cuda, 'is_available', return_value=True), patch.object(torch.cuda, 'is_initialized', return_value=True), \
                patch.object(torch.cuda, 'synchronize', side_effect=lambda *a: calls.append('synchronize')), \
                patch.object(torch.cuda, 'empty_cache', side_effect=lambda: calls.append('empty_cache')), \
                patch.object(torch._C, '_host_emptyCache', side_effect=lambda: calls.append('host_cache'), create=True):
            cia_hour.release_training_buffers()
        self.assertEqual(calls, ['synchronize', 'empty_cache', 'host_cache'])

    def test_a_torch_without_the_host_cache_hook_still_releases(self):
        calls = []
        with patch.object(torch.cuda, 'is_available', return_value=True), patch.object(torch.cuda, 'is_initialized', return_value=True),                 patch.object(torch.cuda, 'synchronize', side_effect=lambda *a: calls.append('synchronize')),                 patch.object(torch.cuda, 'empty_cache', side_effect=lambda: calls.append('empty_cache')),                 patch.object(torch._C, '_host_emptyCache', None, create=True):
            cia_hour.release_training_buffers()
        self.assertEqual(calls, ['synchronize', 'empty_cache'])


class RunHourDropsTrainingOnlyReferences(unittest.TestCase):
    NAMES = {'capture', 'buffers', 'upcoming', 'pack', 'row', 'contention'}

    def test_the_names_are_dropped_before_the_verify_and_never_read_after(self):
        tree = ast.parse(inspect.getsource(cia_hour.run_hour))
        function = tree.body[0]
        verify = [n for n in ast.walk(function) if isinstance(n, ast.Call) and getattr(n.func, 'id', None) == 'verify_checkpoint_restore']
        self.assertEqual(len(verify), 1)
        verify_line = verify[0].lineno
        drops = [n for n in ast.walk(function) if isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant) and n.value.value is None
                 and self.NAMES <= {t.id for t in n.targets if isinstance(t, ast.Name)}]
        self.assertEqual(len(drops), 1)
        self.assertLess(drops[0].lineno, verify_line)
        reads = [(n.id, n.lineno) for n in ast.walk(function)
                 if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and n.id in self.NAMES and n.lineno > drops[0].lineno]
        self.assertEqual(reads, [])


if __name__ == '__main__':
    unittest.main()
