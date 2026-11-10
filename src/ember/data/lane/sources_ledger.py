# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""D1 (lead 82134, Studio spec v5 s3.1.4): derive ember-sources-ledger-v1 rows from data's lane state and receipts.
Row: {schema, source_id, name, modality, licence_verdict (pending|accepted|refused|private_only), state (candidate|queued|downloading|packed|uploaded),
      bytes_expected, bytes_done, link_job_id, eta_s, receipts[]}
Inputs (read only): packed/*/intake.json + media-packed/*/intake.json (packed datasets), loops/approved-uploads.json (verified uploads), logs/licence-audit-20261109.json
(rehost verdict), the tick BACKLOG lane table (scripts/loops/tick.py ids), bulk/<lane>/progress.json (bytes done), loops/spawn-pids.jsonl (live job ids), process list, loops/net-last.json (downlink).
eta_s = bytes_remaining / measured_downlink (AT-LIB-6) for a downloading source with a known expected size, else null. No number is invented: unknown sizes are null.
Output: loops/sources-ledger.jsonl, written to a temp file then os.replace (atomic). Usage: python scripts/sources_ledger.py [--out PATH] [--check]   (--check validates the written file)
Run it from the tick (or by hand); it needs no disk beyond the file itself. Red: python scripts/tests/sources_ledger_red_test.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import os, sys, json, glob, time, re, hashlib
from lane_config import LANE_ROOT as ROOT; OUT = ROOT + "/loops/sources-ledger.jsonl"; SCHEMA = "ember-sources-ledger-v1"
STATES = ("candidate", "queued", "downloading", "packed", "uploaded"); VERDICTS = ("pending", "accepted", "refused", "private_only")
FIELDS = ("schema", "source_id", "name", "modality", "licence_verdict", "state", "bytes_expected", "bytes_done", "link_job_id", "eta_s", "receipts", "bytes_expected_reason")
# lane id -> (modality, directory that holds its progress.json / receipts); only DATA-SOURCE lanes of the tick backlog (no repair/audit jobs)
LANES = {"bulk-mls": ("audio", "bulk/mls"), "bulk-pd12m": ("image", "bulk/pd12m"), "bulk-ccby": ("image", "bulk/ccby"), "image-ccby-pack": ("image", "staging/ccby-pack"),
         "text-pre1929": ("text", "bulk/pre1929"), "text-caselaw": ("text", "bulk/caselaw"), "text-hansard": ("text", "bulk/hansard"), "text-usgpo": ("text", "bulk/usgpo"),
         "text-stackv2_edu": ("text", "bulk/stackv2_edu"), "text-arxiv_papers": ("text", "bulk/arxiv_papers"), "text-github_archive": ("text", "bulk/github_archive"),
         "text-uspto": ("text", "bulk/uspto"), "audio-mls-pack": ("audio", "staging/mls-pack"), "text-loc": ("text", "bulk/loc"), "text-pes2o": ("text", "bulk/pes2o"),
         "text-pubmed": ("text", "bulk/pubmed"), "se-drive": ("text", "se-20221005/work")}
ALIVE = {"bulk-mls": "bulk_lane.py mls", "bulk-pd12m": "bulk_lane.py pd12m", "bulk-ccby": "bulk_lane.py ccby", "image-ccby-pack": "ccby_pack.py", "audio-mls-pack": "mls_pack.py", "se-drive": "se_drive.py"}
_RS_CACHE = {}; _RS_OFF = False      # tests set _RS_OFF=True to use fixture progress.json only
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
DONE = {"image-ccby-pack": "staging/ccby-pack/ALL.done", "audio-mls-pack": "staging/mls-pack/ALL.done", "se-drive": "se-20221005/work/ALL.done"}


def _j(p, d=None):
    try: return json.load(open(p, encoding="utf-8"))
    except Exception: return d


def sid(kind, name): return f"src-{kind}-{hashlib.sha256((kind + ':' + name).encode()).hexdigest()[:12]}"


def dir_bytes(d):
    t = 0
    for dp, _, fs in os.walk(d):
        for f in fs:
            try: t += os.path.getsize(os.path.join(dp, f))
            except OSError: pass
    return t


def cmdlines():
    try:
        import psutil
        return [" ".join(p.info["cmdline"] or []) for p in psutil.process_iter(["cmdline"])]
    except Exception: return []


