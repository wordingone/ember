# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""#1581 pack-receipt audit (read-only). For every local packed/<name> with a receipt.json: required files present (receipt, intake, ledger, source-manifest, docs-index, shards, objects), every receipt object exists with matching size
(--deep: also sha256), receipt token sums consistent, new-lane packs carry domain.json (domain/date_method); then vs the train repo tree (live list_repo_tree): intake.json on HF at text/<name>/ and object shas equal the receipt's;
supersession*.jsonl pairs (r1_pack -> original) both on HF and r1 present locally or on HF. Prints a table; writes logs/pack-audit-<date>.json. Exit 0 = no FAIL rows.
Usage: python pack_audit.py [--deep] [--no-hf]"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import HF_TRAIN_REPO, LANE_ROOT
import os, sys, json, glob, re, time, hashlib
from lane_config import LANE_ROOT as ROOT; REPO = ("wordingone/" + HF_TRAIN_REPO); DEEP = "--deep" in sys.argv; HF = "--no-hf" not in sys.argv
def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 24), b""): h.update(c)
    return h.hexdigest()
tree = {}; sup_pairs = []
if HF:
    from huggingface_hub import HfApi, hf_hub_download
    api = HfApi()
    for t in api.list_repo_tree(REPO, repo_type="dataset", recursive=True):
        if hasattr(t, "size"): tree[t.path] = (t.size, (getattr(t, "lfs", None) or {}).get("sha256") if isinstance(getattr(t, "lfs", None), dict) else getattr(getattr(t, "lfs", None), "sha256", None))
    for p in tree:
        if re.fullmatch(r"supersession(-\d+)?\.jsonl", p):
            for l in open(hf_hub_download(REPO, p, repo_type="dataset", force_download=True), encoding="utf-8"):
                if l.strip():
                    r = json.loads(l)
                    if r.get("kind") != "article_exclusion": sup_pairs.append((r.get("r1_pack"), r.get("original_pack") or r.get("pack") or r.get("old_pack")))
rows = []; fails = 0
for d in sorted(glob.glob(ROOT + "/packed/*/")):
    d = d.replace(chr(92), "/").rstrip("/"); n = os.path.basename(d); issues = []; warn = []
    if not os.path.exists(d + "/receipt.json"):
        rows.append((n, "NO-RECEIPT", "local pack without receipt.json (not yet packed/finished)")); continue
    r = json.load(open(d + "/receipt.json"))
    for f in ("intake.json", "ledger.jsonl", "source-manifest.jsonl"):
        if not os.path.exists(d + "/" + f): issues.append("missing " + f)
    if not (os.path.exists(d + "/docs-index.jsonl.zst") or os.path.exists(d + "/docs-index.jsonl")):
        (warn if "text/%s/docs-index.jsonl.zst" % n in tree else issues).append("docs-index missing locally" + (" (on HF)" if "text/%s/docs-index.jsonl.zst" % n in tree else ""))
    if not glob.glob(d + "/shards/*.bin"): warn.append("no shards locally (cleared after upload?)")
    objs = r.get("objects") or []; tok = 0
    for o in objs:
        p = d + "/objects/" + o["name"]
        if os.path.exists(p):
            if os.path.getsize(p) != o["bytes"]: issues.append("size mismatch " + o["name"])
            elif DEEP and sha(p) != o["sha256"]: issues.append("sha mismatch " + o["name"])
        else: warn.append("object local-absent " + o["name"])
        tok = max(tok, o.get("token_end", 0))
    if objs and tok != r.get("total_tokens"): issues.append("token_end max %s != total_tokens %s" % (tok, r.get("total_tokens")))
    if r.get("content_tokens", 0) + r.get("separator_tokens", 0) != r.get("total_tokens"): issues.append("content+separator != total")
    if re.match(r"(caselaw|usgpo|hansard|pre1929|uspto|loc)-", n) and not os.path.exists(d + "/domain.json") and not n.startswith("loc-"): issues.append("no domain.json (domain/date_method)")
    if HF:
        if "text/%s/intake.json" % n not in tree: warn.append("not on HF train repo yet")
        else:
            for o in objs:
                alts = ["text/%s/objects/%s" % (n, o["name"]), "text/%s/objects/%s" % (n, o["name"].replace(".jsonl.zst", "-r1.jsonl.zst"))]
                if r.get("rebuilt_from"): alts.append("text/%s/objects/%s" % (r["rebuilt_from"], o["name"]))   # -r1 twin: unchanged objects live under the original pack
                t = next((tree[a] for a in alts if a in tree), None)
                if t is None: issues.append("HF missing object " + o["name"])
                elif t[1] and t[1] != o["sha256"]: issues.append("HF sha != receipt " + o["name"])
                elif t[0] != o["bytes"]: issues.append("HF size != receipt " + o["name"])
    st = "FAIL" if issues else ("WARN" if warn else "OK"); fails += bool(issues)
    rows.append((n, st, "; ".join((issues + warn)[:4])))
for r1, old in sup_pairs:
    iss = []
    for x in (r1, old):
        if x and "text/%s/intake.json" % x not in tree: iss.append(x + " not on HF")
    rows.append(("supersession %s->%s" % (r1, old), "FAIL" if iss else "OK", "; ".join(iss))); fails += bool(iss)
c = {}
for r in rows: c[r[1]] = c.get(r[1], 0) + 1
for r in rows:
    if r[1] != "OK": print(r[1], r[0], r[2][:200])
print("SUMMARY", c, "packs/rows", len(rows), "deep" if DEEP else "size-only")
json.dump(dict(ts=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), deep=DEEP, summary=c, rows=rows), open(ROOT + "/logs/pack-audit-20261109.json", "w"), indent=1)
sys.exit(1 if fails else 0)
