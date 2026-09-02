# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import tempfile
from pathlib import Path

from test_ember_restart_eval_checkpoint_consumer_v3_contract import EXPERTS, invoke, write_v3


def test_rejects_duplicate_expert_genesis_hashes_before_output():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        output = root / "receipt.json"
        completed = invoke(write_v3(root, mutate=lambda manifest: manifest["expert_genesis_sha256"].update({name: "e" * 64 for name in EXPERTS})), output)
        assert completed.returncode != 0
        assert not output.exists()
