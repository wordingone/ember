# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json
import tempfile
from pathlib import Path

from test_ember_restart_eval_checkpoint_consumer_v3_contract import invoke, write_v3


def test_rejects_model_config_optimizer_substitution_before_output():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        manifest = write_v3(root)
        config = root / "config.json"
        config.write_text(json.dumps({"training": {"optimizer": {"name": "substituted"}}}), encoding="utf-8")
        output = root / "receipt.json"
        completed = invoke(manifest, output)
        assert completed.returncode != 0
        assert not output.exists()
