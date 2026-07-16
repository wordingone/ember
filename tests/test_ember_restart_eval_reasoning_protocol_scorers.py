# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def test_arc_and_mmlu_protocols_pin_their_deterministic_scorer_bytes():
 expected={'ember-restart-arc-challenge-protocol-v1.json':'scripts/ember_restart_eval_arc_challenge.py','ember-restart-mmlu-pro-protocol-v1.json':'scripts/ember_restart_eval_mmlu_pro_score.py','ember-restart-gsm8k-protocol-v1.json':'scripts/ember_restart_eval_gsm8k_score.py'}
 for manifest_name,relative in expected.items():
  protocol=json.loads((ROOT/'manifests'/manifest_name).read_text(encoding='utf-8'))
  scorer=protocol['scoring_adapter']
  assert scorer['path']==relative
  assert scorer['sha256']==hashlib.sha256((ROOT/relative).read_bytes()).hexdigest()
  assert scorer['result_disposition']=='PREFLIGHT_ONLY_NON_ADMISSIBLE'