# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json
from pathlib import Path
MANIFEST=Path(__file__).resolve().parents[1]/"manifests"/"ember-restart-gsm8k-custody-v1.json"
def test_gsm8k_custody_preserves_inherited_template_hash_incompatibility():
 value=json.loads(MANIFEST.read_text(encoding="utf-8"))
 assert value["materialization"]=={"upstream_revision":"740312add88f781978c0658806c59bc2815b9866","artifact_sha256":"6eb8577c00d48aebc4f55bfbe76de49880b29f1adbd599c0bfd127a02f4a1019","runner_receipt_sha256":"a12c8f72324eb0dbd6d426d90fb2261eb9cd2ed983fde9866a1476b9762f2aff","split_sha256":"ee7b8da9e381df27b9e3f7758a159ab2bdaa4dbaa910546cbbc47e0cb44e4f59","claim_status":"FROZEN_GSM8K_TASKS_NO_CHECKPOINT_BOUND_PREDICTIONS"}
 assert value["inherited_template_compatibility"]=="HASH_MISMATCH_SEPARATE_NONEXECUTABLE_CUSTODY"
 assert value["target_execution_permitted"] is False