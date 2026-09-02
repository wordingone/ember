# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import runpy
import sys

# 3B fallback second held-out transfer surface (ARC-AGI-2 eval, all 120
# tasks; chunked, governed). Launches ONLY on the q3 s15 receipt
# (GPU-serial).
sys.argv = ["t4_chunked.py", "--round", "1", "--surface", "arc2",
            "--seed", "14", "--n-tasks", "120", "--k", "8",
            "--chunk-size", "25", "--min-tasks-stop", "50",
            "--model", "Qwen/Qwen2.5-Coder-3B-Instruct",
            "--tag-suffix=-q3"]
runpy.run_path("<local-path>",
               run_name="__main__")
