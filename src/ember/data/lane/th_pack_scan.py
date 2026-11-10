# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""TruffleHog scan of one local pack dir before its HF push (operator / lead 81934). Called (detached) by tick.py upload; the tick pushes only when logs/th-scan/<name>.json says clean for the
CURRENT file signature. Fail-closed: scanner error => clean=false with the error. Never writes values.
Usage: python th_pack_scan.py NAME LOCALDIR"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import os, sys, json, time, hashlib
pass
import th_gate

OUT = (LANE_ROOT + "/logs/th-scan")


def signature(local):
    rows = sorted((os.path.relpath(os.path.join(dp, f), local).replace("\\", "/"), os.path.getsize(os.path.join(dp, f))) for dp, _, fs in os.walk(local) for f in fs)
    return hashlib.sha1(json.dumps(rows).encode()).hexdigest()


def main(name, local):
    os.makedirs(OUT, exist_ok=True)
    files = [os.path.join(dp, f) for dp, _, fs in os.walk(local) for f in fs]
    row = dict(name=name, local=local, signature=signature(local), ts=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), files=len(files))
    try:
        r = th_gate.scan_files(files, timeout=6 * 3600)
        row.update(clean=not r["hits"], hits=r["hits"], hit_files={os.path.relpath(k, local).replace("\\", "/") if os.path.isabs(k) else k: v for k, v in r["files"].items()}, error=None)
    except th_gate.ThError as e:
        row.update(clean=False, hits={}, hit_files={}, error=str(e)[:200])
    tmp = os.path.join(OUT, name + ".json.tmp")
    json.dump(row, open(tmp, "w"), indent=1); os.replace(tmp, os.path.join(OUT, name + ".json"))
    print(json.dumps({k: row[k] for k in ("name", "clean", "hits", "error")}))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2].replace("\\", "/"))
