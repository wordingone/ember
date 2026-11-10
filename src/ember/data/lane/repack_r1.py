# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Rebuild a wikipedia pack's shards / docs-index / ledger / receipt from its objects, with the redacted '-r1' twins in place of the flagged objects (lead 81713, training 81727).
Usage: repack_r1.py PACK [--verify-identity]      e.g. wikipedia-20220501-g00
Object boundaries are KEPT (doc -> object assignment unchanged); only token offsets after a redacted doc shift. Objects are never rewritten: each is hashed/copied byte-for-byte
(unchanged objects keep their sha256; r1 twins carry the sha256 from redact-r1/MANIFEST.jsonl). Tokenizer/shard format/ledger rows are exactly pack.py's.
Output: packed/<PACK>-r1/ {shards, objects (r1 twins + locally-present originals, hardlinked), docs-index.jsonl.zst, ledger.jsonl, receipt.json, source-manifest.jsonl, intake.json}
and logs/repack-r1/<PACK>.manifest.json  (old shard sha -> new shard sha, token counts).  --verify-identity: use ONLY original objects, write to a scratch dir and compare with the existing pack (must be byte-identical)."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import HF_TRAIN_REPO, LANE_ROOT, M_ROOT
import os, sys, io, json, hashlib, array, time, shutil, requests
os.environ.setdefault("RAYON_NUM_THREADS", "4")
import zstandard
from tokenizers import Tokenizer
from huggingface_hub import get_token
from lane_config import LANE_ROOT as ROOT; PACK = sys.argv[1]; VERIFY = "--verify-identity" in sys.argv
REPO = ("wordingone/" + HF_TRAIN_REPO); S = 4194304
TOKP = (M_ROOT + "/custody-tokenizer-2c557/tokenizer-2c557.json")
old = f"{ROOT}/packed/{PACK}"; rec_old = json.load(open(old + "/receipt.json"))
NAME = PACK + ("-verify" if VERIFY else "-r1"); base = f"{ROOT}/" + ("scratch-repack/" if VERIFY else "packed/") + NAME
SCR = f"{ROOT}/scratch-repack/dl"; os.makedirs(SCR, exist_ok=True)
for d in ("shards", "objects"): os.makedirs(f"{base}/{d}", exist_ok=True)
def log(*a): print(time.strftime("%H:%M:%S"), *a, flush=True)
def _glog(m): print(m, file=sys.stderr, flush=True)      # write_gate wait lines go to stderr, never stdout
def sha_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(8 << 20), b""): h.update(b)
    return h.hexdigest()
twin = {}
if not VERIFY:
    for l in open(f"{ROOT}/redact-r1/MANIFEST.jsonl", encoding="utf-8"):
        r = json.loads(l); twin[r["old_path"]] = r
tok = get_token()
def fetch(hf_path, want_sha, dest):
    """Range-resume until the file reaches its HF size (a stream can end early without raising), then verify the sha."""
    from huggingface_hub import HfApi
    size = HfApi().get_paths_info(REPO, [hf_path], repo_type="dataset", expand=True)[0].size
    have = os.path.getsize(dest) if os.path.exists(dest) else 0
    import reserve_plan
    if not reserve_plan.write_gate("repack_r1.py fetch", max(size - have, 0) + (64 << 20), log=_glog):      # lead 82324 / lead 82669
        sys.exit(f"write_gate refused: B: below the reserve floor for the whole gate cap: repack_r1.py not fetching {os.path.basename(dest)}")
    while have < size:
        try:
            with requests.get(f"https://huggingface.co/datasets/{REPO}/resolve/main/{hf_path}", stream=True, timeout=(30, 90), headers={"Range": f"bytes={have}-", "Authorization": "Bearer " + tok, "User-Agent": "ember-repack/1.0"}) as r:
                if r.status_code == 416: break
                r.raise_for_status()
                with open(dest, "ab") as f:
                    for c in r.iter_content(4 << 20): f.write(c)
        except Exception as e:
            log("drop", type(e).__name__); time.sleep(5)
        have = os.path.getsize(dest) if os.path.exists(dest) else 0
    if sha_file(dest) != want_sha: raise RuntimeError(f"{os.path.basename(dest)} sha mismatch vs expected (have {have} of {size})")
# ---- resolve the ordered object list ----
srcs = []   # dict(name, path, sha, temp)
for o in rec_old["objects"]:
    oname = o["name"]; hf_old = f"text/{PACK}/objects/{oname}"; lp = f"{old}/objects/{oname}"
    t = twin.get(hf_old)
    if t:
        nm = os.path.basename(t["new_path"]); dest = f"{SCR}/{nm}"
        log("fetch r1 twin", nm); fetch(t["new_path"], t["new_sha256"], dest)
        srcs.append(dict(name=nm, path=dest, sha=t["new_sha256"], temp=False, old_sha=o["sha256"], keep=True))
    elif os.path.exists(lp) and sha_file(lp) == o["sha256"]:
        srcs.append(dict(name=oname, path=lp, sha=o["sha256"], temp=False, old_sha=o["sha256"], keep=True, local=True))
    else:
        dest = f"{SCR}/{oname}"; log("fetch original", oname); fetch(hf_old, o["sha256"], dest)
        srcs.append(dict(name=oname, path=dest, sha=o["sha256"], temp=True, old_sha=o["sha256"], keep=False))
