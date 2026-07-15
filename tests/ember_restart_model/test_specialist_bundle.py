# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Owned specialist bundle-emitter contract tests."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tokenizers import Tokenizer, models, pre_tokenizers

ROOT = Path(__file__).resolve().parents[2]
VERIFIER = ROOT / "tools" / "ember-restart-3b" / "verify_training_data.py"
sys.path.insert(0, str(ROOT / "tools" / "ember-restart-3b"))


class SpecialistBundleTests(unittest.TestCase):
    def test_emitter_produces_four_independently_verified_source_bound_manifests(self) -> None:
        from build_specialist_bundle import emit_bundle

        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            root = Path(directory)
            tokenizer = root / "tokenizer.json"
            vocabulary = {"<unk>": 0, "image": 1, "scene": 2, "has": 3, "red": 4, "green": 5, "blue": 6, "squares": 7, "audio": 8, "signal": 9, "positive": 10, "negative": 11, "silent": 12, "frames": 13, "reasoning": 14, "sum": 15, "plus": 16, "equals": 17, "tool": 18, "calculator": 19, **{f"filler-{index}": index for index in range(20, 32_000)}}
            frozen = Tokenizer(models.WordLevel(vocabulary, unk_token="<unk>"))
            frozen.pre_tokenizer = pre_tokenizers.Whitespace()
            frozen.save(str(tokenizer))
            config = root / "config.json"
            config.write_text(json.dumps({"model": {"vocab_size": 32_000, "image_projection": {"input_shape": [48, 48, 3]}, "audio_projection": {"frame_samples": 640}}}), encoding="utf-8")
            emitted = emit_bundle(repo_root=ROOT, output_root=root / "bundle", tokenizer_path=tokenizer, model_config_path=config, count=512)
            self.assertEqual(set(emitted), {"image", "audio", "reasoning", "tool"})
            for capability, manifest in emitted.items():
                completed = subprocess.run([sys.executable, str(VERIFIER), "--data-manifest", str(manifest), "--tokenizer", str(tokenizer), "--capability", capability], cwd=ROOT, text=True, capture_output=True, timeout=30, check=False)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                receipt = json.loads(completed.stdout)
                self.assertEqual(receipt["result"], "VERIFIED")
                self.assertGreaterEqual(receipt["record_count"], 512)
                self.assertGreaterEqual(receipt["token_count"], 4096)
                payload = json.loads(manifest.read_text(encoding="utf-8"))
                source_path = ROOT / payload["source_manifest"]["path"]
                source = json.loads(source_path.read_text(encoding="utf-8"))
                generator = source["semantic_provenance"]["generator"]
                generator_path = ROOT / generator["path"]
                self.assertEqual(generator["sha256"], hashlib.sha256(generator_path.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()