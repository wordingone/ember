# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Trainable-set listing with a secret-scan column (lead 82843). One row per packed pack: tokens, scan = PASS / REFUSED / NOT RUN, C1/C2 verdict state, never-trained tokens.

scan is derived ONLY from logs/th-scan/train-<pack>.json (th_pack_scan.py output) and is valid only for the CURRENT pack file signature:
  PASS     scan row exists, clean is true, error is empty, and (the complete local pack has the same signature now, OR the Hub copy has exactly that signature: scan-hub-binding.json)
  REFUSED  scan row exists for the current signature and clean is false (hits or a scanner error: fail-closed)
  NOT RUN  no scan row, or its signature differs from the pack as it is now (a repack/splice makes the old verdict stale)
The signature is (relative path, byte size) of every file: it binds a verdict to the file set, not to file content.
A pack is SELECTABLE for an hour declaration only when scan is PASS (select_ok(pack) is the single function the hour-declaration path calls).
One bad pack is a row, never an abort: the output carries `residual` = dirs_seen, dirs_classified, dirs_skipped [{pack, reason}] (reasons no_intake_json, missing_content_tokens); a malformed intake.json or an unreadable
ledger gives a classified row with `error` that is not selectable; a --trained ledger that cannot be read is listed under `trained_errors` and left out of the never-trained columns.
Usage: trainable_listing.py [--trained LEDGER[:END_POS] ...] [--out JSON]   (read-only; writes only --out, default loops/trainable-listing.json)
Never prints secret values (it only reads counts)."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import os, sys, json, glob, argparse, collections, re
pass
from th_pack_scan import signature
from pack_scan_status import record_clean      # the ONE clean/hits/error rule for a scan record (the upload tick uses the same function)

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


def _nhits(row):
    try: return sum(sum(v.values()) for v in (row.get("hit_files") or {}).values())
    except Exception:
        h = row.get("hits")
        return sum(v for v in h.values() if isinstance(v, int)) if isinstance(h, dict) else 0


def scan_state(pack_dir, name):
    """-> (state, detail). Fail-closed: anything unreadable is NOT RUN. A row binds either to the complete LOCAL pack (signature equal now) or, for a pack whose local shards are gone,
    to its Hub copy (scan-hub-binding.json: Hub listing signature == the clean row's signature). A scan of an incomplete local stub never counts."""
    f = os.path.join(SCAN_ROWS, "train-%s.json" % name)
    if not os.path.isfile(f): return "NOT RUN", "no scan row"
    try: row = json.load(open(f))
    except Exception as e: return "NOT RUN", "unreadable scan row: %s" % str(e)[:80]
    if not isinstance(row, dict): return "NOT RUN", "unreadable scan row: not a JSON object"
    try: cur = signature(pack_dir)
    except Exception as e: return "NOT RUN", "signature failed: %s" % str(e)[:80]
    hubbound = False
    try:
        rsig = row.get("signature"); bsig = json.load(open(BINDING)).get(name)
        hubbound = bool(rsig) and bool(bsig) and bsig == rsig      # both sides must carry a signature: None == None is not a binding
    except Exception: pass
    if hubbound and not local_complete(pack_dir):       # the scanned file set is exactly the Hub copy; applies only while the local pack is a shard-cleared stub (a complete local pack, e.g. a redacted repack under the same name, must match the row itself)
        if record_clean(row): return "PASS", "clean at %s; the Hub copy has exactly the scanned file signature" % row.get("ts")
        hits = _nhits(row)
        return "REFUSED", ("scanner error: %s" % row["error"]) if row.get("error") else "%d hits in %d objects (Hub copy)" % (hits, len(row.get("hit_files") or {}))
    if not local_complete(pack_dir): return "NOT RUN", "local shards incomplete and no Hub binding: nothing real was scanned"
    if row.get("signature") != cur: return "NOT RUN", "scan row is for an older pack signature"
    if record_clean(row): return "PASS", "clean at %s" % row.get("ts")
    hits = _nhits(row)
    return "REFUSED", ("scanner error: %s" % row["error"]) if row.get("error") else "%d hits in %d objects" % (hits, len(row.get("hit_files") or {}))


def superseded_by(name, packed=None):
    """-> the name of the newest revision when `name` is an older member of a base/-r1/-r2 group among the packs with an intake.json in `packed`, else None (lead 83208)."""
    root = packed or PACKED
    try: names = [n for n in os.listdir(root) if os.path.isfile(os.path.join(root, n, "intake.json"))]
    except Exception: return None
    rows = [dict(pack=n) for n in names]
    if name not in names: rows.append(dict(pack=name))
    mark_superseded(rows)
    return next((r["superseded_by"] for r in rows if r["pack"] == name), None)


def select_refusal(name, packed=None):
    """None when the pack may be selected for an hour, else the reason string. A superseded pack is refused whatever its scan state: 'superseded by <newest>'."""
    d = os.path.join(packed or PACKED, name)
    if not os.path.isdir(d): return "no such packed pack"
    nw = superseded_by(name, packed)
    if nw: return "superseded by %s" % nw
    st = scan_state(d, name)[0]
    return None if st == "PASS" else "scan %s" % st


def select_ok(name, packed=None):
    """The hour-declaration gate: True only for scan == PASS on the pack as it is now AND the pack is not superseded by a newer -rN revision."""
    return select_refusal(name, packed) is None


def trained_set(path, end):
    s = set(); pos = 0
    for line in open(path):
        r = json.loads(line); b0 = r["spans"][0]["token_start"]
        for sp in r["spans"]:
            if pos + sp["token_start"] - b0 < end: s.add(sp["sha256"])
        pos += r["n_tokens"]
        if pos >= end: break
    return s


