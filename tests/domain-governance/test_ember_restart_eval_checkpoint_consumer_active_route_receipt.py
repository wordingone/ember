# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json
import tempfile
from pathlib import Path

from test_ember_restart_eval_checkpoint_consumer_v3_contract import invoke, write_v3


def test_verified_checkpoint_receipt_carries_the_closed_active_route():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        output = root / "receipt.json"

        completed = invoke(write_v3(root), output)

        assert completed.returncode == 0, completed.stderr
        assert json.loads(output.read_text(encoding="utf-8"))["active_expert_ids"] == ["tool"]
