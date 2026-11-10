# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Trainable-set listing with a secret-scan column (lead 82843). One row per packed pack: tokens, scan = PASS / REFUSED / NOT RUN, C1/C2 verdict state, never-trained tokens.

scan is derived ONLY from logs/th-scan/train-<pack>.json (th_pack_scan.py output) and is valid only for the CURRENT pack file signature:
  PASS     scan row exists, clean is true, error is empty, and (the complete local pack has the same signature now, OR the Hub copy has exactly that signature: scan-hub-binding.json)
  REFUSED  scan row exists for the current signature and clean is false (hits or a scanner error: fail-closed)
  NOT RUN  no scan row, or its signature differs from the pack as it is now (a repack/splice makes the old verdict stale)
A pack is SELECTABLE for an hour declaration only when scan is PASS (select_ok(pack) is the single function the hour-declaration path calls).
Usage: trainable_listing.py [--trained LEDGER[:END_POS] ...] [--out JSON]   (read-only; writes only --out, default loops/trainable-listing.json)
Never prints secret values (it only reads counts)."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import os, sys, json, glob, argparse, collections
pass
from th_pack_scan import signature

PACKED = os.environ.get("TL_PACKED", (LANE_ROOT + "/packed"))
SCAN_ROWS = os.environ.get("TL_SCAN_DIR", (LANE_ROOT + "/logs/th-scan"))
OUT = os.environ.get("TL_OUT", (LANE_ROOT + "/loops/trainable-listing.json"))


BINDING = os.environ.get("TL_BINDING", (LANE_ROOT + "/loops/scan-hub-binding.json"))   # {pack: Hub-listing signature} written by hub_sig.py for every pack on the Hub; a scan row with that signature scanned exactly the Hub copy


def local_complete(pack_dir):
    """True when the local pack holds every shard its intake.json declares (after an upload the shards are often cleared: a scan of such a stub proves nothing)."""
    try: want = json.load(open(os.path.join(pack_dir, "intake.json")))["shards"]
    except Exception: return False
    sd = os.path.join(pack_dir, "shards")
    return os.path.isdir(sd) and len(os.listdir(sd)) >= want


def scan_state(pack_dir, name):
    """-> (state, detail). Fail-closed: anything unreadable is NOT RUN. A row binds either to the complete LOCAL pack (signature equal now) or, for a pack whose local shards are gone,
    to its Hub copy (scan-hub-binding.json: Hub listing signature == the clean row's signature). A scan of an incomplete local stub never counts."""
    f = os.path.join(SCAN_ROWS, "train-%s.json" % name)
    if not os.path.isfile(f): return "NOT RUN", "no scan row"
    try: row = json.load(open(f))
    except Exception as e: return "NOT RUN", "unreadable scan row: %s" % str(e)[:80]
    try: cur = signature(pack_dir)
    except Exception as e: return "NOT RUN", "signature failed: %s" % str(e)[:80]
    hubbound = False
    try: hubbound = json.load(open(BINDING)).get(name) == row.get("signature")
    except Exception: pass
    if hubbound and not local_complete(pack_dir):       # the scanned file set is exactly the Hub copy; applies only while the local pack is a shard-cleared stub (a complete local pack, e.g. a redacted repack under the same name, must match the row itself)
        if row.get("clean") is True and not row.get("error"): return "PASS", "clean at %s; the Hub copy has exactly the scanned file signature" % row.get("ts")
        hits = sum(sum(v.values()) for v in (row.get("hit_files") or {}).values())
        return "REFUSED", ("scanner error: %s" % row["error"]) if row.get("error") else "%d hits in %d objects (Hub copy)" % (hits, len(row.get("hit_files") or {}))
    if not local_complete(pack_dir): return "NOT RUN", "local shards incomplete and no Hub binding: nothing real was scanned"
    if row.get("signature") != cur: return "NOT RUN", "scan row is for an older pack signature"
    if row.get("clean") is True and not row.get("error"): return "PASS", "clean at %s" % row.get("ts")
    hits = sum(sum(v.values()) for v in (row.get("hit_files") or {}).values())
    return "REFUSED", ("scanner error: %s" % row["error"]) if row.get("error") else "%d hits in %d objects" % (hits, len(row.get("hit_files") or {}))


def select_ok(name, packed=None):
    """The hour-declaration gate: True only for scan == PASS on the pack as it is now."""
    d = os.path.join(packed or PACKED, name)
    return os.path.isdir(d) and scan_state(d, name)[0] == "PASS"


def trained_set(path, end):
    s = set(); pos = 0
    for line in open(path):
        r = json.loads(line); b0 = r["spans"][0]["token_start"]
        for sp in r["spans"]:
            if pos + sp["token_start"] - b0 < end: s.add(sp["sha256"])
        pos += r["n_tokens"]
        if pos >= end: break
    return s


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--trained", action="append", default=[]); ap.add_argument("--out", default=OUT)
    a = ap.parse_args(argv)
    sets = []
    for t in a.trained:
        p, _, e = t.rpartition(":")
        if not e.isdigit(): p, e = t, ""      # no END_POS given (the colon was the drive letter's)
        sets.append((os.path.basename(p), trained_set(p, int(e) if e else 10**15)))
    rows = []
    for d in sorted(glob.glob(os.path.join(PACKED, "*/"))):
        name = os.path.basename(d.rstrip("/\\")); ip = os.path.join(d, "intake.json")
        if not os.path.isfile(ip): continue
        it = json.load(open(ip)); st, detail = scan_state(d, name)
        row = dict(pack=name, tokens=it["content_tokens"], scan=st, scan_detail=detail, selectable=(st == "PASS"))
        if sets:
            nev = [0] * len(sets)
            for l in open(os.path.join(d, "ledger.jsonl")):
                for sp in json.loads(l)["spans"]:
                    ln = sp["token_end"] - sp["token_start"]
                    for i, (_, s) in enumerate(sets):
                        if sp["sha256"] not in s: nev[i] += ln
            row["never_trained"] = {n: v for (n, _), v in zip(sets, nev)}; row["never_trained_min"] = min(nev)
        rows.append(row)
    tot = collections.OrderedDict()
    for r in rows:
        k = r["scan"]; tot.setdefault(k, dict(packs=0, tokens=0, never_trained_min=0))
        tot[k]["packs"] += 1; tot[k]["tokens"] += r["tokens"]; tot[k]["never_trained_min"] += r.get("never_trained_min", 0)
    out = dict(rows=rows, totals=tot, trained_sets=[t for t in a.trained])
    tmp = a.out + ".part"; json.dump(out, open(tmp, "w"), indent=1); os.replace(tmp, a.out)
    for r in rows: print("%-30s %-8s tokens %14d%s  %s" % (r["pack"], r["scan"], r["tokens"], ("  never %14d" % r["never_trained_min"]) if "never_trained_min" in r else "", r["scan_detail"]))
    for k, v in tot.items(): print("TOTAL %-8s packs %3d tokens %14d%s" % (k, v["packs"], v["tokens"], ("  never-trained(min) %14d" % v["never_trained_min"]) if sets else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
