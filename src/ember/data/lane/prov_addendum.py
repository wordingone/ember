# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""lead 81995-approved: provenance-addendum.json for packs whose source-manifest lacks an exact upstream revision. HF-sourced: last upstream commit <= end of fetch_date window (HfApi.list_repo_commits);
wikipedia: dump file + sha1 quoted in the manifest origin; arxiv: sha256 of provenance-per-paper.jsonl if present. Writes packed/<name>/provenance-addendum.json (new file only; receipts/manifests/objects untouched)."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import os, sys, json, re, hashlib, glob
from huggingface_hub import HfApi
api = HfApi(); LA = json.load(open((LANE_ROOT + "/logs/licence-audit-20261109.json"))); BASE = (LANE_ROOT + "/packed/")
REPO = {"loc": "storytracer/LoC-PD-Books", "pes2o": "common-pile/peS2o", "pubmed": "common-pile/pubmed"}
def sha(p):
    h = hashlib.sha256(); h.update(open(p, "rb").read()); return h.hexdigest()
for n, v in LA.items():
    if v["version_hash"]: continue
    out = dict(pack=n, recorded="2026-11-09", note="addendum; source-manifest/receipt unchanged")
    fd_end = (v["fetch_dates"][0].split("..")[-1] or "")[:10] + "T23:59:59"
    k = n.split("-")[0]
    if k in REPO:
        cm = api.list_repo_commits(REPO[k], repo_type="dataset"); pick = None
        for c in cm:
            if c.created_at.strftime("%Y-%m-%dT%H:%M:%S") <= fd_end: pick = c; break
        out.update(upstream=REPO[k], upstream_revision=pick.commit_id if pick else None, revision_committed_at=str(pick.created_at) if pick else None, rule="last upstream commit at or before end of the fetch_date window " + v["fetch_dates"][0],
                   caveat="derived from commit history, not recorded at download time; the lane downloaded from the default branch")
    elif k == "wikipedia":
        o = json.loads(open(BASE + n + "/source-manifest.jsonl", encoding="utf-8").readline())["origin"]; m = re.search(r"enwiki-\S+\.bz2.*?sha1 ([0-9a-f]{8,40})", o)
        out.update(upstream="archive.org enwiki-20220501", dump_file=re.search(r"(enwiki-\S+\.bz2)", o).group(1) if re.search(r"(enwiki-\S+\.bz2)", o) else None, sha1_prefix=m.group(1) if m else None, origin_text=o[:400])
    elif k == "arxiv":
        pp = [p for p in glob.glob((LANE_ROOT + "/arxiv/**/provenance-per-paper.jsonl"), recursive=True)][:1]
        out.update(upstream="arxiv.org PDFs + OAI-PMH", provenance_per_paper=pp[0] if pp else None, provenance_per_paper_sha256=sha(pp[0]) if pp else None)
    json.dump(out, open(BASE + n + "/provenance-addendum.json", "w"), indent=1); print(n, {a: b for a, b in out.items() if a in ("upstream_revision", "sha1_prefix", "provenance_per_paper_sha256")})
