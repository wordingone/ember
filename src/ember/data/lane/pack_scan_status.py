# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Pack TruffleHog scan status (lead 82613 item 3). One function decides what a pack's scan state is, and 'unknown' is never printed as 'running'.
Class closed: 'no record yet' was read as 'scan running' (2026-11-10: three C1/C2-PASSed packs sat REFUSED for 2 h while I reported them as scanning).
States:
  running  a live process whose cmdline names `th_pack_scan.py <name> ` exists (its pid is printed) and no final record covers the CURRENT file set
  clean    a record for the CURRENT file signature with clean=true, no hits, no error
  refused  a record for the CURRENT file signature that is not clean (hits or error), or a record that contradicts itself (fail closed)
  unknown  anything else: no record, a record for an older file set, an unreadable record, and no live scan process
Records are written ONCE at scan end (th_pack_scan.py), so 'no record' alone says nothing about a scan; only a live pid does.
Pure function: the record dir, the signature function and the pid lookup are injected, so the test needs no live lane."""
import json, os

def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            r = json.load(f)
        return r if isinstance(r, dict) else None
    except Exception:
        return None

def pack_scan_status(name, local, rec_dir, signature_fn, pids_fn):
    """-> (state, detail). state in running|clean|refused|unknown. detail is a short string with no secret values (detector COUNTS only)."""
    rec = _read(os.path.join(rec_dir, name + ".json"))
    try:
        cur = signature_fn(local)
    except Exception as e:
        cur = None
        sig_err = "signature unreadable (%s)" % type(e).__name__
    else:
        sig_err = None
    current = rec is not None and cur is not None and rec.get("signature") == cur
    if current:
        hits = rec.get("hits") or {}
        err = rec.get("error")
        if rec.get("clean") is True and not hits and not err:
            return "clean", "record clean for the current file set (scan start %s)" % rec.get("ts")
        n_files = len(rec.get("hit_files") or [])
        return "refused", "hits %s, hit files %d, error %s" % (json.dumps(hits, sort_keys=True), n_files, err)
    try:
        pids = list(pids_fn(name) or [])
    except Exception:
        pids = None
    if pids:
        return "running", "pid " + ",".join(str(p) for p in pids)
    if pids is None:
        why = "process lookup failed"
    elif sig_err:
        why = sig_err
    elif rec is None:
        why = "no scan record and no live scan process"
    else:
        why = "record is for an older file set and no live scan process"
    return "unknown", why

def status_line(name, state, detail):
    """Fixed wording per state; the word 'running' appears only for state running."""
    if state == "running": return "%s: TruffleHog scan running (%s)" % (name, detail)
    if state == "clean": return "%s: TruffleHog scan clean (%s)" % (name, detail)
    if state == "refused": return "%s: TRUFFLEHOG REFUSED push (%s); nothing uploaded" % (name, detail)
    return "%s: TruffleHog scan state UNKNOWN (%s); a scan will be started" % (name, detail)

def push_decision(state, was_pass):
    """Upload-tick gate (lead 82933). -> 'push' | 'wait' | 'skip' | 'escalate'.
    push      scan clean for the current file set.
    wait      a scan is running (transient; neither a push nor a blocked tick).
    skip      REFUSED or NOT RUN (unknown): no push attempt, no cap check, no mail, no blocked count; the trainable listing owns these packs.
    escalate  REFUSED but this queue item was PASS earlier (a clean verdict was recorded for it): a real regression, reported as a blocked tick."""
    if state == "clean": return "push"
    if state == "running": return "wait"
    if state == "refused": return "escalate" if was_pass else "skip"
    return "skip"
