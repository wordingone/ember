# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Fixed prospective speed decision. No learning acceptance or installation."""
import math

BASE='b3ea8dd0504e2eb9afab4d8939577abaa1bf8e4e'
LAYERS=(0,2,13,22)
LENGTHS=(1024,1024,1024,1024)
LABELS=('A','A2','B','C','D','E')
ROUNDS=24
CALLS=2
MIN_REGION_GAIN=.20
MAX_BASELINE_DRIFT=.02
CLAIM='Independent v2 component speed screen; zero optimizer updates; no learning, whole-step or integration credit.'


def decide(rows,*,hardware_ok,ideal_ok):
    if type(hardware_ok) is not bool or type(ideal_ok) is not bool:
        raise ValueError('CHECKS: booleans required')
    if set(rows)!={str(i) for i in LAYERS}: raise ValueError('SUBJECTS: four fixed layers required')
    for r in rows.values():
        for k in ('region_gain','block_gain','baseline_drift'):
            if type(r[k]) not in (int,float) or not math.isfinite(r[k]): raise ValueError('TIMING: invalid metric')
        if type(r['checks_pass']) is not bool: raise ValueError('CHECKS: boolean required')
        if r['baseline_drift']<0: raise ValueError('TIMING: negative drift')
    correct=hardware_ok and all(r['checks_pass'] for r in rows.values())
    quiet=all(r['baseline_drift']<=MAX_BASELINE_DRIFT for r in rows.values())
    useful=all(r['region_gain']>=MIN_REGION_GAIN and r['block_gain']>r['baseline_drift'] for r in rows.values())
    status=('IMPLEMENTATION_CHECK_FAILED' if not correct else 'TIMING_INCONCLUSIVE' if not quiet
            else 'SPEED_JUSTIFIES_LEARNING_COMPARISON' if useful else 'NO_COMPONENT_GAIN')
    return dict(status=status,worth_learning_comparison=correct and quiet and useful,
                hardware_model_agreement=hardware_ok,original_ideal_gate_passed=ideal_ok,
                learning_qualified=False,trainer_integration_authorized=False,
                interpretation='Speed-prioritization screen for D only, not learning acceptance; A/A2 drift is not a confidence interval.')
