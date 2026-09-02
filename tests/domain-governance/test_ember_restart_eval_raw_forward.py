# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from test_ember_restart_eval_checkpoint_consumer_v3_contract import write_v3


def test_runner_accepts_valid_tokenizer_and_checkpoint_probe():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        tokenizer, output = root / "tokenizer.json", root / "receipt.json"
        tokenizer.write_text(json.dumps({"version": "1.0", "truncation": None, "padding": None, "added_tokens": [], "normalizer": None, "pre_tokenizer": None, "post_processor": None, "decoder": None, "model": {"type": "WordLevel", "vocab": {"x": 0}, "unk_token": "x"}}), encoding="utf-8")
        checkpoint = write_v3(root)
        config = root / "config.json"
        completed = subprocess.run([sys.executable, str(Path(__file__).parents[1] / "scripts" / "ember_restart_eval_raw_forward.py"), "--tokenizer", str(tokenizer), "--checkpoint-manifest", str(checkpoint), "--checkpoint-sha256", hashlib.sha256(checkpoint.read_bytes()).hexdigest(), "--model-config", str(config), "--model-config-sha256", hashlib.sha256(config.read_bytes()).hexdigest(), "--output", str(output)], capture_output=True, text=True)
        assert completed.returncode == 0, completed.stderr
        assert output.exists()


def test_refuses_to_overwrite_an_existing_raw_forward_receipt():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        tokenizer, output = root / "tokenizer.json", root / "receipt.json"
        tokenizer.write_text(json.dumps({"version": "1.0", "truncation": None, "padding": None, "added_tokens": [], "normalizer": None, "pre_tokenizer": None, "post_processor": None, "decoder": None, "model": {"type": "WordLevel", "vocab": {"x": 0}, "unk_token": "x"}}), encoding="utf-8")
        checkpoint = write_v3(root)
        config = root / "config.json"
        output.write_text("preserve", encoding="utf-8")
        completed = subprocess.run([sys.executable, str(Path(__file__).parents[1] / "scripts" / "ember_restart_eval_raw_forward.py"), "--tokenizer", str(tokenizer), "--checkpoint-manifest", str(checkpoint), "--checkpoint-sha256", hashlib.sha256(checkpoint.read_bytes()).hexdigest(), "--model-config", str(config), "--model-config-sha256", hashlib.sha256(config.read_bytes()).hexdigest(), "--output", str(output)], capture_output=True, text=True)
        assert completed.returncode != 0
        assert "refusing to overwrite existing output" in completed.stderr

def test_rejects_nontext_capability_label_before_writing_receipt():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary); tokenizer, output = root / "tokenizer.json", root / "receipt.json"
        tokenizer.write_text(json.dumps({"version": "1.0", "truncation": None, "padding": None, "added_tokens": [], "normalizer": None, "pre_tokenizer": None, "post_processor": None, "decoder": None, "model": {"type": "WordLevel", "vocab": {"x": 0}, "unk_token": "x"}}), encoding="utf-8")
        checkpoint = write_v3(root); config = root / "config.json"
        completed = subprocess.run([sys.executable, str(Path(__file__).parents[1] / "scripts" / "ember_restart_eval_raw_forward.py"), "--tokenizer", str(tokenizer), "--checkpoint-manifest", str(checkpoint), "--checkpoint-sha256", hashlib.sha256(checkpoint.read_bytes()).hexdigest(), "--model-config", str(config), "--model-config-sha256", hashlib.sha256(config.read_bytes()).hexdigest(), "--benchmark-capability", "image", "--output", str(output)], capture_output=True, text=True)
        assert completed.returncode != 0
        assert not output.exists()
