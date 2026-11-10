# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Raw-backlog yield: sample issue1719 train tarballs by range-reading the first ~12 MB of each .tar.gz (no full download): member names/extensions, text-like share, chars per member, licence cues. Out logs/tar-sample-20261109.json"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import io, gzip, tarfile, zlib, json, requests, collections, re
from huggingface_hub import hf_hub_url, get_token
H = {"Authorization": "Bearer " + (get_token() or "")}; R = "wordingone/ember-raw-private"
FILES = ["train/issue1719-github-license-partitions-20260818T0550Z__F-train-2.tar.gz", "train/issue1719-github-license-partitions-20260818T0550Z__H-train-2.tar.gz", "train/issue1719-license-partitions-wave10-20260819T0215Z__H-train-1.tar.gz", "train/issue1719-wide-wave-20260818T1436Z__K-train-2.tar.gz", "train/issue1719-wide-wave-20260818T1436Z__license-partitions.tar.gz"]
out = {}
for f in FILES:
    b = requests.get(hf_hub_url(R, f, repo_type="dataset"), headers=dict(H, Range="bytes=0-12000000"), timeout=120).content
    raw = zlib.decompressobj(31).decompress(b); ext = collections.Counter(); n = chars = textn = 0; names = []
    try:
        tf = tarfile.open(fileobj=io.BytesIO(raw), mode="r:")
        for m in tf:
            if not m.isfile(): continue
            n += 1; e = re.sub(r".*\.", ".", m.name) if "." in m.name else "(none)"; ext[e] += 1
            if len(names) < 4: names.append(m.name[-90:])
            try:
                d = tf.extractfile(m).read()
            except Exception: break
            if b"\x00" not in d[:2000]: textn += 1; chars += len(d)
    except Exception as e: names.append("ERR " + type(e).__name__)
    out[f.split("/")[-1]] = dict(sampled_members=n, text_members=textn, text_bytes=chars, top_ext=ext.most_common(6), names=names, decompressed_mb=round(len(raw) / 2**20, 1), ratio=round(len(raw) / max(1, len(b)), 2))
    print(f.split("/")[-1][-50:], out[f.split("/")[-1]], flush=True)
json.dump(out, open((LANE_ROOT + "/logs/tar-sample-20261109.json"), "w"), indent=1)
