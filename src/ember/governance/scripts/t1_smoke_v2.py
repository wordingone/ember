# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import runpy
import sys

sys.argv = ["t1_probe.py", "--mode", "smoke", "--n-tasks", "30", "--k", "16",
            "--batch-size", "16", "--max-new", "1024",
            "--model", "unsloth/Qwen2.5-Coder-7B-Instruct"]
runpy.run_path("<local-path>",
               run_name="__main__")
