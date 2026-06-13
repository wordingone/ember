"""c04_design_c03-h1024-d20.py — train MCP wrapper for c04 design bench, candidate c03-h1024-d20."""
import sys, os
sys.argv = ["c04_design_bench.py", "--candidate", "c03-h1024-d20"]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from c04_design_bench import main
main()
