# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import runpy
import sys

# Replication seed for the small-core round-1 verdict (chunked, governed).
# Launches ONLY on the s14 receipt (GPU-serial).
sys.argv = ["t4_chunked.py", "--round", "1", "--surface", "arc1",
            "--seed", "15", "--n-tasks", "100", "--k", "8",
            "--chunk-size", "25", "--min-tasks-stop", "50",
            "--model", "Qwen/Qwen2.5-Coder-1.5B-Instruct",
            "--tag-suffix=-q15"]
runpy.run_path("<local-path>",
               run_name="__main__")
