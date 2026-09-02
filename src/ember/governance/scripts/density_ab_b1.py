# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""density_ab_b1.py — arm=b seed=1 wrapper for train MCP dispatch."""
import sys, os
sys.argv = ["density_ab_bench.py", "--arm", "b", "--seed", "1"]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from density_ab_bench import main
main()
