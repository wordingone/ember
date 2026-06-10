import runpy
import sys

# Layer 1b: train-split baseline, chunked/resumable (replaces killed
# 57e1d01f). Defaults: 400 tasks x k=16 in 8 chunks of 50 tasks (~1h each);
# resume = relaunch this same wrapper. Run in idle windows AFTER the round-1
# eval sequence — GPU-serial with everything else.
sys.argv = ["t1_chunked.py"]
runpy.run_path("/mnt/b/M/avir/leo/state/nc-ladder/scripts/t1_chunked.py",
               run_name="__main__")
