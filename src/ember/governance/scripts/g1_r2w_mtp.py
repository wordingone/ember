# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import runpy
import sys

# G1 eval, W-code r2, arm: mtp. Validation split (43 heldout), k=8
# seed 16 (same eval seed as r1 G1 -> paired deltas + cross-round
# comparability; strict-verify stack now in-path by default, eng-24).
NC = "<local-path>"
sys.argv = ["w1_mbpp.py",
            "--model", "Qwen/Qwen2.5-Coder-3B-Instruct",
            "--split", "validation", "--k", "8", "--batch-size", "8",
            "--temp", "0.8", "--seed", "16", "--tag", "g1r2-mtp",
            "--adapter", "<local-path>"]
runpy.run_path(f"{NC}/src/ember/governance/scripts/w1_mbpp.py", run_name="__main__")