def downlink_bps(now=None):
    """Measured downlink from two samples of the NIC rx counter; the previous sample is kept in loops/net-prev.json. None if no usable interval yet."""
    now = now or time.time(); cur = _j(ROOT + "/loops/net-last.json"); prev = _j(ROOT + "/loops/net-prev.json")
    if not cur or "rx" not in cur: return None
    bps = None
    if prev and cur["t"] - prev["t"] >= 30 and cur["rx"] >= prev["rx"]: bps = (cur["rx"] - prev["rx"]) / (cur["t"] - prev["t"])
    elif prev and prev.get("bps"): bps = prev["bps"]
    if not prev or cur["t"] - prev["t"] >= 30:
        try: json.dump(dict(rx=cur["rx"], t=cur["t"], bps=bps), open(ROOT + "/loops/net-prev.json", "w"))
        except Exception: pass
    return bps if bps and bps > 0 else None


def licence_map():
    a = _j(ROOT + "/logs/licence-audit-20261109.json", {}); out = {}
    for k, v in a.items():
        rh = str(v.get("rehost", "")).upper()
        out[k] = "private_only" if "PRIVATE" in rh else ("refused" if rh.startswith(("NO", "REFUS")) else ("accepted" if rh.startswith("PUBLIC") else "pending"))
    return out


def rows(now=None):
    now = now or time.time(); out = []; lic = licence_map(); cl = cmdlines(); bps = downlink_bps(now)
    ups = {os.path.basename(str(u.get("local", "")).replace("\\", "/")): u for u in (_j(ROOT + "/loops/approved-uploads.json", []) or []) if u.get("verified")}
    pids = []
    for l in (open(ROOT + "/loops/spawn-pids.jsonl", encoding="utf-8-sig") if os.path.exists(ROOT + "/loops/spawn-pids.jsonl") else []):
        try: pids.append(json.loads(l.lstrip("﻿")))
        except Exception: pass      # a torn/BOM line must not stop the ledger
    # 1. packed datasets (text packed/, media media-packed/): bytes known exactly from the pack dir
    for base, defmod in (("packed", "text"), ("media-packed", None)):
        for ip in sorted(glob.glob(f"{ROOT}/{base}/*/intake.json")):
            it = _j(ip, {}); name = it.get("name") or os.path.basename(os.path.dirname(ip)); d = os.path.dirname(ip); n = dir_bytes(d)
            up = ups.get(name) or ups.get("train-" + name)
            rc = [os.path.relpath(ip, ROOT).replace("\\", "/")] + [os.path.relpath(x, ROOT).replace("\\", "/") for x in sorted(glob.glob(d + "/receipt*.json*"))]
            if up: rc.append(f"loops/approved-uploads.json#{up.get('name')}@{up.get('verified')}")
            out.append(dict(schema=SCHEMA, source_id=sid("pack", name), name=name, modality=it.get("modality") or defmod or "other", licence_verdict=lic.get(name, "pending"),
                            state="uploaded" if up else "packed", bytes_expected=n, bytes_done=n, link_job_id=None, eta_s=None, receipts=rc))
    # 2. lanes of the tick backlog (queued / downloading / finished)
    for lane, (mod, rel) in LANES.items():
        d = f"{ROOT}/{rel}"; prog = _j(d + "/progress.json", {}) or {}; done_marker = ROOT + "/" + DONE.get(lane, rel + "/ALL.done")
        pat = ALIVE.get(lane) or lane.replace("text-", "text_lane.py ")
        alive = any(pat in c and "tick.py" not in c and "sources_ledger" not in c for c in cl)
        done_b = int(prog.get("bytes_uploaded", 0) or 0); exp = prog.get("bytes_expected") or prog.get("total_bytes")
        state = "uploaded" if os.path.exists(done_marker) else ("downloading" if alive else "queued")
        job = None
        if state == "downloading":
            cand = [p for p in pids if pat in str(p.get("cmd", ""))]
            job = f"pid:{cand[-1]['pid']}" if cand else "tick-lane"
        if state in ("downloading", "queued") and not _RS_OFF:      # lead 82182 (4): bytes_expected from the REMOTE listing (scripts/remote_sizes.py, cached, never invented); done in the same unit
            try:
                import remote_sizes as _rs
                if lane not in _RS_CACHE: _RS_CACHE.update(_rs.refresh([lane]))
                rx, rd = _rs.expected_done(lane, _RS_CACHE)
                if rx: exp, done_b = rx, rd
            except Exception: pass
        rem = (exp - done_b) if (exp and state == "downloading") else None
        rc = [x for x in (rel + "/progress.json", rel + "/state.json") if os.path.exists(f"{ROOT}/{x}")] + [os.path.relpath(x, ROOT).replace("\\", "/") for x in sorted(glob.glob(d + "/receipt*.jsonl"))[:3]]
        out.append(dict(schema=SCHEMA, source_id=sid("lane", lane), name=lane, modality=mod, licence_verdict="pending", state=state, bytes_expected=int(exp) if exp else None,
                        bytes_done=done_b, link_job_id=job, eta_s=round(rem / bps) if (rem is not None and bps) else None, receipts=rc))
    return out


