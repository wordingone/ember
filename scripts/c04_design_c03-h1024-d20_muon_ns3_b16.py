"""c04_design_c03-h1024-d20_muon_ns3_b16.py — thin wrapper for muon_ns3 opt-variant bench.

Benches candidate c03-h1024-d20 with --opt-variant muon_ns3 --single-batch 16.
Do NOT git add / commit this file.
"""
import sys, os
sys.argv = [
    "c04_design_bench.py",
    "--candidate", "c03-h1024-d20",
    "--opt-variant", "muon_ns3",
    "--single-batch", "16",
]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from c04_design_bench import main
main()
