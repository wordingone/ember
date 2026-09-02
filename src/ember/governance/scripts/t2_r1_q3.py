# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import runpy
import sys

# 3B fallback round-1 core arm: identical 1,909-episode ledger dataset
# (--train-only), adapter tag -q3. Launches ONLY on the q3 smoke receipt.
sys.argv = ["t2_round.py", "--round", "1", "--train-only",
            "--model", "Qwen/Qwen2.5-Coder-3B-Instruct",
            "--tag-suffix=-q3"]
runpy.run_path("<local-path>",
               run_name="__main__")
