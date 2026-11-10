# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Census phase 3: unique-content table by modality x status (lead 81208/81209). READ-ONLY.
Usage: census_table.py FILES.jsonl HF_TREES.json OUT_PREFIX"""
import sys, json, hashlib, collections, os
FILES, HF, OUT = sys.argv[1:4]
loc = [json.loads(l) for l in open(FILES)]
hf = json.load(open(HF))
hf_sizes = collections.defaultdict(list)
for repo, rows in hf.items():
    for r in rows: hf_sizes[r["s"]].append((repo, r))
def sha256f(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 22), b""): h.update(b)
    return h.hexdigest()
extra = 0
for d in loc:
    if d["sha"] is None and d["s"] in hf_sizes:
        try: d["sha"] = sha256f(d["p"]); extra += 1
        except Exception: pass
print("extra local hashes for HF size matches:", extra, flush=True)
AUD = {".wav", ".flac", ".mp3", ".opus", ".ogg"}; IMG = {".jpg", ".jpeg", ".png", ".webp"}; VID = {".mp4", ".webm"}
def modality(p, x):
    pl = p.lower()
    if x in AUD: return "audio"
    if x in IMG: return "image"
    if x in VID: return "video"
    if "librispeech" in pl or "common_voice" in pl or "audio" in pl: return "audio"
    if "pd12m" in pl or "docci" in pl or "wikimedia-commons" in pl or "arxivqa" in pl or "image" in pl: return "image"
    if any(k in pl for k in ("github", "the-stack", "starcoder", "code", "commitpack", "notebook")): return "code/other"
    if x == ".safetensors": return "code/other"
    return "text"
def status(p):
    pl = p.lower()
    if "qwen2-vl" in pl: return ("excluded", "model-made (Qwen2-VL output)")
    if "heldout" in pl: return ("heldout", "heldout dir")
    if "librispeech" in pl: return ("heldout", "LibriSpeech dev/test = eval splits")
    if "docci" in pl: return ("heldout", "DOCCI: ruled eval-only (post-wall)")
    if "pd12m" in pl: return ("excluded", "PD12M: Florence-2 captions + model-selected images")
    if "quarantine" in pl: return ("excluded", "quarantined soft-404")
    if "/packed/" in pl or "/upload/" in pl or "catalog-train-cache" in pl or "shards-v0" in pl or "custody" in pl and "train" in pl: return ("admitted", "train-ready / approved batch")
    return ("held-unclassified", "raw held, not yet gated or classified")
def train_ready(p, x):
    pl = p.lower()
    return x in (".bin", ".npy") and ("catalog-train-cache" in pl or "shards" in pl or "/packed/" in pl or "/upload/train" in pl)
groups = {}   # key -> dict(size, paths[], source)
for d in loc:
    key = d["sha"] or ("u:" + d["p"])
    g = groups.setdefault(key, dict(size=d["s"], paths=[], x=d["x"], src="local"))
    g["paths"].append(d["p"])
hf_overlap_proven = 0; hf_only = 0
for repo, rows in hf.items():
    for r in rows:
        if (r["s"] or 0) < 1:
            continue
        key = r["sha"] or ("hf:" + repo + ":" + r["p"])
        g = groups.get(key)
        tag = "hf:" + repo + "/" + r["p"]
        if g is None:
            x = os.path.splitext(r["p"])[1].lower()
            groups[key] = dict(size=r["s"], paths=[tag], x=x, src="hf-only")
            hf_only += 1
        else: g["paths"].append(tag); g["src"] = "local+hf"; hf_overlap_proven += 1
tab = collections.defaultdict(lambda: collections.defaultdict(lambda: [0, 0, 0, 0]))   # modality -> (status) -> [raw_bytes, train_bytes, tokens, n]
reasons = collections.defaultdict(set)
dups_removed = 0; dup_bytes = 0
for key, g in groups.items():
    ps = g["paths"]; p0 = ps[0]; dups_removed += len(ps) - 1; dup_bytes += g["size"] * (len(ps) - 1)
    # status priority: heldout > excluded > admitted > held-unclassified
    sts = [status(p) for p in ps]
    order = {"heldout": 0, "excluded": 1, "admitted": 2, "held-unclassified": 3}
    st, why = sorted(sts, key=lambda s: order[s[0]])[0]
    m = modality(p0, g["x"]); tr = any(train_ready(p, g["x"]) for p in ps)
    row = tab[m][st]
    if tr: row[1] += g["size"]; row[2] += g["size"] // 2     # uint16 token stream: counted from bytes (separators included)
    else:
        row[0] += g["size"]
        if m == "text" and g["x"] in (".jsonl", ".json", ".txt", ".csv", ".parquet", ".gz", ".zst", ".pdf", ".tar", ".bz2", ".xz", ".7z", ".zip"): row[2] += int(g["size"] / 4.2 / 0.3)   # ESTIMATE: compressed->tokens, very rough
    row[3] += 1; reasons[(m, st)].add(why)
md = ["| modality | status | unique files | raw GB | train-ready GB | tokens (B) | note |", "|---|---|---|---|---|---|---|"]
tot = [0, 0, 0, 0]
for m in ("text", "image", "audio", "video", "code/other"):
    for st in ("admitted", "held-unclassified", "excluded", "heldout"):
        r = tab[m][st] if st in tab[m] else None
        if not r or r[3] == 0: continue
        for i in range(4): tot[i] += r[i]
        md.append(f"| {m} | {st} | {r[3]:,} | {r[0]/1e9:.1f} | {r[1]/1e9:.1f} | {r[2]/1e9:.2f}{' (est. for raw part)' if r[0] else ' (counted)'} | {'; '.join(sorted(reasons[(m, st)]))} |")
md.append(f"| TOTAL | | {tot[3]:,} | {tot[0]/1e9:.1f} | {tot[1]/1e9:.1f} | | |")
summary = dict(unique_contents=len(groups), duplicate_path_copies_collapsed=dups_removed, duplicate_bytes_collapsed_gb=round(dup_bytes / 1e9, 1), hf_files_proven_same_as_local_sha=hf_overlap_proven, hf_only_files=hf_only)
open(OUT + ".md", "w").write("\n".join(md) + "\n\n" + json.dumps(summary, indent=1))
json.dump({m: {s: v for s, v in d.items()} for m, d in tab.items()}, open(OUT + ".json", "w"))
print("\n".join(md)); print(summary)
