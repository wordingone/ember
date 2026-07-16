# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def test_mmmu_custody_pins_canonical_image_scorer_bytes():
 v=json.loads((ROOT/'manifests'/'ember-restart-mmmu-validation-custody-v1.json').read_text());a=v['scoring_adapter'];assert a['path']=='scripts/ember_restart_eval_mmmu.py';assert a['sha256']==hashlib.sha256((ROOT/a['path']).read_bytes()).hexdigest();assert a['result_disposition']=='PREFLIGHT_ONLY_NON_ADMISSIBLE'