log(f"{PACK}: {len(srcs)} objects ({sum(1 for s in srcs if s['old_sha'] != s['sha'])} r1 twins)")
# ---- tokenize exactly like pack.py ----
tk = Tokenizer.from_file(TOKP)
cctx = zstandard.ZstdCompressor(level=6)
import reserve_plan
if not reserve_plan.write_gate("repack_r1.py rebuild", sum(os.path.getsize(s["path"]) for s in srcs) + (64 << 20), log=_glog):      # index + ledger + hardlink/copy fallback; the shards re-gate per shard in flush_shards
    sys.exit(f"write_gate refused: B: below the reserve floor for the whole gate cap: repack_r1.py not rebuilding {NAME}")
docidx = open(f"{base}/docs-index.jsonl", "w", encoding="utf-8")
buf = array.array("H"); shard_idx = 0; total = 0; sep = 0; ndocs = 0; shard_rows = []; parts = []
def flush_shards(final=False):
    global buf, shard_idx
    while len(buf) >= S or (final and len(buf) > 0):
        chunk = buf[:S]; buf = buf[S:]
        import reserve_plan
        if not reserve_plan.write_gate("repack_r1.py shard", len(chunk) * 2 + (64 << 20), log=_glog):      # same gate as pack.py
            sys.exit(f"write_gate refused: B: below the reserve floor for the whole gate cap: repack_r1.py stopped before shard {shard_idx} of {NAME}")
        tmp = f"{base}/shards/tmp.bin"
        with open(tmp, "wb") as f: chunk.tofile(f)
        sha = sha_file(tmp); name = f"v1-{shard_idx:05d}-{sha[:12]}.bin"
        os.replace(tmp, f"{base}/shards/{name}")
        shard_rows.append((name, sha, len(chunk))); shard_idx += 1
        if final and len(buf) == 0: break
t0 = time.time()
for k, s in enumerate(srcs):
    start = total
    with open(s["path"], "rb") as f:
        rd = io.TextIOWrapper(zstandard.ZstdDecompressor().stream_reader(f), encoding="utf-8")
        B = []
        def proc(B):
            global total, sep, ndocs
            encs = tk.encode_batch([d["text"] for d in B], add_special_tokens=False)
            for d, e in zip(B, encs):
                ids = e.ids
                if 0 in ids: raise RuntimeError("doc encodes to id 0: object boundary would change; abort")
                n = len(ids) + 1
                docidx.write(json.dumps(dict(id=d.get("id"), object_index=k, token_start=total, token_end=total + n)) + "\n")
                buf.extend(ids); buf.append(0); total += n; sep += 1; ndocs += 1
                if len(buf) >= S: flush_shards()
        for line in rd:
            B.append(json.loads(line))
            if len(B) >= 256: proc(B); B = []
        if B: proc(B)
    parts.append(dict(path=s["path"], name=s["name"], token_start=start, token_end=total, sha256=s["sha"]))
    log(f"obj {k+1}/{len(srcs)} done, tokens {total}, {round(time.time()-t0)}s")