NULL_REASON = {"bulk-pd12m": "images are fetched from S3 per parquet row; no remote file listing gives their total size (no number invented)",
               "se-drive": "progress is counted in Stack Exchange sites (357/360), not bytes; no remote byte listing",
               "audio-mls-pack": "plan-B 500 h speaker-balanced subset: download volume is not known before selection"}
QUOTA_BOUND = ("bulk-ccby",)      # lane walks a 20 TB upstream set but stops at the 85% private quota: its own eta is not a finish time
SUMMARY = ROOT + "/loops/sources-ledger-summary.json"


def finish_reason(rs):
    """lead 82187: every row carries bytes_expected_reason (null when bytes_expected is known; else why it is null)."""
    for r in rs: r["bytes_expected_reason"] = None if r["bytes_expected"] is not None else NULL_REASON.get(r["name"], "no remote size available for this source")
    return rs


def summary(rs, now=None):
    """Honest clock (lead 82187): the lanes share ONE link, so the finish time is the SERIAL sum of remaining bytes / measured downlink, not the per-row eta_s (which assumes the whole link per row)."""
    now = now or time.time(); bps = downlink_bps(now); dl = [r for r in rs if r["state"] == "downloading" and r["bytes_expected"]]
    use = [r for r in dl if r["name"] not in QUOTA_BOUND]; rem = sum(r["bytes_expected"] - r["bytes_done"] for r in use)
    return dict(ts=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)), downlink_bps=bps, lanes_counted=[r["name"] for r in use], lanes_quota_bound_excluded=[r["name"] for r in dl if r["name"] in QUOTA_BOUND],
                bytes_remaining=rem, serial_eta_s=round(rem / bps) if bps else None, finish_epoch=round(now + rem / bps) if bps else None,
                note="serial sum: lanes share one link, so the finish time is total remaining bytes / measured downlink, not the per-row eta_s; quota-bound lanes are excluded; rows with null bytes_expected are not counted")


def validate(rs):
    """AT-LIB-6 shape check: every field present, enums valid, unique ids, eta only on downloading with a known remainder."""
    errs = []; seen = set()
    for r in rs:
        if tuple(r) != FIELDS: errs.append((r.get("name"), "fields", tuple(r))); continue
        if r["state"] not in STATES: errs.append((r["name"], "state", r["state"]))
        if r["licence_verdict"] not in VERDICTS: errs.append((r["name"], "licence_verdict", r["licence_verdict"]))
        if r["source_id"] in seen: errs.append((r["name"], "duplicate source_id"))
        seen.add(r["source_id"])
        if r["eta_s"] is not None and r["state"] != "downloading": errs.append((r["name"], "eta_s on a non-downloading row"))
        if r["eta_s"] is not None and r["bytes_expected"] is None: errs.append((r["name"], "eta_s without bytes_expected"))
        if (r["bytes_expected"] is None) != bool(r["bytes_expected_reason"]): errs.append((r["name"], "bytes_expected_reason must be set exactly when bytes_expected is null"))
        if not isinstance(r["receipts"], list): errs.append((r["name"], "receipts not a list"))
    return errs


def write(path=OUT):
    rs = finish_reason(rows()); errs = validate(rs)
    if errs: raise SystemExit(f"REFUSED: invalid rows {errs[:3]}")
    tmp = path + f".{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        for r in rs: f.write(json.dumps(r, sort_keys=False) + "\n")
    os.replace(tmp, path)
    if path == OUT:
        try: json.dump(summary(rs), open(SUMMARY + ".tmp", "w"), indent=1); os.replace(SUMMARY + ".tmp", SUMMARY)
        except Exception: pass
    return rs


if __name__ == "__main__":
    path = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else OUT
    if "--check" in sys.argv:
        rs = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]; e = validate(rs); print("CHECK", len(rs), "rows", "OK" if not e else e); sys.exit(1 if e else 0)
    rs = write(path); c = {}
    for r in rs: c[r["state"]] = c.get(r["state"], 0) + 1
    print(f"wrote {path}: {len(rs)} rows {c}")
