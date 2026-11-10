# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Set of owner/name (lower case) of the GitHub repos we already hold issue/PR text from (github_archive finals, `url` field) -> catalog/held-github-repos.json.
The Stack-Edu code rows carry no repo identity (url None), so they cannot be matched by owner/name; the catalog summary says so. Read-only, CPU-only."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import glob, io, json, re, sys, zstandard
RX = re.compile(r"github\.com/([^/\s]+)/([^/\s#?]+)", re.I)
held = set(); n = 0
for f in sorted(glob.glob((LANE_ROOT + "/textwork/github_archive/final-*.jsonl.zst"))):
    with open(f, "rb") as fh:
        for line in io.TextIOWrapper(zstandard.ZstdDecompressor().stream_reader(fh), encoding="utf-8"):
            n += 1
            try: u = json.loads(line).get("url") or ""
            except Exception: continue
            m = RX.search(u)
            if m: held.add((m.group(1) + "/" + m.group(2)).lower())
    print(f, "docs so far", n, "repos so far", len(held), flush=True)
json.dump(sorted(held), open((LANE_ROOT + "/catalog/held-github-repos.json"), "w", encoding="utf-8"))
print("held repos", len(held), "docs", n)
