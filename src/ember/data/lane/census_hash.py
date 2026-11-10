# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Census phase 2: hash Ember-scope candidate files; READ-ONLY.
Usage: census_hash.py CANDIDATES.jsonl OUT.jsonl
Scope: path under an Ember root OR name matches EMBER_RE; everything else is only counted per top dir ('out of scope, listed').
Dedup: files with a unique size cannot be duplicates -> not hashed (sha=None, unique). Files sharing a size are sha256-hashed (full)."""
import sys, json, re, hashlib, collections, time
CAND, OUT = sys.argv[1], sys.argv[2]
SKIP_PREFIXES = tuple(x for x in __import__("os").environ.get("EMBER_CENSUS_SKIP_PREFIXES", "").lower().split(";") if x)
EMBER_RE = re.compile(r"ember|corpus|dclm|zyda|pes2o|common-pile|wikipedia|wikisource|arxiv|pd12m|docci|librispeech|gutenberg|stackex|custody|heldout|catalog-train|commons|openstax|courtlistener|metamath|fineweb|the-stack|github", re.I)
NOT_DATA = (".safetensors",)
files = [json.loads(l) for l in open(CAND)]
scope = []; out_of_scope = collections.Counter(); oos_n = collections.Counter()
for d in files:
    pl = d["p"].lower()
    if d["x"] in NOT_DATA: out_of_scope["model-weights(.safetensors)"] += d["s"]; oos_n["model-weights(.safetensors)"] += 1; continue
    if "/.claude/" in pl or "/.codex/" in pl or "/node_modules/" in pl: out_of_scope["agent-session-dirs"] += d["s"]; oos_n["agent-session-dirs"] += 1; continue
    if pl.startswith(SKIP_PREFIXES) or EMBER_RE.search(pl): scope.append(d)
    else:
        k = "/".join(d["p"].split("/")[:3]); out_of_scope[k] += d["s"]; oos_n[k] += 1
by = collections.defaultdict(list)
for d in scope: by[d["s"]].append(d)
need = [d for s, v in by.items() if len(v) > 1 for d in v]
print("scope files", len(scope), "bytes", sum(d["s"] for d in scope), "to hash", len(need), "bytes", sum(d["s"] for d in need), flush=True)
t0 = time.time(); done = 0; hb = 0; sha = {}
for d in sorted(need, key=lambda x: x["s"]):
    h = hashlib.sha256()
    try:
        with open(d["p"], "rb") as f:
            for b in iter(lambda: f.read(1 << 22), b""): h.update(b)
        sha[d["p"]] = h.hexdigest()
    except Exception: sha[d["p"]] = None
    done += 1; hb += d["s"]
    if done % 500 == 0: print(done, len(need), round(hb / 1e9, 1), "GB", round(time.time() - t0), flush=True)
with open(OUT, "w") as fo:
    for d in scope:
        d["sha"] = sha.get(d["p"]); fo.write(json.dumps(d) + "\n")
json.dump({k: [v, oos_n[k]] for k, v in out_of_scope.most_common()}, open(OUT + ".out-of-scope.json", "w"), indent=0)
print("DONE", round(time.time() - t0))
