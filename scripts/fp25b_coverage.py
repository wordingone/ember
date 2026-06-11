import runpy
import sys

# fp-25 Surface-B SELECTION leg: uniform base-only theta coverage over the
# full w4_eval --split train sanitized pool (120 tasks x k8 = 960 — w1 split
# discipline; NOT raw-MBPP 374, wording corrected per monitor audit 14579;
# n_tasks proven by the terminal receipt). Feasibility receipt 2026-06-11:
# pooled-q3
# round-1 coverage leaves only 2 held-out frontier candidates (theta in
# (0,0.5] outside the sft+grpo training union) — the r2 frontier filter
# selected the known frontier INTO training by construction. Surface B needs
# fresh uniform coverage to find held-out frontier tasks. Base arm only (no
# adapter): selection uses base outcomes exclusively, so arm deltas on the
# eventual B set carry no selection-on-outcome bias. Seed 16 = the G1/recall
# eval seed (same sampling regime as the arms will face).
NC = "/mnt/b/M/avir/leo/state/nc-ladder"
sys.argv = ["w4_eval.py",
            "--model", "Qwen/Qwen2.5-Coder-3B-Instruct",
            "--arm", "base=",
            "--split", "train",
            "--k", "8", "--batch-size", "8",
            "--temp", "0.8", "--seed", "16", "--tag", "fp25b-cov"]
sys.path.insert(0, f"{NC}/scripts")
runpy.run_path(f"{NC}/scripts/w4_eval.py", run_name="__main__")
