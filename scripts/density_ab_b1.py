"""density_ab_b1.py — arm=b seed=1 wrapper for train MCP dispatch."""
import sys, os
sys.argv = ["density_ab_bench.py", "--arm", "b", "--seed", "1"]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from density_ab_bench import main
main()