flush_shards(final=True); docidx.close()
with open(f"{base}/docs-index.jsonl", "rb") as f, open(f"{base}/docs-index.jsonl.zst", "wb") as fo: cctx.copy_stream(f, fo)
os.remove(f"{base}/docs-index.jsonl")
# ---- ledger (pack.py's code) ----
rows = []; prev = "0" * 64
for i, (name, sha, n) in enumerate(shard_rows):
    a, b = i * S, i * S + n
    spans = []; last_k = None
    for kk, p in enumerate(parts):
        lo, hi = max(a, p["token_start"]), min(b, p["token_end"])
        if lo < hi: spans.append(dict(sha256=p["sha256"], token_start=lo, token_end=hi)); last_k = kk
    p = parts[last_k]
    if b < p["token_end"]: res = dict(object_index=last_k, carry_tokens=b - max(a, p["token_start"]))
    else: res = dict(object_index=last_k + 1, carry_tokens=0)
    row = dict(index=i, n_tokens=n, name=name, prev_row_sha256=prev, resume=res, schema_version="ember-catalog-train-shard-ledger-v1", sha256=sha, spans=spans)
    row["row_sha256"] = hashlib.sha256(json.dumps({k: v for k, v in row.items() if k != "row_sha256"}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    prev = row["row_sha256"]; rows.append(row)
with open(f"{base}/ledger.jsonl", "w", encoding="utf-8") as f:
    for r in rows: f.write(json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n")
dsid = hashlib.sha256("\n".join(sorted(p["sha256"] for p in parts)).encode()).hexdigest()
rec = dict(name=NAME, docs=ndocs, total_tokens=total, separator_tokens=sep, content_tokens=total - sep, docs_dropped_text_encodes_to_id0=0, shards=len(shard_rows),
           objects=[dict(index=k, name=p["name"], sha256=p["sha256"], token_start=p["token_start"], token_end=p["token_end"], bytes=os.path.getsize(p["path"])) for k, p in enumerate(parts)],
           tokenizer_sha256=rec_old["tokenizer_sha256"], tokenizer_path=TOKP, stream_format=rec_old["stream_format"], shard_tokens=S,
           secret_redaction=dict(note="objects scanned clean by secret_scan (audit); flagged objects replaced by their redacted -r1 twins", scanner="scripts/secret_scan.py"),
           dataset_id=f"dataset:{NAME}:{dsid}", rebuilt_from=PACK, inputs=[p["name"] for p in parts], secs=round(time.time() - t0))
json.dump(rec, open(f"{base}/receipt.json", "w"), indent=1)
# object files: r1 twins and originals that were already local stay (hardlink); temp downloads are dropped
for s, p in zip(srcs, parts):
    if s["keep"]:
        dst = f"{base}/objects/{s['name']}"
        if not os.path.exists(dst):
            try: os.link(s["path"], dst)
            except OSError: shutil.copy2(s["path"], dst)
    elif s["temp"]: os.remove(s["path"])
# source manifest: old rows, with the r1 twins' object_name/sha swapped
sm_old = [json.loads(l) for l in open(old + "/source-manifest.jsonl", encoding="utf-8")]
by_old = {s["old_sha"]: s for s in srcs}
with open(f"{base}/source-manifest.jsonl", "w", encoding="utf-8") as f:
    for r in sm_old:
        s = by_old.get(r["object_sha256"])
        if s and s["sha"] != r["object_sha256"]: r = dict(r, object_sha256=s["sha"], object_name=s["name"], redacted_from=s["old_sha"])
        f.write(json.dumps(r) + "\n")
# old -> new shard manifest
old_led = [json.loads(l) for l in open(old + "/ledger.jsonl", encoding="utf-8")]
man = dict(pack_old=PACK, pack_new=NAME, old_total_tokens=rec_old["total_tokens"], new_total_tokens=total, old_shards=len(old_led), new_shards=len(rows),
           shards=[dict(index=i, old_name=(old_led[i]["name"] if i < len(old_led) else None), old_sha256=(old_led[i]["sha256"] if i < len(old_led) else None), old_tokens=(old_led[i]["n_tokens"] if i < len(old_led) else None),
                        new_name=rows[i]["name"], new_sha256=rows[i]["sha256"], new_tokens=rows[i]["n_tokens"], changed=(i >= len(old_led) or old_led[i]["sha256"] != rows[i]["sha256"])) for i in range(len(rows))],
           objects_r1=[dict(old_sha256=s["old_sha"], new_sha256=s["sha"], name=s["name"]) for s in srcs if s["old_sha"] != s["sha"]])
man["shards_changed"] = sum(1 for x in man["shards"] if x["changed"])
if VERIFY:
    same = (rec["total_tokens"] == rec_old["total_tokens"] and man["shards_changed"] == 0 and len(rows) == len(old_led)
            and [r["row_sha256"] for r in rows] == [r["row_sha256"] for r in old_led])
    log("IDENTITY", "PASS" if same else "FAIL", "tokens", total, "vs", rec_old["total_tokens"], "changed shards", man["shards_changed"],
        "ledger rows equal", [r["row_sha256"] for r in rows] == [r["row_sha256"] for r in old_led])
    sys.exit(0 if same else 1)
os.makedirs(f"{ROOT}/logs/repack-r1", exist_ok=True)
json.dump(man, open(f"{ROOT}/logs/repack-r1/{PACK}.manifest.json", "w"), indent=1)
# intake.json (same shape as the existing packs)
old_in = json.load(open(old + "/intake.json"))
intake = dict(old_in, name=NAME, dataset_id=rec["dataset_id"], content_tokens=rec["content_tokens"], shards=rec["shards"], objects=len(parts),
              docs_index_sha256=sha_file(f"{base}/docs-index.jsonl.zst"), ledger_sha256=sha_file(f"{base}/ledger.jsonl"), source_manifest_sha256=sha_file(f"{base}/source-manifest.jsonl"),
              path=base.replace("/", "\\") if False else base, written=time.strftime("%Y-%m-%dT%H:%M:%S"), rebuilt_from=PACK, note="redacted -r1 rebuild (lead 81713, training 81727)")
json.dump(intake, open(f"{base}/intake.json", "w"), indent=1)
log("DONE", NAME, "tokens", total, "changed shards", man["shards_changed"], "of", len(rows))
