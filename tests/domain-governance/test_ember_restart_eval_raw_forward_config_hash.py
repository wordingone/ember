# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from test_ember_restart_eval_checkpoint_consumer_v3_contract import write_v3


SCRIPT = Path(__file__).parents[1] / "scripts" / "ember_restart_eval_raw_forward.py"


def test_rejects_supplied_model_config_hash_mismatch_before_output():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        tokenizer, output = root / "tokenizer.json", root / "receipt.json"
        tokenizer.write_text(json.dumps({"version": "1.0", "truncation": None, "padding": None, "added_tokens": [], "normalizer": None, "pre_tokenizer": None, "post_processor": None, "decoder": None, "model": {"type": "WordLevel", "vocab": {"x": 0}, "unk_token": "x"}}), encoding="utf-8")
        checkpoint = write_v3(root)
        completed = subprocess.run([sys.executable, str(SCRIPT), "--tokenizer", str(tokenizer), "--checkpoint-manifest", str(checkpoint), "--checkpoint-sha256", hashlib.sha256(checkpoint.read_bytes()).hexdigest(), "--model-config", str(root / "config.json"), "--model-config-sha256", "0" * 64, "--output", str(output)], capture_output=True, text=True)
        assert completed.returncode != 0
        assert not output.exists()
