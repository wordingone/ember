# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "ember_restart_eval_raw_forward.py"


def tokenizer_payload():
    return {
        "version": "1.0",
        "truncation": None,
        "padding": None,
        "added_tokens": [],
        "normalizer": None,
        "pre_tokenizer": None,
        "post_processor": None,
        "decoder": None,
        "model": {"type": "WordLevel", "vocab": {"x": 0}, "unk_token": "x"},
    }


def test_records_verified_checkpoint_hash_before_preflight_output():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        tokenizer = root / "tokenizer.json"
        checkpoint = root / "checkpoint-manifest.json"
        output = root / "receipt.json"
        tokenizer.write_text(json.dumps(tokenizer_payload()), encoding="utf-8")
        checkpoint.write_text('{"schema":"ember-sparse-checkpoint-v2"}\n', encoding="utf-8")
        checkpoint_sha256 = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
        completed = subprocess.run([sys.executable, str(SCRIPT), "--tokenizer", str(tokenizer), "--checkpoint-manifest", str(checkpoint), "--checkpoint-sha256", checkpoint_sha256, "--output", str(output)], capture_output=True, text=True)
        assert completed.returncode == 0, completed.stderr
        assert json.loads(output.read_text(encoding="utf-8"))["checkpoint_sha256"] == checkpoint_sha256
