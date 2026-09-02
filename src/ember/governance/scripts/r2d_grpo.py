# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import runpy
import sys

# Round-2 W GRPO arm (verifier reward, theta=0.5 frontier window, stats
# from the round-2 w1 floor receipts) via the #112 wrapper. GPU-serial.
NC = "<local-path>"
sys.argv = ["t2_r2_grpo.py", "--the lead-gate-token", "r2-prereg-20260611-the lead"]
sys.path.insert(0, f"{NC}/scripts")
runpy.run_path(f"{NC}/src/ember/governance/scripts/t2_r2_grpo.py", run_name="__main__")
