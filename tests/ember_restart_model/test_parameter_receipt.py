# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""TDD checkpoint-bound sparse parameter counter receipt."""

from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "ember-restart-3b"))

from checkpoint_artifacts import write_checkpoint_artifacts as _production_write
from model import RestartDecoderConfig, UnifiedDecoder
# issue2015 exact-local-import:tests/ember_restart_model/domain-governance/checkpoint_fixture.py
import importlib.util as _ember_c22d7dabcd875f5a_importlib
import sys as _ember_c22d7dabcd875f5a_sys
from pathlib import Path as _ember_c22d7dabcd875f5a_Path
_ember_c22d7dabcd875f5a_path = _ember_c22d7dabcd875f5a_Path(__file__).resolve().parents[2].joinpath('tests', 'ember_restart_model', 'domain-governance', 'checkpoint_fixture.py')
if not _ember_c22d7dabcd875f5a_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:tests/ember_restart_model/domain-governance/checkpoint_fixture.py')
_ember_c22d7dabcd875f5a_aliases = ('_ember_issue2015_c22d7dabcd875f5a', 'checkpoint_fixture', 'tests.ember_restart_model.checkpoint_fixture')
_ember_c22d7dabcd875f5a_existing = []
for _ember_c22d7dabcd875f5a_alias in _ember_c22d7dabcd875f5a_aliases:
    _ember_c22d7dabcd875f5a_candidate = _ember_c22d7dabcd875f5a_sys.modules.get(_ember_c22d7dabcd875f5a_alias)
    if _ember_c22d7dabcd875f5a_candidate is not None and all(_ember_c22d7dabcd875f5a_candidate is not item for item in _ember_c22d7dabcd875f5a_existing):
        _ember_c22d7dabcd875f5a_existing.append(_ember_c22d7dabcd875f5a_candidate)
if len(_ember_c22d7dabcd875f5a_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:tests/ember_restart_model/domain-governance/checkpoint_fixture.py')
if _ember_c22d7dabcd875f5a_existing:
    _ember_c22d7dabcd875f5a_module = _ember_c22d7dabcd875f5a_existing[0]
    _ember_c22d7dabcd875f5a_observed = getattr(_ember_c22d7dabcd875f5a_module, '__file__', None)
    if _ember_c22d7dabcd875f5a_observed is None or _ember_c22d7dabcd875f5a_Path(_ember_c22d7dabcd875f5a_observed).resolve() != _ember_c22d7dabcd875f5a_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:tests/ember_restart_model/domain-governance/checkpoint_fixture.py')
else:
    _ember_c22d7dabcd875f5a_spec = _ember_c22d7dabcd875f5a_importlib.spec_from_file_location('_ember_issue2015_c22d7dabcd875f5a', _ember_c22d7dabcd875f5a_path)
    if _ember_c22d7dabcd875f5a_spec is None or _ember_c22d7dabcd875f5a_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:tests/ember_restart_model/domain-governance/checkpoint_fixture.py')
    _ember_c22d7dabcd875f5a_module = _ember_c22d7dabcd875f5a_importlib.module_from_spec(_ember_c22d7dabcd875f5a_spec)
    for _ember_c22d7dabcd875f5a_alias in _ember_c22d7dabcd875f5a_aliases:
        _ember_c22d7dabcd875f5a_prior = _ember_c22d7dabcd875f5a_sys.modules.get(_ember_c22d7dabcd875f5a_alias)
        if _ember_c22d7dabcd875f5a_prior is not None and _ember_c22d7dabcd875f5a_prior is not _ember_c22d7dabcd875f5a_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:tests/ember_restart_model/domain-governance/checkpoint_fixture.py')
        _ember_c22d7dabcd875f5a_sys.modules[_ember_c22d7dabcd875f5a_alias] = _ember_c22d7dabcd875f5a_module
    try:
        _ember_c22d7dabcd875f5a_spec.loader.exec_module(_ember_c22d7dabcd875f5a_module)
    except BaseException:
        for _ember_c22d7dabcd875f5a_alias in _ember_c22d7dabcd875f5a_aliases:
            if _ember_c22d7dabcd875f5a_sys.modules.get(_ember_c22d7dabcd875f5a_alias) is _ember_c22d7dabcd875f5a_module:
                _ember_c22d7dabcd875f5a_sys.modules.pop(_ember_c22d7dabcd875f5a_alias, None)
        raise
for _ember_c22d7dabcd875f5a_alias in _ember_c22d7dabcd875f5a_aliases:
    _ember_c22d7dabcd875f5a_prior = _ember_c22d7dabcd875f5a_sys.modules.get(_ember_c22d7dabcd875f5a_alias)
    if _ember_c22d7dabcd875f5a_prior is not None and _ember_c22d7dabcd875f5a_prior is not _ember_c22d7dabcd875f5a_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:tests/ember_restart_model/domain-governance/checkpoint_fixture.py')
    _ember_c22d7dabcd875f5a_sys.modules[_ember_c22d7dabcd875f5a_alias] = _ember_c22d7dabcd875f5a_module
write_checkpoint_artifacts = getattr(_ember_c22d7dabcd875f5a_module, 'write_checkpoint_artifacts')
# issue2015 exact-local-import-end:tests/ember_restart_model/domain-governance/checkpoint_fixture.py





from parameter_counter import write_parameter_receipt


class ParameterReceiptTests(unittest.TestCase):
    def test_binds_config_counter_checkpoint_and_preupdate_genesis_hashes(self) -> None:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=7)
        optimizer = torch.optim.AdamW((p for p in model.parameters() if p.requires_grad), lr=1e-4)
        genesis = model.expert_bank_genesis_hashes()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config.json"
            config_path.write_text("{}", encoding="utf-8")
            checkpoint = write_checkpoint_artifacts(model, optimizer, root / "checkpoint", launch_seed=7, rng_state={"cpu": torch.get_rng_state().clone(), "cuda": torch.tensor([1, 2, 3], dtype=torch.uint8)}, data_cursor={"shard": "owned-test-v1", "record_index": 0, "global_step": 0, "tokens_seen": 0}, model_config_sha256="c" * 64, contract_sha256="d" * 64, expert_genesis_sha256=genesis)
            receipt = write_parameter_receipt(model, config_path, root / "checkpoint" / "checkpoint-manifest.json", genesis)
        self.assertEqual(receipt["result"], "MEASURED")
        self.assertEqual(receipt["active_expert_ids"], ["reasoning"])
        self.assertEqual(receipt["expert_genesis_sha256"], genesis)
        self.assertEqual(receipt["counter_sha256"], hashlib.sha256((ROOT / "tools" / "ember-restart-3b" / "parameter_counter.py").read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
