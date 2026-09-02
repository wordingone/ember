# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import runpy
import sys

# Matched-budget control arm for the small-core round-1 re-stage:
# same control_pool, same example counts per task as the -q15 core arm.
# Launches ONLY on the t2-r1-q15 receipt (GPU-serial).
sys.argv = ["t2_round.py", "--round", "1", "--control",
            "--model", "Qwen/Qwen2.5-Coder-1.5B-Instruct",
            "--tag-suffix=-q15"]
runpy.run_path("<local-path>",
               run_name="__main__")
