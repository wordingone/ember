# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import runpy
import sys

# k=16 not 32: SOAR (2507.14172) measures +0.36%/doubling for the base model —
# the extra ~12h buys nothing; purpose is baseline-of-record + control-pool
# harvest + free episodes, not k-scaling. batch 16 = VRAM-safe unattended.
sys.argv = ["t1_probe.py", "--mode", "full", "--k", "16",
            "--batch-size", "16", "--max-new", "1024",
            "--model", "unsloth/Qwen2.5-Coder-7B-Instruct"]
runpy.run_path("<local-path>",
               run_name="__main__")
