# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json,hashlib
from pathlib import Path
MANIFEST=Path(__file__).resolve().parents[1]/"manifests"/"ember-restart-mmlu-pro-custody-v1.json"
def test_mmlu_pro_custody_preserves_current_raw_split_as_separate_from_inherited_pin():
 value=json.loads(MANIFEST.read_text(encoding="utf-8"))
 assert value['materialization']=={'upstream_revision':'b189ec765aa7ed75c8acfea42df31fdae71f97be','artifact_sha256':'3577c66990ac2d1cc396d49c6d6b4d3c0b24e160915885b0f9e3b3d0f0577514','runner_receipt_sha256':'0b34ba0415efdad6b07d05379a742ca8204183233998df3394f2cac8139416c5','split_sha256':'0e24a191921c2f453518a537a8b2117bd137e7714d4ef1565e9ba06c1ecb9ad8','claim_status':'FROZEN_MMLU_PRO_TASKS_NO_CHECKPOINT_BOUND_PREDICTIONS'}
 assert value['inherited_template_compatibility']=='HASH_MISMATCH_SEPARATE_NONEXECUTABLE_CUSTODY'
 assert value['target_execution_permitted'] is False

def test_public_mmlu_pro_protocol_connects_strict_freezer_and_custody_authority():
 protocol=json.loads((MANIFEST.parent/'ember-restart-mmlu-pro-protocol-v1.json').read_text(encoding='utf-8'))
 adapter=hashlib.sha256((MANIFEST.parents[1]/'scripts'/'ember_restart_eval_mmlu_pro_score.py').read_bytes()).hexdigest()
 assert protocol['strict_protocol_required'] is True
 assert protocol['benchmark_version']==protocol['benchmark_revision']
 assert protocol['scoring_adapter']['sha256']==adapter
 assert protocol['references_sha256']==json.loads(MANIFEST.read_text(encoding='utf-8'))['materialization']['split_sha256']


def test_public_mmlu_pro_protocol_content_addresses_its_custody_manifest():
 protocol=json.loads((MANIFEST.parent/'ember-restart-mmlu-pro-protocol-v1.json').read_text(encoding='utf-8'))
 custody_bytes=MANIFEST.read_bytes()
 assert protocol['custody_manifest_path']=='manifests/ember-restart-mmlu-pro-custody-v1.json'
 assert protocol['custody_manifest_sha256']==hashlib.sha256(custody_bytes).hexdigest()
