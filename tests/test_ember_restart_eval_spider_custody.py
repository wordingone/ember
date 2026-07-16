# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json
from pathlib import Path
MANIFEST=Path(__file__).resolve().parents[1]/'manifests'/'ember-restart-spider-custody-v1.json'
def test_spider_custody_binds_fresh_source_only_audit_and_explicit_execution_hold():
 value=json.loads(MANIFEST.read_text(encoding='utf-8'))
 assert value['source_only_audit']=={'artifact_sha256':'ac3f513e8e6a2436379b5db85269c86568f81285e7dd9603aa66c2d244895e31','runner_receipt_sha256':'476348c1ad82995a3824e55eb19cedee70c782b219ea750dfa5aaee127aeb0f2','claim_status':'SOURCE_ONLY_NO_FROZEN_SQL_EVALUATION_ASSETS'}
 assert value['frozen_evaluation_assets']=={'gold_sql':'ABSENT','tables_json':'ABSENT','database_directory':'ABSENT','examples':'SOURCE_EXAMPLES_ONLY_FORBIDDEN_AS_EVALUATION_DATA'}
 assert value['admission']=='NOT_EXECUTABLE_NO_FROZEN_GOLD_AND_DATABASE'