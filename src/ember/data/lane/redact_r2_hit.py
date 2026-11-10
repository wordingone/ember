# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""TruffleHog hit in the NEW local r2 pack (never uploaded): find the value(s) in the scrubbed intermediate object(s) in memory, replace with <REDACTED_CREDENTIAL>, repack r2 (old local dir renamed aside, not deleted), source_manifest.
Values are never printed or logged: only counts."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import os, sys, json, io, subprocess, shutil, time
pass
import zstandard, secret_scan, th_gate
from lane_config import LANE_ROOT as ROOT; NEW = "wikipedia-20220501-p41243p151573-r2"; SCR = f"{ROOT}/scratch/{NEW}"
ENV = dict(os.environ, PYTHONIOENCODING="utf-8", CUDA_VISIBLE_DEVICES="")
files = sorted(os.path.join(SCR, f) for f in os.listdir(SCR) if f.endswith(".jsonl.zst")); changed = 0; total_vals = 0
for p in files:
    vals = th_gate.find_values(p)
    if not vals: continue
    total_vals += len(vals); tmp = p + ".tmp"
    with open(p, "rb") as f, open(tmp, "wb") as fo, zstandard.ZstdCompressor(level=6).stream_writer(fo) as w:
        for line in io.TextIOWrapper(zstandard.ZstdDecompressor().stream_reader(f), encoding="utf-8"):
            d = json.loads(line); t = d["text"]
            for v in vals:
                if v in t: t = t.replace(v, secret_scan.PLACEHOLDER); changed += 1
            d["text"] = t; w.write((json.dumps(d, ensure_ascii=False) + "\n").encode())
    os.replace(tmp, p); print("redacted file", os.path.basename(p), "values", len(vals), flush=True)
print("values", total_vals, "doc replacements", changed, flush=True)
if not total_vals: sys.exit("no value found in scratch objects - nothing to redact (scan hit elsewhere?)")
for p in files:                                             # re-scan the fixed intermediates (must be clean)
    assert not th_gate.find_values(p), "still a hit after redaction: " + os.path.basename(p)
old = f"{ROOT}/packed/{NEW}"; aside = f"{ROOT}/scratch/{NEW}-pre-redaction-{time.strftime('%H%M')}"; os.rename(old, aside); print("old local r2 moved aside:", aside)
rr = subprocess.run([sys.executable, f"{ROOT}/scripts/pack.py", f"{ROOT}/packed", NEW] + files, env=ENV, capture_output=True, text=True); print(rr.stdout.strip()[-200:], rr.stderr.strip()[-200:]); assert rr.returncode == 0
prov = f"{ROOT}/packed/{NEW}.prov.jsonl"
rr = subprocess.run([sys.executable, f"{ROOT}/scripts/source_manifest.py", f"{ROOT}/packed/{NEW}", prov, "archive.org/details/enwiki-20220501 enwiki-20220501-pages-articles-multistream2.xml-p41243p151573.bz2 (sha1 8d256c02, verified; ns0 non-redirect; rescrubbed vs frozen 2M wiki heldout + full heldout index + arxiv heldout; one TruffleHog-flagged span redacted)", "CC BY-SA 3.0 + GFDL (Wikipedia text)", "2026-11-06", "2022-05-01"], env=ENV, capture_output=True, text=True); print(rr.stdout.strip()[-200:], rr.stderr.strip()[-200:])
print("REDACT-R2 DONE")
