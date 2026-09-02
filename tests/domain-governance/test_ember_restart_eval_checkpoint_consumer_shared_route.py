# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json
import tempfile
from pathlib import Path

from test_ember_restart_eval_checkpoint_consumer_v3_contract import invoke, write_v3


def _write_shared_manifest(root: Path, *, active_parameters: int) -> Path:
    manifest = write_v3(root)
    content = json.loads(manifest.read_text(encoding="utf-8"))
    content["active_expert_ids"] = ["shared"]
    content["architecture"]["active_parameters"] = active_parameters
    content["architecture"]["episode_trainable_parameters"] = active_parameters
    manifest.write_text(json.dumps(content), encoding="utf-8")
    return manifest


def test_accepts_shared_route_with_authorized_active_parameter_count():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        output = root / "receipt.json"
        completed = invoke(_write_shared_manifest(root, active_parameters=1020589568), output)

        assert completed.returncode == 0, completed.stderr
        assert output.exists()


def test_rejects_shared_route_with_specialist_active_parameter_count_before_output():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        output = root / "receipt.json"
        completed = invoke(_write_shared_manifest(root, active_parameters=1725232640), output)

        assert completed.returncode != 0
        assert not output.exists()
