# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import runpy
import sys

# Contamination probe targeting the ACTIVE round-1 core (1.5B re-stage,
# post-crash redesign): raw-prefix continuation membership + ID-recall on
# the base the q15 verdict serves from. Governed via t1_probe.load_model.
# GPU-serial: fire in a round-1 eval idle window, never beside a live job.
sys.argv = ["t1c_contamination.py",
            "--model", "Qwen/Qwen2.5-Coder-1.5B-Instruct"]
runpy.run_path("<local-path>",
               run_name="__main__")
