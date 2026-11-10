# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Sample stackexchange 7z yield: download 3 mid-size sites (one thread), measure compressed->Posts.xml bytes->clean body chars (html stripped, entity-decoded). Output logs/yield-se-sample.json"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import HF_RAW_REPO, LANE_ROOT
import os, re, json, html, shutil, sys
from huggingface_hub import HfApi, hf_hub_download
import py7zr
api = HfApi(); R = ("wordingone/" + HF_RAW_REPO); D = (LANE_ROOT + "/scratch/se-sample")
fs = sorted((t.size, t.path) for t in api.list_repo_tree(R, repo_type="dataset", path_in_repo="text/stackexchange-20221005") if hasattr(t, "size"))
picks = [next(f for f in fs if f[0] > x) for x in (20e6, 60e6, 120e6)]
tag = re.compile(r"<[^>]+>"); body = re.compile(r'Body="([^"]*)"')
out = []
for sz, p in picks:
    os.makedirs(D, exist_ok=True); lp = hf_hub_download(R, p, repo_type="dataset", local_dir=D)
    ed = D + "/x"; shutil.rmtree(ed, ignore_errors=True); os.makedirs(ed)
    with py7zr.SevenZipFile(lp) as z: z.extract(path=ed, targets=[n for n in z.getnames() if n.lower() == "posts.xml"])
    px = ed + "/Posts.xml"; raw = os.path.getsize(px); chars = 0; n = 0
    for l in open(px, encoding="utf-8", errors="ignore"):
        m = body.search(l)
        if m: chars += len(tag.sub(" ", html.unescape(m.group(1)))); n += 1
    out.append(dict(path=p, comp=sz, posts_xml=raw, posts=n, clean_chars=chars, clean_per_comp=round(chars / sz, 2)))
    print(out[-1], flush=True); shutil.rmtree(D, ignore_errors=True)
json.dump(out, open((LANE_ROOT + "/logs/yield-se-sample.json"), "w"), indent=1)
tot_c = sum(o["comp"] for o in out); tot_ch = sum(o["clean_chars"] for o in out)
print("clean chars per compressed byte", round(tot_ch / tot_c, 2), "=> est tokens for 18.3 GiB:", round(18.3 * 2**30 * tot_ch / tot_c / 4.2 / 1e9, 2), "B (chars/4.2)")
