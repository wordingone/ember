# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Pack TruffleHog scan status (lead 82613 item 3). One function decides what a pack's scan state is, and 'unknown' is never printed as 'running'.
Class closed: 'no record yet' was read as 'scan running' (2026-11-10: three C1/C2-PASSed packs sat REFUSED for 2 h while I reported them as scanning).
A scan record binds to the pack's file signature = (relative path, byte size) of every file. It does NOT bind to file content: a same-size rewrite of a shard keeps the old verdict.
States:
  running       a live process whose cmdline names `th_pack_scan.py <name> ` exists (its pid is printed) and no final record covers the CURRENT file set
  clean         a record for the CURRENT file signature with clean=true, no hits, no error (record_verdict: ONE rule, the trainable listing imports it)
  refused_hits  a record for the CURRENT file signature with hits and no error (or clean=true carrying hits: the hits win)
  error         a record for the CURRENT file signature with `error` set, an unreadable record, or a record that contradicts itself (fail closed); nothing was proven either way
  unknown       anything else: no record, a record for an older file set, and no live scan process; also ANY case where the process lookup failed (detail says so, LOOKUP_FAILED)
Records are written ONCE at scan end (th_pack_scan.py), so 'no record' alone says nothing about a scan; only a live pid does.
Pure function: the record dir, the signature function and the pid lookup are injected, so the test needs no live lane."""
import json, os

LOOKUP_FAILED = "process lookup failed"
MAX_SCAN_TRIES = 3

def _read(path):
    """-> (record|None, unreadable). A missing file is (None, False); a file that exists but is not a JSON object is (None, True)."""
    if not os.path.exists(path): return None, False
    try:
        with open(path, encoding="utf-8") as f:
            r = json.load(f)
        return (r, False) if isinstance(r, dict) else (None, True)
    except Exception:
        return None, True

def record_verdict(rec):
    """The single clean/hits/error rule for a scan record dict. -> 'clean' | 'refused_hits' | 'error'.
    error needs `error` set (or a record that says neither clean nor hits nor error: self-contradicting, fail closed); non-empty `hits` always wins over clean=true."""
    if not isinstance(rec, dict): return "error"
    if rec.get("error"): return "error"
    if rec.get("hits"): return "refused_hits"
    if rec.get("clean") is True: return "clean"
    return "error"

def record_clean(rec):
    return record_verdict(rec) == "clean"

TOP_HIT_TYPES = 5

def hit_summary(hits, n_files, row_path):
    """Capped hit text for mails and tick lines (lead 83120): the TOTAL plus the top TOP_HIT_TYPES detector types by count, the number of further types, the hit-file count and the PATH of the scan row that holds the full table. Counts only, never values."""
    items = sorted(((k, int(v)) for k, v in hits.items()), key=lambda kv: (-kv[1], kv[0]))
    top = ", ".join("%s %d" % kv for kv in items[:TOP_HIT_TYPES]); more = len(items) - TOP_HIT_TYPES
    return "%d hits in %d types (top %d: %s%s), hit files %d, full table in %s" % (sum(v for _, v in items), len(items), min(TOP_HIT_TYPES, len(items)), top, (", +%d more types" % more) if more > 0 else "", n_files, row_path.replace("\\", "/"))

def pack_scan_status(name, local, rec_dir, signature_fn, pids_fn):
    """-> (state, detail). state in running|clean|refused_hits|error|unknown. detail is a short string with no secret values (detector COUNTS only)."""
    rec, unreadable = _read(os.path.join(rec_dir, name + ".json"))
    try:
        cur = signature_fn(local)
    except Exception as e:
        cur = None
        sig_err = "signature unreadable (%s)" % type(e).__name__
    else:
        sig_err = None
    current = rec is not None and cur is not None and rec.get("signature") == cur
    if current:
        v = record_verdict(rec)
        if v == "clean":
            return "clean", "record clean for the current file set (scan start %s)" % rec.get("ts")
        if v == "refused_hits":
            n_files = len(rec.get("hit_files") or [])
            return "refused_hits", hit_summary(rec.get("hits") or {}, n_files, os.path.join(rec_dir, name + ".json"))
    # not a final verdict for the current file set (error record, unreadable record, stale or missing record): a live scan process still decides
    try:
        pids = list(pids_fn(name) or [])
    except Exception:
        pids = None
    if pids:
        return "running", "pid " + ",".join(str(p) for p in pids)
    if pids is None:
        return "unknown", LOOKUP_FAILED
    if current:
        return "error", "scanner error: %s" % (rec.get("error") or "record says neither clean nor hits")
    if unreadable:
        return "error", "scan record unreadable"
    if sig_err:
        return "unknown", sig_err
    if rec is None:
        return "unknown", "no scan record and no live scan process"
    return "unknown", "record is for an older file set and no live scan process"

def status_line(name, state, detail):
    """Fixed wording per state; the word 'running' appears only for state running."""
    if state == "running": return "%s: TruffleHog scan running (%s)" % (name, detail)
    if state == "clean": return "%s: TruffleHog scan clean (%s)" % (name, detail)
    if state == "refused_hits": return "%s: TRUFFLEHOG REFUSED push (%s); nothing uploaded" % (name, detail)
    if state == "error": return "%s: TruffleHog scan ERROR (%s); nothing uploaded" % (name, detail)
    return "%s: TruffleHog scan state UNKNOWN (%s)" % (name, detail)

DECISIONS = ("push", "wait", "skip", "escalate", "rescan")

def push_decision(state, was_pass, scan_tries=0, lookup_failed=False):
    """Upload-tick gate (lead 82933). -> exactly one of 'push' | 'wait' | 'skip' | 'escalate' | 'rescan'. The caller must treat ANYTHING other than 'push' as no push.
    push      scan clean for the current file set.
    wait      a scan is running, or the process lookup failed (never spawn on a failed lookup): neither a push nor a blocked tick.
    rescan    state error or unknown, fewer than MAX_SCAN_TRIES scans started so far: start one scan (the tick counts it in the queue item's scan_tries).
    escalate  error/unknown after MAX_SCAN_TRIES scans, or REFUSED by hits for an item that was PASS earlier (was_pass: a clean verdict, a recorded push start): blocked tick; the error case also mails once.
    skip      REFUSED by hits and never PASS: no push, no cap check, no mail, no blocked count; the trainable listing owns these packs."""
    if state == "clean": return "push"
    if state == "running": return "wait"
    if state == "refused_hits": return "escalate" if was_pass else "skip"
    if state in ("error", "unknown"):
        if lookup_failed: return "wait"
        return "rescan" if int(scan_tries or 0) < MAX_SCAN_TRIES else "escalate"
    return "skip"
