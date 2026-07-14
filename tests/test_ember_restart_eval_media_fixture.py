# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Deterministic image/audio fixture scorer self-test."""
import hashlib
import json
import subprocess
import sys


def test_scores_frozen_image_and_audio_rows_as_non_admissible_selftest(tmp_path):
    image = tmp_path / "image.bin"; audio = tmp_path / "audio.bin"
    image.write_bytes(b"frozen-image-fixture"); audio.write_bytes(b"frozen-audio-fixture")
    fixture = tmp_path / "fixture.json"
    fixture.write_text(json.dumps([
        {"id": "image-1", "capability": "image", "media_path": image.name, "media_sha256": hashlib.sha256(image.read_bytes()).hexdigest(), "answer": "A"},
        {"id": "audio-1", "capability": "audio", "media_path": audio.name, "media_sha256": hashlib.sha256(audio.read_bytes()).hexdigest(), "answer": "B"},
    ]))
    predictions = tmp_path / "predictions.json"; predictions.write_text(json.dumps({"image-1": "A", "audio-1": "wrong"}))
    output = tmp_path / "result.json"; script = __import__("pathlib").Path(__file__).parents[1] / "scripts" / "ember_restart_eval_media_fixture.py"
    subprocess.run([sys.executable, str(script), "--fixture", str(fixture), "--predictions", str(predictions), "--output", str(output)], check=True)
    assert json.loads(output.read_text()) == {"result": "SELFTEST", "admission": "NOT_ELIGIBLE", "rows": [{"id": "image-1", "capability": "image", "correct": True}, {"id": "audio-1", "capability": "audio", "correct": False}], "correct": 1, "total": 2}
