# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Interim guard (lead 83073), until the th_gate vanish-after-open PR merges: a clean TruffleHog verdict is valid for a push only if Get-MpThreatDetection shows NO detection on a scan scratch path inside that scan's window.
check(row_path) -> (ok, why). Cannot check (query fails, row unreadable) -> not ok: the upload tick does not push. Window = [row ts - scan_s - 180 s, row ts + 120 s]; a row without scan_s (older per-part scans) = [ts - 3600 s, ts + 120 s].
Paths counted: only detections whose resource is a part of THIS scan (th-* scratch dir, part file named <k>-<pack name>-...), not other scans' parts in the same window. Reads Defender's own detection history; changes nothing."""
import json, re, subprocess, datetime as dt

def check(row_path):
    try:
        row = json.load(open(row_path, encoding="utf-8"))
        end = dt.datetime.strptime(row["ts"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
        w0 = end - dt.timedelta(seconds=float(row.get("scan_s") or 3600) + 180); w1 = end + dt.timedelta(seconds=120)
    except Exception as e:
        return False, "defender guard: scan row unreadable (%s)" % type(e).__name__
    stem = str(row.get("name", "")); stem = stem[6:] if stem.startswith("train-") else stem
    if not stem: return False, "defender guard: scan row has no pack name"
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", stem): return False, "defender guard: unexpected pack name"
    own = r"th-[a-z0-9]+[\\/]\d+-" + stem + "-"      # THIS scan's own parts only: scratch dir th-*, part name <k>-<pack object name>; another scan's detection in the same window never holds this pack (lead 83081)
    ps = ("$a=[datetime]::Parse('%s').ToUniversalTime();$b=[datetime]::Parse('%s').ToUniversalTime();"
          "Get-MpThreatDetection | Where-Object { $_.InitialDetectionTime.ToUniversalTime() -ge $a -and $_.InitialDetectionTime.ToUniversalTime() -le $b -and (($_.Resources -join ';') -match '%s') } | ForEach-Object { $_.ThreatID }"
          % (w0.strftime("%Y-%m-%dT%H:%M:%SZ"), w1.strftime("%Y-%m-%dT%H:%M:%SZ"), own))
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=120)
    except Exception as e:
        return False, "defender guard: cannot query detections (%s)" % type(e).__name__
    if r.returncode != 0: return False, "defender guard: detection query rc %d" % r.returncode
    ids = [x for x in r.stdout.split() if x.strip()]
    if ids: return False, "defender guard: %d Defender detection(s) on a scan scratch path inside the scan window (threat ids %s)" % (len(ids), ",".join(sorted(set(ids))))
    return True, "no Defender detection on scan scratch in the window"

if __name__ == "__main__":
    import sys
    if sys.argv[1:] == ["selftest"]:
        import tempfile, os
        d = tempfile.mkdtemp(); p = os.path.join(d, "r.json")
        json.dump(dict(name="train-stackv2_edu-00006-00011", ts="2026-11-11T03:22:26Z", scan_s=30), open(p, "w")); ok, why = check(p); print("this scan's own detection (stackv2 part014, 12:22) ->", ok, why); assert not ok
        json.dump(dict(name="train-usgpo-00003-00006", ts="2026-11-11T03:22:26Z", scan_s=30), open(p, "w")); ok, why = check(p); print("another scan's detection in the same window ->", ok, why); assert ok
        json.dump(dict(name="train-stackv2_edu-00006-00011", ts="2026-11-10T00:00:00Z", scan_s=30), open(p, "w")); ok, why = check(p); print("window without a detection ->", ok, why); assert ok
        open(p, "w").write("{"); ok, why = check(p); print("unreadable row ->", ok, why); assert not ok
        os.remove(p); os.rmdir(d); print("ALL PASS")
    else:
        print(check(sys.argv[1]))
