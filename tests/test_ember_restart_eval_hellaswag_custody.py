# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json
from pathlib import Path
MANIFEST=Path(__file__).resolve().parents[1]/"manifests"/"ember-restart-hellaswag-custody-v1.json"
def test_hellaswag_custody_binds_unlabeled_test_inputs_without_substituting_inherited_pin():
 value=json.loads(MANIFEST.read_text(encoding="utf-8"))
 assert value['materialization']=={'upstream_revision':'218ec52e09a7e7462a5400043bb9a69a41d06b76','artifact_sha256':'2ff0c32b7ce1deb99ba2b0e20a053dd6579851b74ced15b43cad7128a7478546','runner_receipt_sha256':'160b8eecd6c147bf6025b4a49c8eafd238429bdbd71f2f05527c19da53656995','split_sha256':'e572fd5579bd1768b1985f47234f8bbe29247aca200a778b635bffc637714a41','claim_status':'FROZEN_HELLASWAG_TEST_INPUTS_NO_FROZEN_LABELS'}
 assert value['admission']=='NOT_EXECUTABLE_NO_FROZEN_LABELS'
 assert value['inherited_template_compatibility']=='HASH_MISMATCH_SEPARATE_NONEXECUTABLE_CUSTODY'