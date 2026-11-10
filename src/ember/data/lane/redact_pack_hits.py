# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""TruffleHog-refused LOCAL text-lane pack (never uploaded): redact the flagged spans and repack under the same name. Usage: redact_pack_hits.py PACK   (PACK has receipt.json['inputs'] = lane finals)
Finals are never modified: redacted COPIES go to scratch/<PACK>-redacted/, the old local pack dir is renamed aside (not deleted), pack.py + source_manifest.py (text_lane convention) rebuild it,
domain.json / provenance-addendum.json are carried over. Values are never printed or logged (counts only). Hit values come from th_gate.find_values (in memory)."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import os, sys, json, io, subprocess, shutil, time
pass
import zstandard, secret_scan, th_gate
from lane_config import LANE_ROOT as ROOT; NAME = sys.argv[1]; SRC = f"{ROOT}/packed/{NAME}"; OUTD = f"{ROOT}/scratch/{NAME}-redacted"; os.makedirs(OUTD, exist_ok=True)
ENV = dict(os.environ, PYTHONIOENCODING="utf-8", CUDA_VISIBLE_DEVICES="")
rc = json.load(open(SRC + "/receipt.json")); ins = rc["inputs"]; outs = []; nv = nrep = 0
src0 = json.loads(open(SRC + "/source-manifest.jsonl", encoding="utf-8").readline())
import reserve_plan
for p in ins:
    if not reserve_plan.write_gate("redact copy", 2 * os.path.getsize(p) + (256 << 20)):      # lead 82324
        sys.exit("write_gate refused: B: below the reserve floor for the whole gate cap: redact copy not writing")
    o = f"{OUTD}/{os.path.basename(p)}"; vals = th_gate.find_values(p); nv += len(vals)
    with open(p, "rb") as f, open(o, "wb") as fo, zstandard.ZstdCompressor(level=6).stream_writer(fo) as w:
        for line in io.TextIOWrapper(zstandard.ZstdDecompressor().stream_reader(f), encoding="utf-8"):
            d = json.loads(line); t = d["text"]
            for v in vals:
                if v in t: t = t.replace(v, secret_scan.PLACEHOLDER); nrep += 1
            d["text"] = t; w.write((json.dumps(d, ensure_ascii=False) + "\n").encode())
    outs.append(o); print("input", os.path.basename(p), "values", len(vals), flush=True)
print("values", nv, "doc replacements", nrep, flush=True)
for o in outs: assert not th_gate.find_values(o), "still a hit after redaction: " + os.path.basename(o)
aside = f"{ROOT}/scratch/{NAME}-pre-redaction-{time.strftime('%H%M')}"; os.rename(SRC, aside)
rr = subprocess.run([sys.executable, f"{ROOT}/scripts/pack.py", f"{ROOT}/packed", NAME] + outs, env=ENV, capture_output=True, text=True); print(rr.stdout.strip()[-160:], rr.stderr.strip()[-160:]); assert rr.returncode == 0
rr = subprocess.run([sys.executable, f"{ROOT}/scripts/source_manifest.py", f"{ROOT}/packed/{NAME}", f"{ROOT}/packed/{NAME}.prov.jsonl", src0["origin"], "per-doc licence (see rows)", src0["fetch_date"].split("..")[0], src0["content_date_max"], "text"], env=ENV, capture_output=True, text=True); print(rr.stdout.strip()[-160:], rr.stderr.strip()[-160:])
for f in ("domain.json", "provenance-addendum.json"):
    if os.path.exists(f"{aside}/{f}"): shutil.copyfile(f"{aside}/{f}", f"{ROOT}/packed/{NAME}/{f}")
print("REDACT-PACK DONE", NAME)
