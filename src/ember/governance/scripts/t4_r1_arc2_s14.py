# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import runpy
import sys

sys.argv = ["t4_eval.py", "--round", "1", "--seed", "14", "--surface", "arc2",
            "--n-tasks", "120"]
runpy.run_path("<local-path>",
               run_name="__main__")
