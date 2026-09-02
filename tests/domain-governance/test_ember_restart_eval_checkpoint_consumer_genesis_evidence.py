# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import tempfile
from pathlib import Path

from test_ember_restart_eval_checkpoint_consumer_v3_contract import invoke, write_v3


def test_rejects_missing_independent_expert_genesis_evidence_before_output():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        output = root / "receipt.json"
        manifest = write_v3(root)
        (root / "genesis" / "tool.json").unlink()
        completed = invoke(manifest, output)
        assert completed.returncode != 0
        assert not output.exists()
