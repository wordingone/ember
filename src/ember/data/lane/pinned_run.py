# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Run a lane script pinned like tick.py spawn() does: CPUs 16-23 (mask 0x00FF0000), BelowNormal, CUDA hidden. Usage: python scripts/pinned_run.py script.py args..."""
import os, sys, ctypes, runpy
os.environ["CUDA_VISIBLE_DEVICES"] = ""
k = ctypes.windll.kernel32; k.GetCurrentProcess.restype = ctypes.c_void_p; k.SetProcessAffinityMask.argtypes = [ctypes.c_void_p, ctypes.c_size_t]; k.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint]
k.SetProcessAffinityMask(k.GetCurrentProcess(), 0x00FF0000); k.SetPriorityClass(k.GetCurrentProcess(), 0x4000)
sys.argv = sys.argv[1:]; runpy.run_path(sys.argv[0], run_name="__main__")
