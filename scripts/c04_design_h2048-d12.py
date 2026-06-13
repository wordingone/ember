"""c04_design_h2048-d12.py — train MCP wrapper for c04 design bench, candidate h2048-d12."""
import sys, os
sys.argv = ["c04_design_bench.py", "--candidate", "h2048-d12"]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from c04_design_bench import main
main()
