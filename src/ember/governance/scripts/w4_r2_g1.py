# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import runpy
import sys

# G1, round-2 W-code: ALL FIVE ARMS paired in one governed job (prereg
# §1.3 — w4_eval on MBPP sanitized VALIDATION, paired bootstrap + exact
# methods; stats_exact Newcombe BINDING for zero-inflated). Seed 16 =
# the r1 G1 eval seed (cross-round comparability). Dispatch ONLY after
# all four trained arms' receipts exist (GPU-serial precedent).
NC = "<local-path>"
sys.argv = ["w4_eval.py",
            "--model", "Qwen/Qwen2.5-Coder-3B-Instruct",
            "--arm", "base=",
            "--arm", f"sft={NC}/adapters/r2-q3-sft",
            "--arm", f"mtp={NC}/adapters/r2-q3-mtp",
            "--arm", f"grpo={NC}/adapters/r2-q3-grpo",
            "--arm", f"control={NC}/adapters/r2-q3-control",
            "--split", "validation", "--k", "8", "--batch-size", "8",
            "--temp", "0.8", "--seed", "16", "--tag", "r2w-q3"]
sys.path.insert(0, f"{NC}/scripts")
runpy.run_path(f"{NC}/src/ember/governance/scripts/w4_eval.py", run_name="__main__")
