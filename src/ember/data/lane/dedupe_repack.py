# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Dedupe-repack a text-lane pack whose documents overlap the union index (class fix for the arxiv_papers ns_key gap, #2449, 2026-11-10).
  python dedupe_repack.py LANE PACK [--extra-final PATH ...] [--dry]
LANE = text lane name (ns_key namespace); PACK = packed/<PACK> with receipt.json['inputs'] = lane finals; --extra-final = further UNPACKED finals of the lane to filter in place
(they also drop docs whose key is already kept in the pack finals). A document is dropped when check_docs(ns_key id, text) hits ANY pack except PACK itself (for the pack's own finals),
or when its key was already kept earlier in this run. Finals are filtered into scratch/<PACK>-dedup/ (write-gated), the originals are renamed aside (never deleted) into
scratch/<PACK>-finals-pre-dedupe/, the filtered file takes the final's path, the old pack dir is renamed aside (scratch/<PACK>-pre-dedupe-<ts>, keeps its HOLD-UPLOAD marker), then
pack.py + pack_prov_fix.py rebuild PACK; the new pack is re-checked against the index (must be 0) and re-indexed. Resumable (progress.json), logged, nothing deleted.
The new pack carries no marker: tick.py upload still needs training's C1/C2 PASS bound to the NEW intake ledger sha. Red: scripts/tests/dedupe_repack_red_test.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import os, sys, io, json, time, shutil, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import zstandard, overlap_gate as G, reserve_plan

from lane_config import LANE_ROOT as ROOT


def keep_batch(batch, lane, self_srcs, seen, check=None):
    """batch = list of doc dicts (id, text). Returns (kept, dropped[(id, why, src)]). Mutates seen (set of kept ns keys)."""
    check = check or G.check_docs
    keys = [G.ns_key(lane, r["id"]) for r in batch]
    hit = {k: (why, src) for k, why, src in check([(k, r["text"]) for k, r in zip(keys, batch)], lane) if src not in self_srcs}
    kept, dropped = [], []
    for k, r in zip(keys, batch):
        if k in hit: dropped.append((r["id"], hit[k][0], hit[k][1]))
        elif k in seen: dropped.append((r["id"], "run-dup", "this run"))
        else: seen.add(k); kept.append(r)
    return kept, dropped


def filter_final(src, dst, lane, self_srcs, seen, check=None, gate=True, batch_n=2000, drop_log=None):
    if gate and not reserve_plan.write_gate("dedupe copy", os.path.getsize(src) + (256 << 20)):
        raise RuntimeError("write_gate refused: B: below the reserve floor for the whole gate cap: dedupe copy not writing")
    n_in = n_keep = 0; batch = []
    def flush(w):
        nonlocal n_keep
        kept, dropped = keep_batch(batch, lane, self_srcs, seen, check)
        for r in kept: w.write((json.dumps(r, ensure_ascii=False) + "\n").encode()); n_keep += 1
        if drop_log:
            for d in dropped: drop_log.write(json.dumps(dict(final=os.path.basename(src), id=d[0], why=d[1], src=d[2])) + "\n")
        batch.clear()
    with open(src, "rb") as f, open(dst, "wb") as fo, zstandard.ZstdCompressor(level=6).stream_writer(fo) as w:
        for line in io.TextIOWrapper(zstandard.ZstdDecompressor().stream_reader(f), encoding="utf-8"):
            batch.append(json.loads(line)); n_in += 1
            if len(batch) >= batch_n: flush(w)
        if batch: flush(w)
    return n_in, n_keep


def main():
    a = sys.argv[1:]; dry = "--dry" in a; extra = [a[i + 1] for i, x in enumerate(a) if x == "--extra-final"]
    pos = [x for i, x in enumerate(a) if not x.startswith("--") and not (i and a[i - 1] == "--extra-final")]; LANE, PACK = pos[0], pos[1]
    SRC = f"{ROOT}/packed/{PACK}"; WD = f"{ROOT}/scratch/{PACK}-dedup"; OLD = f"{ROOT}/scratch/{PACK}-finals-pre-dedupe"; PR = WD + "/progress.json"
    os.makedirs(WD, exist_ok=True); os.makedirs(OLD, exist_ok=True)
    prog = json.load(open(PR)) if os.path.exists(PR) else {"finals": {}}
    def save(): json.dump(prog, open(PR + ".tmp", "w")); os.replace(PR + ".tmp", PR)
    ins = [p.replace("\\", "/") for p in json.load(open(SRC + "/receipt.json"))["inputs"]] if os.path.isdir(SRC) else sorted(prog.get("pack_inputs", []))
    prog["pack_inputs"] = ins; seen = set(); dl = open(f"{ROOT}/logs/dedupe-{PACK}-dropped{'-dryrun' if dry else ''}.jsonl", "a", encoding="utf-8")
    for p in ins + [e.replace("\\", "/") for e in extra]:
        st = prog["finals"].get(p)
        if st and st.get("done"):    # resume: kept ids of a finished final still have to enter `seen`
            for line in io.TextIOWrapper(zstandard.ZstdDecompressor().stream_reader(open(p, "rb")), encoding="utf-8"): seen.add(G.ns_key(LANE, json.loads(line)["id"]))
            print("skip done", os.path.basename(p), flush=True); continue
        o = os.devnull if dry else f"{WD}/{os.path.basename(p)}"; selfs = {PACK} if p in ins else set()
        n_in, n_keep = filter_final(p, o, LANE, selfs, seen, drop_log=dl, gate=not dry); dl.flush()
        print(os.path.basename(p), "docs", n_in, "kept", n_keep, "dropped", n_in - n_keep, flush=True)
        if dry: continue
        os.rename(p, f"{OLD}/{os.path.basename(p)}"); os.replace(o, p)          # originals kept aside, never deleted
        prog["finals"][p] = dict(done=True, docs_in=n_in, kept=n_keep, aside=f"{OLD}/{os.path.basename(p)}", ts=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())); save()
    if dry: print("DRY done"); return
    ts = time.strftime("%Y%m%dT%H%M%S")
    if os.path.isdir(SRC) and "old_pack_aside" not in prog:
        aside = f"{ROOT}/scratch/{PACK}-pre-dedupe-{ts}"; os.rename(SRC, aside); prog["old_pack_aside"] = aside; save(); print("old pack aside", aside, flush=True)
    env = dict(os.environ, PYTHONIOENCODING="utf-8", CUDA_VISIBLE_DEVICES="")
    if not prog.get("packed"):
        if os.path.isdir(SRC): os.rename(SRC, f"{ROOT}/scratch/{PACK}-partial-{ts}")      # an interrupted earlier build: keep it aside, never delete
        r = subprocess.run([sys.executable, f"{ROOT}/scripts/pack.py", f"{ROOT}/packed", PACK] + ins, env=env, capture_output=True, text=True); print(r.stdout.strip()[-200:], r.stderr.strip()[-200:]); assert r.returncode == 0
        prog["packed"] = True; save()
    if not prog.get("prov"):
        r = subprocess.run([sys.executable, f"{ROOT}/scripts/pack_prov_fix.py", LANE, PACK], env=env, capture_output=True, text=True); print(r.stdout.strip()[-300:], r.stderr.strip()[-200:]); assert r.returncode == 0
        prog["prov"] = True; save()
    n = bad = 0; batch = []
    for r in G.iter_objects(SRC):
        batch.append(r); n += 1
        if len(batch) >= 2000: bad += len([1 for k, w, s in G.check_docs([(G.ns_key(LANE, x["id"]), x["text"]) for x in batch], LANE) if s != PACK]); batch = []
    if batch: bad += len([1 for k, w, s in G.check_docs([(G.ns_key(LANE, x["id"]), x["text"]) for x in batch], LANE) if s != PACK])
    print("new pack docs", n, "overlaps with other packs", bad, flush=True); prog["new_pack_docs"] = n; prog["new_pack_overlaps"] = bad; save(); assert bad == 0, "overlaps remain"
    c = G._db(); c.execute("delete from docs where src=?", (PACK,)); c.commit(); c.close(); G.build_docs([PACK])        # index == the new, smaller pack
    print("DEDUPE-REPACK DONE", PACK, json.dumps({k: v for k, v in prog.items() if k != "finals"}), flush=True)


if __name__ == "__main__": main()
