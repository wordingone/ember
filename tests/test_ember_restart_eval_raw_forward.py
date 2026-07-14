# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def test_runner_accepts_valid_tokenizer_and_checkpoint_probe():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        tokenizer = root / "tokenizer.json"
        checkpoint = root / "checkpoint-manifest.json"
        output = root / "receipt.json"
        tokenizer.write_text(
            json.dumps(
                {
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
            ),
            encoding="utf-8",
        )
        checkpoint.write_text('{"schema":"ember-sparse-checkpoint-v2"}\n', encoding="utf-8")
        completed = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).parents[1] / "scripts" / "ember_restart_eval_raw_forward.py"),
                "--tokenizer",
                str(tokenizer),
                "--checkpoint-manifest",
                str(checkpoint),
                "--checkpoint-sha256",
                hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
                "--output",
                str(output),
            ],
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0, completed.stderr
        assert output.exists()
