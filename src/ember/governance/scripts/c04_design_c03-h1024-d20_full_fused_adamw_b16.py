# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""c04_design_c03-h1024-d20_full_fused_adamw_b16.py — wrapper for full_fused_adamw single-batch bench.

Forwards --opt-variant full_fused_adamw --single-batch 16 to c04_design_bench.py.
Do NOT git add/commit this file.
"""
import sys, os
sys.argv = [
    "c04_design_bench.py",
    "--candidate", "c03-h1024-d20",
    "--opt-variant", "full_fused_adamw",
    "--single-batch", "16",
]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from c04_design_bench import main
main()
