# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def test_terminal_bench_custody_pins_fixture_scorer_and_remains_ineligible():
 v=json.loads((ROOT/'manifests'/'ember-restart-terminal-bench-custody-v1.json').read_text());a=v['scoring_adapter'];assert a['path']=='scripts/ember_restart_eval_terminal_bench.py';assert a['sha256']==hashlib.sha256((ROOT/a['path']).read_bytes()).hexdigest();assert a['result_disposition']=='SELFTEST_ONLY_NON_ADMISSIBLE';assert v['eligibility']['eligible_task_count']==0 and v['target_execution_permitted'] is False