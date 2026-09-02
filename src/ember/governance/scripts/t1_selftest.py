# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import runpy
import sys

sys.argv = ["t1_probe.py", "--mode", "selftest"]
runpy.run_path("<local-path>",
               run_name="__main__")
