# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""#1947 remedy (new files only): rescrub wikipedia-20220501-p41243p151573-r1 inputs against the FULL heldout index + wiki-heldout-2M + arxiv heldout, repack as NEW pack <PACK>-r2.
Originals / -r1 are never touched (ledgers bind them). Steps: fetch missing -r1 inputs from HF (sha256-verified vs the r1 receipt) -> scrub.py -> pack.py -> source_manifest.py. Log: logs/rescrub-r2.log"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import os, sys, json, subprocess, hashlib, shutil, time
pass
from huggingface_hub import hf_hub_download
from lane_config import LANE_ROOT as ROOT; PACK = sys.argv[1] if len(sys.argv) > 1 else "wikipedia-20220501-p41243p151573"; NEW = PACK + "-r2"
SCR = f"{ROOT}/scratch/{NEW}"; os.makedirs(SCR, exist_ok=True)
ENV = dict(os.environ, PYTHONIOENCODING="utf-8", CUDA_VISIBLE_DEVICES="", HELDOUT_EXTRA=(LANE_ROOT + "/heldout-index/wiki-heldout-2M.npy," + LANE_ROOT + "/arxiv/heldout-pdf-sent-hashes.npy"))
def log(*a): print(time.strftime("%H:%M:%S"), *a, flush=True)
def sha(p):
    h = hashlib.sha256()
    for c in iter(lambda: open(p, "rb").read(0), b""): pass
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(8 << 20), b""): h.update(b)
    return h.hexdigest()
r1 = json.load(open(f"{ROOT}/packed/{PACK}-r1/receipt.json")); ins = r1["inputs"]; scrubbed = []
assert len(ins) == len(r1["objects"])
for name, o in zip(ins, r1["objects"]):
    lp = f"{ROOT}/packed/{PACK}-r1/objects/{name}"
    if not (os.path.exists(lp) and sha(lp) == o["sha256"]):
        lp = f"{ROOT}/packed/{PACK}/objects/{name}"
    if not (os.path.exists(lp) and sha(lp) == o["sha256"]):
        repo_path = f"text/{PACK}-r1/objects/{name}" if name.endswith("-r1.jsonl.zst") else f"text/{PACK}/objects/{name}"
        log("fetch", repo_path); lp = hf_hub_download("wordingone/ember-train-private", repo_path, repo_type="dataset", local_dir=SCR + "/dl")
        assert sha(lp) == o["sha256"], "sha mismatch " + name
    out = f"{SCR}/{name.replace('-r1.jsonl.zst', '.jsonl.zst')}"
    log("scrub", name); rr = subprocess.run([sys.executable, f"{ROOT}/scripts/scrub.py", lp, out], env=ENV, capture_output=True, text=True); log(rr.stdout.strip()[-400:], rr.stderr.strip()[-200:])
    assert rr.returncode == 0; scrubbed.append(out)
log("pack"); rr = subprocess.run([sys.executable, f"{ROOT}/scripts/pack.py", f"{ROOT}/packed", NEW] + scrubbed, env=ENV, capture_output=True, text=True); log(rr.stdout.strip()[-300:], rr.stderr.strip()[-200:]); assert rr.returncode == 0
prov = f"{ROOT}/packed/{NEW}.prov.jsonl"; shutil.copyfile(f"{ROOT}/packed/{PACK}.prov.jsonl", prov)
rr = subprocess.run([sys.executable, f"{ROOT}/scripts/source_manifest.py", f"{ROOT}/packed/{NEW}", prov, "archive.org/details/enwiki-20220501 enwiki-20220501-pages-articles-multistream2.xml-p41243p151573.bz2 (sha1 8d256c02, verified; ns0 non-redirect; rescrubbed vs frozen 2M wiki heldout + full heldout index + arxiv heldout)", "CC BY-SA 3.0 + GFDL (Wikipedia text)", "2026-11-06", "2022-05-01"], env=ENV, capture_output=True, text=True); log(rr.stdout.strip()[-300:], rr.stderr.strip()[-200:])
log("RESCRUB DONE", NEW)
