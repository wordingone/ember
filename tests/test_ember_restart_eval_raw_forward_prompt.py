# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "ember_restart_eval_raw_forward.py"
sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location("raw_forward_prompt", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _sha256_bytes(value):
    return hashlib.sha256(value).hexdigest()


def _token_digest(tokens):
    return _sha256_bytes(json.dumps(tokens, separators=(",", ":")).encode("utf-8"))


def _write_bound_inputs(tmp_path, *, prompt_override=None, split_override=None):
    prompt = {"schema_version": "ember-owned-inference-prompt-v1", "id": "row-1", "active_expert": "shared", "token_ids": [8, 9]}
    if prompt_override:
        prompt.update(prompt_override)
    prompt_path = tmp_path / "prompt.json"
    prompt_path.write_text(json.dumps(prompt, sort_keys=True), encoding="utf-8")
    prompt_sha256 = _sha256_bytes(prompt_path.read_bytes())
    split = {"schema_version": "ember-owned-frozen-local-text-split-v1", "benchmark_id": "local-text", "benchmark_version": "1", "rows": [{"id": prompt["id"], "prompt_sha256": prompt_sha256, "active_expert": prompt["active_expert"], "token_ids_sha256": _token_digest(prompt["token_ids"])}], "target_training_access": "FORBIDDEN"}
    if split_override:
        split_override(split)
    split_path = tmp_path / "split.json"
    split_path.write_text(json.dumps(split, sort_keys=True), encoding="utf-8")
    return prompt_path, split_path, prompt_sha256


def _binding(prompt, split, split_sha256=None):
    return MODULE.load_canonical_prompt_binding(prompt, split, split_sha256 or _sha256_bytes(split.read_bytes()), "local-text", "1")


def test_loads_closed_owned_prompt_without_targets(tmp_path):
    prompt, _, _ = _write_bound_inputs(tmp_path)
    assert MODULE.load_owned_prompt(prompt) == {"id": "row-1", "active_expert": "shared", "token_ids": [8, 9]}


def test_rejects_target_ids_in_owned_prompt_before_generation(tmp_path):
    prompt, _, _ = _write_bound_inputs(tmp_path, prompt_override={"target_ids": [9, 10]})
    with pytest.raises(ValueError, match="target_ids"):
        MODULE.load_owned_prompt(prompt)


def test_frozen_prompt_binding_derives_canonical_row_route_tokens_and_digest(tmp_path):
    prompt, split, prompt_sha256 = _write_bound_inputs(tmp_path)
    assert _binding(prompt, split) == {"row_id": "row-1", "active_expert": "shared", "token_ids": [8, 9], "input_sha256": prompt_sha256}


def test_prompt_binding_reads_each_prompt_and_split_byte_stream_once(tmp_path, monkeypatch):
    prompt, split, _ = _write_bound_inputs(tmp_path)
    prompt_bytes, split_bytes = prompt.read_bytes(), split.read_bytes()
    reads = {prompt: 0, split: 0}
    original_read_bytes = Path.read_bytes

    def counted_read_bytes(path):
        if path in reads:
            reads[path] += 1
            if reads[path] > 1:
                raise AssertionError(f"reopened immutable binding input: {path.name}")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", counted_read_bytes)
    assert MODULE.load_canonical_prompt_binding(prompt, split, _sha256_bytes(split_bytes), "local-text", "1") == {
        "row_id": "row-1",
        "active_expert": "shared",
        "token_ids": [8, 9],
        "input_sha256": _sha256_bytes(prompt_bytes),
    }
    assert reads == {prompt: 1, split: 1}

def test_prompt_binding_rejects_split_digest_substitution(tmp_path):
    prompt, split, _ = _write_bound_inputs(tmp_path)
    with pytest.raises(ValueError, match="split digest"):
        _binding(prompt, split, "0" * 64)


@pytest.mark.parametrize("field,value", [("benchmark_id", "other-text"), ("benchmark_version", "2")])
def test_prompt_binding_rejects_frozen_benchmark_identity_substitution(tmp_path, field, value):
    prompt, split, _ = _write_bound_inputs(tmp_path, split_override=lambda frozen: frozen.update({field: value}))
    with pytest.raises(ValueError, match="benchmark identity"):
        _binding(prompt, split)

def test_prompt_binding_rejects_prompt_hash_substitution(tmp_path):
    prompt, split, _ = _write_bound_inputs(tmp_path, split_override=lambda value: value["rows"][0].update({"prompt_sha256": "0" * 64}))
    with pytest.raises(ValueError, match="prompt hash"):
        _binding(prompt, split)


def test_prompt_binding_rejects_row_substitution(tmp_path):
    prompt, split, _ = _write_bound_inputs(tmp_path, split_override=lambda value: value["rows"][0].update({"id": "other-row"}))
    with pytest.raises(ValueError, match="row"):
        _binding(prompt, split)


def test_prompt_binding_rejects_route_substitution(tmp_path):
    prompt, split, _ = _write_bound_inputs(tmp_path, split_override=lambda value: value["rows"][0].update({"active_expert": "tool"}))
    with pytest.raises(ValueError, match="route"):
        _binding(prompt, split)


def test_prompt_binding_rejects_token_sequence_substitution(tmp_path):
    prompt, split, _ = _write_bound_inputs(tmp_path, split_override=lambda value: value["rows"][0].update({"token_ids_sha256": _token_digest([7, 9])}))
    with pytest.raises(ValueError, match="token"):
        _binding(prompt, split)


def test_prompt_binding_rejects_stale_scalar_local_text_prompt_schema(tmp_path):
    prompt = tmp_path / "stale-prompt.json"
    prompt.write_text(json.dumps({"schema_version": "ember-owned-frozen-local-text-prompt-v1", "id": "row-1", "active_expert": "shared", "input_token_id": 8}), encoding="utf-8")
    split = tmp_path / "split.json"
    split.write_text(json.dumps({"schema_version": "ember-owned-frozen-local-text-split-v1", "benchmark_id": "local-text", "benchmark_version": "1", "rows": [{"id": "row-1", "prompt_sha256": _sha256_bytes(prompt.read_bytes()), "active_expert": "shared", "token_ids_sha256": _token_digest([8])}], "target_training_access": "FORBIDDEN"}), encoding="utf-8")
    with pytest.raises(ValueError, match="prompt schema"):
        _binding(prompt, split)


def _canonical_arguments(tmp_path, prompt, split, *, manual=()):
    return [str(SCRIPT), "--tokenizer", str(tmp_path / "tokenizer.json"), "--checkpoint-manifest", str(tmp_path / "checkpoint.json"), "--checkpoint-sha256", "a" * 64, "--model-config", str(tmp_path / "config.json"), "--model-config-sha256", "b" * 64, "--output", str(tmp_path / "receipt.json"), "--canonical-output", str(tmp_path / "predictions.json"), "--execute", "--model-source", str(tmp_path / "model.py"), "--model-source-sha256", "c" * 64, "--prompt", str(prompt), "--frozen-split", str(split), "--benchmark-id", "local-text", "--benchmark-version", "1", "--benchmark-capability", "text", "--split-sha256", _sha256_bytes(split.read_bytes()), "--protocol-sha256", "d" * 64, *manual]


def test_canonical_output_reaches_owned_prompt_binding_before_model_loading(tmp_path, monkeypatch, capsys):
    prompt, split, _ = _write_bound_inputs(tmp_path)
    monkeypatch.setattr(MODULE, "load_canonical_prompt_binding", lambda *args: (_ for _ in ()).throw(ValueError("prompt binding reached")), raising=False)
    monkeypatch.setitem(sys.modules, "tokenizers", SimpleNamespace(Tokenizer=object))
    monkeypatch.setattr(sys, "argv", _canonical_arguments(tmp_path, prompt, split))
    with pytest.raises(SystemExit, match="2"):
        MODULE.main()
    assert "prompt binding reached" in capsys.readouterr().err


@pytest.mark.parametrize("manual", [("--input-token-id", "8"), ("--active-expert", "shared"), ("--row-id", "row-1")])
def test_canonical_output_rejects_detached_manual_prompt_fields(tmp_path, monkeypatch, capsys, manual):
    prompt, split, _ = _write_bound_inputs(tmp_path)
    monkeypatch.setattr(MODULE, "load_canonical_prompt_binding", lambda *args: {"row_id": "row-1", "active_expert": "shared", "token_ids": [8, 9], "input_sha256": "e" * 64}, raising=False)
    monkeypatch.setitem(sys.modules, "tokenizers", SimpleNamespace(Tokenizer=object))
    monkeypatch.setattr(sys, "argv", _canonical_arguments(tmp_path, prompt, split, manual=manual))
    with pytest.raises(SystemExit, match="2"):
        MODULE.main()
    assert "detached manual" in capsys.readouterr().err