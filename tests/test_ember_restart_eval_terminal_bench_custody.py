# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def test_terminal_bench_custody_pins_fixture_scorer_and_remains_ineligible():
 v=json.loads((ROOT/'manifests'/'ember-restart-terminal-bench-custody-v1.json').read_text());a=v['scoring_adapter'];assert a['path']=='scripts/ember_restart_eval_terminal_bench.py';assert a['sha256']==hashlib.sha256((ROOT/a['path']).read_bytes()).hexdigest();assert a['result_disposition']=='SELFTEST_ONLY_NON_ADMISSIBLE';assert v['eligibility']['eligible_task_count']==0 and v['target_execution_permitted'] is False

def test_terminal_bench_custody_records_the_fail_closed_image_and_network_boundary():
 v=json.loads((ROOT/'manifests'/'ember-restart-terminal-bench-custody-v1.json').read_text())
 contract=v['eligibility_contract']
 assert contract['required_image_form']=='<registry>/<name>@sha256:<64 lowercase hex>'
 assert contract['required_allow_internet'] is False
 assert contract['observed_cache_audit']=={'task_count':89,'digest_pinned_image_task_count':0,'network_disabled_task_count':0,'eligible_task_count':0,'task_manifest_sha256':'3a0c0127df1aab9c05c60c5bc08d1c7f2ab701e913614ec5b41082fd81c1e694','reason':'all cached task.toml records use mutable image tags and allow_internet=true'}
 assert v['goal_id']=='EMBER-02' and v['workstream_id']=='EMBER-02C'
 a=v['cache_audit']; assert a['path']=='scripts/ember_restart_eval_terminal_bench_cache_audit.py'; assert a['sha256']==hashlib.sha256((ROOT/a['path']).read_bytes()).hexdigest(); assert a['task_manifest_sha256']=='3a0c0127df1aab9c05c60c5bc08d1c7f2ab701e913614ec5b41082fd81c1e694'

def test_terminal_bench_public_custody_exposes_derived_protocol_identity():
 v=json.loads((ROOT/'manifests'/'ember-restart-terminal-bench-custody-v1.json').read_text())
 assert v['strict_protocol_required'] is True
 assert v['scoring_adapter_path']=='scripts/ember_restart_eval_terminal_bench.py'
 identity={k:v[k] for k in ('benchmark_id','benchmark_version','source_commit','source_tree','license_sha256','scoring_adapter_path')}
 identity['scoring_adapter_sha256']=v['scoring_adapter']['sha256']
 assert hashlib.sha256(json.dumps(identity,sort_keys=True,separators=(',',':')).encode()).hexdigest()==v['protocol_sha256']