def _row_for(d, name, it, sets):
    """One classified row for a pack dir whose intake.json parsed and carries content_tokens."""
    st, detail = scan_state(d, name)
    row = dict(pack=name, tokens=it["content_tokens"], scan=st, scan_detail=detail, selectable=(st == "PASS"))
    if sets:
        nev = [0] * len(sets)
        for l in open(os.path.join(d, "ledger.jsonl")):
            for sp in json.loads(l)["spans"]:
                ln = sp["token_end"] - sp["token_start"]
                for i, (_, s) in enumerate(sets):
                    if sp["sha256"] not in s: nev[i] += ln
        row["never_trained"] = {n: v for (n, _), v in zip(sets, nev)}; row["never_trained_min"] = min(nev)
    return row


_REV = re.compile(r"^(.*?)(?:-r(\d+))?$")


def mark_superseded(rows):
    """lead 83018: a pack and its -r1/-r2 repacks are ONE pack. Group rows by base name (name minus a trailing -r<N>; no suffix = rank 0); the highest rank is kept,
    every older member gets row['superseded_by'] = <newest name> (None on the kept row). Mutates the rows; returns the number superseded. Pure on names."""
    groups = collections.defaultdict(list)
    for r in rows:
        m = _REV.match(r["pack"]); groups[m.group(1)].append((int(m.group(2) or 0), r))
    n = 0
    for g in groups.values():
        g.sort(key=lambda x: x[0]); newest = g[-1][1]["pack"]
        for _, r in g[:-1]: r["superseded_by"] = newest; n += 1
        g[-1][1]["superseded_by"] = None
    return n


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--trained", action="append", default=[]); ap.add_argument("--out", default=OUT)
    a = ap.parse_args(argv)
    sets = []; trained_errors = []
    for t in a.trained:
        p, _, e = t.rpartition(":")
        if not e.isdigit(): p, e = t, ""      # no END_POS given (the colon was the drive letter's)
        try: sets.append((os.path.basename(p), trained_set(p, int(e) if e else 10**15)))
        except Exception as ex: trained_errors.append(dict(trained=t, reason="%s: %s" % (type(ex).__name__, str(ex)[:100])))      # a missing/unreadable ledger is a reason in the output, not an abort
    rows = []; skipped = []; seen = 0
    for d in sorted(glob.glob(os.path.join(PACKED, "*/"))):
        name = os.path.basename(d.rstrip("/\\")); ip = os.path.join(d, "intake.json"); seen += 1
        if not os.path.isfile(ip): skipped.append(dict(pack=name, reason="no_intake_json")); continue
        try:
            it = json.load(open(ip))
            if not isinstance(it, dict): raise ValueError("intake.json is not a JSON object")
        except Exception as ex:
            rows.append(dict(pack=name, tokens=0, scan="NOT RUN", scan_detail="malformed intake.json", selectable=False, error="malformed intake.json: %s" % str(ex)[:100])); continue
        ct = it.get("content_tokens")
        if isinstance(ct, bool) or not isinstance(ct, int): skipped.append(dict(pack=name, reason="missing_content_tokens")); continue
        try: rows.append(_row_for(d, name, it, sets))
        except Exception as ex: rows.append(dict(pack=name, tokens=ct, scan="NOT RUN", scan_detail="row failed", selectable=False, error="%s: %s" % (type(ex).__name__, str(ex)[:100])))
    mark_superseded(rows)
    tot = collections.OrderedDict(); sup = dict(packs=0, tokens=0)
    for r in rows:
        if r.get("superseded_by"): r["selectable"] = False; r["scan_detail"] += "; superseded by %s" % r["superseded_by"]; sup["packs"] += 1; sup["tokens"] += r["tokens"]; continue      # superseded rows are listed, never counted in the totals
        k = r["scan"]; tot.setdefault(k, dict(packs=0, tokens=0, never_trained_min=0))
        tot[k]["packs"] += 1; tot[k]["tokens"] += r["tokens"]; tot[k]["never_trained_min"] += r.get("never_trained_min", 0)
    residual = dict(dirs_seen=seen, dirs_classified=len(rows), dirs_skipped=skipped)
    out = dict(rows=rows, totals=tot, superseded_not_counted=sup, trained_sets=[n for n, _ in sets], trained_errors=trained_errors, residual=residual)
    tmp = a.out + ".part"; json.dump(out, open(tmp, "w"), indent=1); os.replace(tmp, a.out)
    for r in rows: print("%-30s %-8s tokens %14d%s  %s%s" % (r["pack"], r["scan"], r["tokens"], ("  never %14d" % r["never_trained_min"]) if "never_trained_min" in r else "", r["scan_detail"], ("  ERROR " + r["error"]) if r.get("error") else ""))
    for k, v in tot.items(): print("TOTAL %-8s packs %3d tokens %14d%s" % (k, v["packs"], v["tokens"], ("  never-trained(min) %14d" % v["never_trained_min"]) if sets else ""))
    print("SUPERSEDED (listed, not in any TOTAL) packs %d tokens %d" % (sup["packs"], sup["tokens"]))
    print("RESIDUAL dirs seen %d = classified %d + skipped %d%s" % (seen, len(rows), len(skipped), "".join("  [%s: %s]" % (x["pack"], x["reason"]) for x in skipped)))
    for x in trained_errors: print("TRAINED LEDGER NOT READ: %s (%s)" % (x["trained"], x["reason"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
