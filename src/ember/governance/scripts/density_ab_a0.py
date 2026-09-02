"""density_ab_a0.py — arm=a seed=0 wrapper for train MCP dispatch."""
import sys, os
sys.argv = ["density_ab_bench.py", "--arm", "a", "--seed", "0"]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from density_ab_bench import main
main()
