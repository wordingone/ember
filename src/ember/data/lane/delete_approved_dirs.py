# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""lead 81736 (2026-11-08): delete pg/work/*.zst, wikipedia-20220501/work/*.zst and lvpilot media/text, EACH after a manifest (file, size, sha256, regenerate note) is written.
Explicit paths only, os.remove. Kept: *.done markers (tick.py counts them), lvpilot pair/label/stat json(l) files. Receipt: logs/delete-approved-dirs-receipt.json."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import os, json, hashlib, time
from lane_config import LANE_ROOT as ROOT; MD = ROOT + "/logs/manifests-20261108"; os.makedirs(MD, exist_ok=True)
def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(8 << 20), b""): h.update(c)
    return h.hexdigest()
JOBS = [
 ("pg-work", ROOT + "/pg/work", (".zst",), "re-run scripts/pg_worker.sh on the matching Project Gutenberg shard (common-pile project_gutenberg; source URL + revision per shard in packed/pg-*.prov.jsonl). The product is packed/pg-*."),
 ("wikipedia-work", ROOT + "/wikipedia-20220501/work", (".zst",), "re-run scripts/wiki_pilot.py on the matching enwiki-20220501 part (https://archive.org/download/enwiki-20220501/<part>.bz2; sha1s and URLs in wikipedia-20220501/MANIFEST-deleted-20261108.jsonl). The product is packed/wikipedia-20220501-* plus their HF objects."),
 ("lvpilot", ROOT + "/lvpilot", (".mp3", ".txt", ".bad"), "LibriVox audio from archive.org/librivox.org by section id (origin + archive_sha1 per row in lvpilot/pairs.jsonl, KEPT); text from Project Gutenberg by pg_ebook id (lvpilot/pgids.json, KEPT). Retired lane (lead 81651), MLS replaces it."),
]
receipt = []
for name, root, exts, how in JOBS:
    files = []
    for dp, dn, fn in os.walk(root):
        for f in fn:
            if f.lower().endswith(exts): files.append(os.path.join(dp, f).replace("\\", "/"))
    files.sort(); mp = f"{MD}/{name}-manifest.jsonl"; tot = 0
    with open(mp, "w", encoding="utf-8") as m:
        for p in files:
            sz = os.path.getsize(p); tot += sz
            m.write(json.dumps(dict(file=p, size=sz, sha256=sha(p), regenerate=how)) + chr(10))
    kept = sorted(os.path.relpath(os.path.join(dp, f), root).replace("\\", "/") for dp, dn, fn in os.walk(root) for f in fn if not f.lower().endswith(exts))
    print(name, len(files), "files", round(tot / 2**30, 2), "GiB manifest written", mp, flush=True)
    # manifest is on disk and complete: now delete the explicit paths
    n = 0
    for p in files:
        os.remove(p); n += 1
    for dp, dn, fn in sorted(os.walk(root), key=lambda x: -len(x[0])):
        if dp != root and not os.listdir(dp):
            try: os.rmdir(dp)
            except OSError: pass
    receipt.append(dict(name=name, root=root, deleted=n, bytes=tot, manifest=mp, kept_count=len(kept), kept_sample=kept[:12]))
    print(name, "deleted", n, "files; kept", len(kept), flush=True)
json.dump(dict(ts=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), jobs=receipt), open(ROOT + "/logs/delete-approved-dirs-receipt.json", "w"), indent=1)
print("DONE")
