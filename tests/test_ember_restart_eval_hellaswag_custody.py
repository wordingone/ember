# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json
from pathlib import Path
MANIFEST=Path(__file__).resolve().parents[1]/"manifests"/"ember-restart-hellaswag-custody-v1.json"
def test_hellaswag_custody_binds_unlabeled_test_inputs_without_substituting_inherited_pin():
 value=json.loads(MANIFEST.read_text(encoding="utf-8"))
 assert value['materialization']=={'upstream_revision':'218ec52e09a7e7462a5400043bb9a69a41d06b76','artifact_sha256':'38eac5ab4ba9209cd8814123663203657a9a4c1745e7685bb3eb95a7acb1487f','runner_receipt_sha256':'efa3958273ad01f40862694ebd688b52fefb5751a84641a8dfac681b0100e9d8','split_sha256':'e572fd5579bd1768b1985f47234f8bbe29247aca200a778b635bffc637714a41','claim_status':'FROZEN_HELLASWAG_TEST_INPUTS_NO_FROZEN_LABELS'}
 assert value['admission']=='NOT_EXECUTABLE_NO_FROZEN_LABELS'
 assert value['inherited_template_compatibility']=='HASH_MISMATCH_SEPARATE_NONEXECUTABLE_CUSTODY'