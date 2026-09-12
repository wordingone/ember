# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Fail-closed legs of the CIA checkpoint-bound Evaluation minimum gate on a tiny physical checkpoint.

The tiny checkpoint follows the transaction fixture (26 eight-element tensors under a patched inventory),
so these tests prove the identity, fixture and leakage refusals and the positive open of an admitted
checkpoint. The scoring leg needs the real CIA-3B reference and is proven only on the real path (an
admitted probe checkpoint); no test here fakes a forward pass or claims a score.
"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import torch

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / 'src/ember/infrastructure/tools/ember-restart-3b'
for entry in (ROOT / 'src', TOOLS):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))
import checkpoint_artifacts as artifacts  # noqa: E402
import parameter_counter as counter  # noqa: E402
import eval_cia_checkpoint_gate as gate  # noqa: E402
import cia_step_runner as runner  # noqa: E402
from ember.model import ember_v0_inventory as cia_inventory, ember_v0_decoder as cia_decoder  # noqa: E402
from ember.model.ember_v0_contract import cia_architecture_config, validate_cia_architecture  # noqa: E402

HELD = 'a' * 64
TRAIN = 'b' * 64
TOKENIZER_SHA = 'c' * 64


def _export():
    """Minimal frozen-export shape: one admitted heldout object, one admitted train object."""
    records = [
        {'kind': 'immutable_object', 'sha256': HELD, 'id': 'sha256:' + HELD},
        {'kind': 'immutable_object', 'sha256': TRAIN, 'id': 'sha256:' + TRAIN},
        {'kind': 'membership', 'exact_sha256': HELD, 'split': 'heldout', 'admission_state': 'admitted'},
        {'kind': 'membership', 'exact_sha256': TRAIN, 'split': 'train', 'admission_state': 'admitted'},
        {'kind': 'dataset_version', 'id': 'dataset:test'},
    ]
    return {'records': records, 'edges': []}


def _write(path, payload):
    raw = json.dumps(payload, sort_keys=True).encode('utf-8')
    Path(path).write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def _fixture(object_sha256, sequence=8, export_sha256='0' * 64):
    ids = list(range(sequence + 1))
    item = {'object_sha256': object_sha256, 'path': 'doc.json', 'token_ids': ids,
            'item_sha256': gate.item_sha256(object_sha256, ids)}
    fixture = {'schema_version': gate.FIXTURE_SCHEMA, 'export_sha256': export_sha256, 'tokenizer_sha256': TOKENIZER_SHA,
               'tokenizers_version': 'test', 'corpus_root_name': 'test', 'corpus_receipt_sha256': '1' * 64,
               'count': 1, 'sequence': sequence, 'object_class': 'admitted-heldout', 'items': [item], 'skipped': {}}
    fixture['self_sha256'] = gate.sha256_bytes(gate.canonical(fixture))
    return fixture


class FixtureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)
        self.export_path = self.dir / 'export.json'
        self.export_sha = _write(self.export_path, _export())
        self.export = gate.load_export(self.export_path, self.export_sha)

    def test_export_identity_is_pinned(self):
        with self.assertRaises(gate.GateRefusal) as caught:
            gate.load_export(self.export_path, '9' * 64)
        self.assertEqual(caught.exception.token, 'EXPORT_IDENTITY')

    def test_heldout_fixture_passes_and_records_executed_leakage(self):
        sha = _write(self.dir / 'f.json', _fixture(HELD, export_sha256=self.export_sha))
        result = gate.validate_fixture(self.dir / 'f.json', sha, self.export)
        self.assertEqual(result['leakage_assertion']['items_checked'], 1)
        self.assertEqual(result['leakage_assertion']['train_overlaps'], 0)

    def test_fixture_sha_mismatch_refused(self):
        _write(self.dir / 'f.json', _fixture(HELD, export_sha256=self.export_sha))
        with self.assertRaises(gate.GateRefusal) as caught:
            gate.validate_fixture(self.dir / 'f.json', '9' * 64, self.export)
        self.assertEqual(caught.exception.token, 'FIXTURE_IDENTITY')

    def test_train_member_in_fixture_is_leakage(self):
        sha = _write(self.dir / 'f.json', _fixture(TRAIN, export_sha256=self.export_sha))
        with self.assertRaises(gate.GateRefusal) as caught:
            gate.validate_fixture(self.dir / 'f.json', sha, self.export)
        self.assertEqual(caught.exception.token, 'FIXTURE_LEAKAGE')

    def test_tampered_token_ids_refused(self):
        fixture = _fixture(HELD, export_sha256=self.export_sha)
        fixture['items'][0]['token_ids'][3] = 99
        fixture['self_sha256'] = gate.sha256_bytes(gate.canonical({k: v for k, v in fixture.items() if k != 'self_sha256'}))
        sha = _write(self.dir / 'f.json', fixture)
        with self.assertRaises(gate.GateRefusal) as caught:
            gate.validate_fixture(self.dir / 'f.json', sha, self.export)
        self.assertEqual(caught.exception.token, 'FIXTURE_ITEM_DIGEST')

    def test_cli_refuses_before_any_checkpoint_read(self):
        _write(self.dir / 'f.json', _fixture(HELD, export_sha256=self.export_sha))
        output = self.dir / 'receipt.json'
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONPATH=str(ROOT / 'src'))
        arguments = [str(TOOLS / 'eval_cia_checkpoint_gate.py'), 'run',
                     '--checkpoint', str(self.dir / 'absent'), '--receipt', str(self.dir / 'absent.json'),
                     '--fixture', str(self.dir / 'f.json'), '--fixture-sha256', '9' * 64,
                     '--export', str(self.export_path), '--export-sha256', self.export_sha,
                     '--tokenizer', str(self.export_path), '--tokenizer-sha256', TOKENIZER_SHA,
                     '--output', str(output)]
        if os.name == 'nt':
            # Permanent host rule: every non-CLI Python child runs through the headless helper, hidden.
            helper = Path.home() / '.codex/headless-python.ps1'
            command = ['powershell.exe', '-NoLogo', '-NoProfile', '-NonInteractive', '-File', str(helper), '--'] + arguments
            env['CODEX_PYTHON'] = sys.executable
            hidden = runner.hidden_kwargs()
        else:
            command, hidden = [sys.executable] + arguments, {}
        completed = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, text=True, env=env,
                                   timeout=300, **hidden)
        self.assertEqual(completed.returncode, 2, completed.stderr)
        self.assertIn('REFUSED:FIXTURE_IDENTITY', completed.stderr)
        self.assertFalse(output.exists())


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'published'
        self.config_path = Path(self.temp.name) / 'config.json'
        self.config_path.write_text(json.dumps(cia_architecture_config()), encoding='utf-8')
        specs = (cia_inventory.TensorSpec('embedding.weight', (8,), 'core'),) + tuple(
            cia_inventory.TensorSpec(f'experts.{i}.weight', (8,), 'expert', i) for i in range(25))
        self.parameters = {spec.name: torch.nn.Parameter(torch.full(spec.shape, i, dtype=torch.bfloat16))
                           for i, spec in enumerate(specs)}
        self.model = type('Fixture', (), {'parameter_inventory': lambda _: self.parameters})()
        self.model.config = validate_cia_architecture(cia_architecture_config())
        self.model._cuda_execution = None
        dispatch = patch.object(cia_decoder, 'CIADecoder', type(self.model))
        dispatch.start()
        self.addCleanup(dispatch.stop)
        self.optimizer = torch.optim.AdamW(self.parameters.values(), lr=.01, foreach=False)
        self.identity = {'param_groups': [{'params': list(self.parameters), 'hyperparameters': {'amsgrad': False}}]}
        for target, attr, value in ((cia_inventory, 'equation_inventory', specs),
                                    (artifacts, 'cia_optimizer_identity', self.identity)):
            mocking = patch.object(target, attr, return_value=value)
            mocking.start()
            self.addCleanup(mocking.stop)
        receipt = artifacts.write_checkpoint_artifacts(
            self.model, self.optimizer, self.root, launch_seed=7,
            rng_state={'cpu': torch.get_rng_state(), 'cuda': torch.empty(0, dtype=torch.uint8)},
            data_cursor={'shard': 'fixture', 'record_index': 0, 'global_step': 0, 'tokens_seen': 0},
            model_config_sha256=hashlib.sha256(self.config_path.read_bytes()).hexdigest(), contract_sha256='2' * 64,
            expert_genesis_sha256={}, max_serialized_bytes=4 * 1024 * 1024, max_transient_scratch_bytes=1024 * 1024,
            pre_publish_verifier=self.verifier)
        self.receipt_path = Path(self.temp.name) / 'receipt.json'
        self.receipt_path.write_text(json.dumps(receipt, sort_keys=True), encoding='utf-8')
        self.receipt = receipt

    def verifier(self, candidate, receipt):
        result = counter.execute_counter(model_config=self.config_path,
                                         checkpoint_manifest=candidate / 'checkpoint-manifest.json', active_expert='all')
        (candidate / 'parameter-counter-receipt.json').write_text(json.dumps(result), encoding='utf-8')
        return result

    def test_admitted_checkpoint_opens_with_complete_inventory(self):
        verified, tensors = gate.open_checkpoint(self.root, self.receipt_path, max_restore_bytes=1024 * 1024)
        self.assertEqual(set(tensors), set(self.parameters))
        self.assertEqual(verified['checkpoint_manifest_sha256'], self.receipt['checkpoint']['byte_sha256'])
        for name, value in tensors.items():
            torch.testing.assert_close(value, self.parameters[name].detach(), rtol=0, atol=0)

    def test_flipped_core_object_byte_refused(self):
        path = self.root / 'objects' / (self.receipt['core']['sha256'] + '.pt')
        raw = bytearray(path.read_bytes())
        raw[-1] ^= 0xFF
        path.write_bytes(bytes(raw))
        with self.assertRaises(gate.GateRefusal) as caught:
            gate.open_checkpoint(self.root, self.receipt_path, max_restore_bytes=1024 * 1024)
        self.assertEqual(caught.exception.token, 'CHECKPOINT_REFUSED')

    def test_receipt_with_foreign_architecture_refused(self):
        receipt = json.loads(self.receipt_path.read_text(encoding='utf-8'))
        receipt['architecture_config'] = dict(receipt['architecture_config'], d_model=8)
        self.receipt_path.write_text(json.dumps(receipt, sort_keys=True), encoding='utf-8')
        with self.assertRaises(gate.GateRefusal) as caught:
            gate.open_checkpoint(self.root, self.receipt_path, max_restore_bytes=1024 * 1024)
        self.assertEqual(caught.exception.token, 'CHECKPOINT_REFUSED')

    def test_receipt_identity_field_is_bound(self):
        receipt = json.loads(self.receipt_path.read_text(encoding='utf-8'))
        receipt['checkpoint']['byte_sha256'] = '9' * 64
        self.receipt_path.write_text(json.dumps(receipt, sort_keys=True), encoding='utf-8')
        with self.assertRaises(gate.GateRefusal) as caught:
            gate.open_checkpoint(self.root, self.receipt_path, max_restore_bytes=1024 * 1024)
        self.assertEqual(caught.exception.token, 'RECEIPT_IDENTITY')

    def test_missing_expert_object_refused(self):
        expert = self.receipt['expert_parameter_sha256']['3']
        (self.root / 'objects' / (expert + '.pt')).unlink()
        with self.assertRaises(gate.GateRefusal) as caught:
            gate.open_checkpoint(self.root, self.receipt_path, max_restore_bytes=1024 * 1024)
        self.assertEqual(caught.exception.token, 'CHECKPOINT_REFUSED')


if __name__ == '__main__':
    unittest.main()
