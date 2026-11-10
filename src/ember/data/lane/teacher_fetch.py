# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Fetch one teacher's main-branch weights at a pinned revision, sha256-verify every LFS file against the HF API, record in audit/teacher-licences/VERIFIED.md fetch log.
Usage: teacher_fetch.py REPO REV DEST   (e.g. Qwen/Qwen3-8B b968826d9c46dd6066d109eabc6255188de91218 A:/ember-stage/teachers/Qwen3-8B)
Refuses if the main files exceed 100 GB or the drive would drop below floor (A >= 12 GiB, B >= 301 GiB). Writes DEST/FETCH.done on success."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import sys, os, json, hashlib, shutil, time
from huggingface_hub import HfApi, hf_hub_download
repo, rev, dest = sys.argv[1:4]
api = HfApi(); info = api.model_info(repo, revision=rev, files_metadata=True)
files = [s for s in info.siblings if not s.rfilename.startswith(("original/", "onnx/")) and (s.rfilename.endswith((".safetensors", ".json", ".txt", ".model", ".md")) or s.rfilename in ("LICENSE", "merges.txt", "vocab.json"))]
need = sum(s.size or 0 for s in files); print("files", len(files), "bytes", need)
assert need < 100 * 2**30, "over 100 GB: needs lead"
free = shutil.disk_usage(dest[:3]).free
pass; import reserve_plan   # single B: floor source (lead 82070)
floor = (12 if dest.upper().startswith("A:") else reserve_plan.floor_gib()) * 2**30
assert free - need > floor, f"would drop below floor: free {free/2**30:.1f} GiB need {need/2**30:.1f}"
os.makedirs(dest, exist_ok=True); rows = []
for s in files:
    p = hf_hub_download(repo, s.rfilename, revision=rev, local_dir=dest)
    want = getattr(s.lfs, "sha256", None) if s.lfs else None
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 24), b""): h.update(b)
    ok = (want is None) or (h.hexdigest() == want)
    rows.append(dict(file=s.rfilename, size=s.size, sha256=h.hexdigest(), lfs_sha256=want, verified=ok))
    assert ok, "sha mismatch " + s.rfilename
json.dump(dict(repo=repo, revision=rev, fetched=time.strftime("%Y-%m-%dT%H:%M:%S"), files=rows), open(dest + "/FETCH-receipt.json", "w"), indent=1)
open(dest + "/FETCH.done", "w").write("ok")
print("DONE free after GiB", shutil.disk_usage(dest[:3]).free / 2**30)
