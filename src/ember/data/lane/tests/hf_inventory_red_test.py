# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Red/green test for hf_inventory (lead 81645 item 1). Offline: no HF calls.
RED condition: a planted duplicate must show up as overlap_items>0 and overlap_bytes>0; a clean set must give 0. Classification must keep checkpoints out of data."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from lane_config import LANE_ROOT
import sys, importlib.util
spec = importlib.util.spec_from_file_location("inv", (LANE_ROOT + "/scripts/hf_inventory.py")); inv = importlib.util.module_from_spec(spec); spec.loader.exec_module(inv)
ok = True
def check(name, cond):
    global ok; print(("PASS " if cond else "FAIL ") + name); ok &= bool(cond)
clean = [("a" * 64, 100, "raw"), ("b" * 64, 200, "public"), ("c" * 64, 50, "train")]
u = inv.uniq_stats(clean); check("clean set: overlap 0", u["overlap_items"] == 0 and u["overlap_bytes"] == 0 and u["unique_items"] == 3)
dup = clean + [("b" * 64, 200, "raw")]                    # same bytes in two repos
u = inv.uniq_stats(dup); check("planted cross-repo duplicate: overlap 1 item / 200 B", u["overlap_items"] == 1 and u["overlap_bytes"] == 200 and u["items"] == 4 and u["unique_items"] == 3)
dup2 = clean + [("a" * 64, 100, "raw")]                   # same bytes twice in one repo
check("planted in-repo duplicate counted", inv.uniq_stats(dup2)["overlap_items"] == 1)
check("checkpoints excluded from data", inv.classify("public", "checkpoints/lineage-2119/step1/model.safetensors")[0] == "excluded")
check("heldout kept separate from training", inv.classify("public", "objects/heldout/x.tar.gz")[0] == "heldout" and inv.classify("public", "objects/train/x.tar.gz")[0] == "raw")
check("shards are train_ready text", inv.classify("train", "text/pg-00000-00000/shards/v1-00000-ab.bin")[:2] == ("train_ready", "text"))
check("mp3 is audio raw", inv.classify("raw", "audio/librivox/1055/lv1055-s1.mp3")[:2] == ("raw", "audio"))
check("image classified", inv.classify("public", "sources/wikimedia-commons-pd/File__x.jpg")[:2] == ("raw", "image"))
print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)
