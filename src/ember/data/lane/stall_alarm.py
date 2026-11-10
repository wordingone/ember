# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""No-progress alarm (lead 81807). Called from tick.py done() on every tick (and runnable alone).
Progress = bytes landed by the shared uploader (upq/stats.json uploaded_bytes) + bytes read from staged files by any live push process (upload_file subprocess of upload_worker, hf upload pack pushes).
If the uploader queue is non-empty or a pack push is alive AND progress has not increased for STALL_ALARM_S (default 600 s), mail lead ONCE (again after 60 min if still flat) with queue size,
last landed file and socket states of the push processes. State: upq/alarm-state.json (override with STALL_ALARM_STATE / STALL_ALARM_S for tests)."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT, M_ROOT, SEAT_LEAD
import os, sys, json, time, subprocess, collections, re
import psutil
pass
from lane_config import LANE_ROOT as ROOT; Q = ROOT + "/upq"; STATE = os.environ.get("STALL_ALARM_STATE", Q + "/alarm-state.json")
THRESH = float(os.environ.get("STALL_ALARM_S", "600")); REPEAT = 3600
MB = (M_ROOT + "/avir/infra/mailbox/target/release/mailbox.exe")
def pushes():
    out = []
    for p in psutil.process_iter(["pid", "cmdline"]):
        c = p.info["cmdline"] or []; j = " ".join(c)
        if c and "python" in c[0].lower() and ("upload_file" in j or "hf.exe" in j and " upload " in j): out.append(p)
    return out

def heal(ps, prog_by_log, now):
    """Auto-heal (lead 81847): a pack push (hf upload) whose sockets sit in CLOSE_WAIT for >=120 s, or whose own progress (files + bytes in its log) is flat >=300 s, is restarted via kill_lane.ps1 (PID-verified, receipts);
    the tick relaunches it (resumable, never overwrites, capped at 5 relaunches). Uses state file alarm-heal.json."""
    hs = json.load(open(Q + "/alarm-heal.json")) if os.path.exists(Q + "/alarm-heal.json") else {}
    acts = []
    for lf, sig in prog_by_log.items():
        name = os.path.basename(lf)[len("hf-upload-"):-4]
        pk = [p for p in ps if "hf.exe" in " ".join(p.info["cmdline"] or []) and name.replace("train-", "") in " ".join(p.info["cmdline"] or [])]
        if not pk: hs.pop(name, None); continue
        cw = 0
        for p in pk:
            try: cw += sum(1 for c in p.net_connections() if c.status == "CLOSE_WAIT")
            except Exception: pass
        h = hs.setdefault(name, {"sig": None, "since": now, "cw_since": None})
        if h["sig"] != sig: h["sig"] = sig; h["since"] = now
        if cw and h["cw_since"] is None: h["cw_since"] = now
        if not cw: h["cw_since"] = None
        why = None
        if h["cw_since"] is not None and now - h["cw_since"] >= 120: why = f"CLOSE_WAIT socket for {now - h['cw_since']:.0f} s"
        elif now - h["since"] >= 300: why = f"no progress for {now - h['since']:.0f} s"
        if why:
            sel = ("hf upload wordingone/ember-train-private " + LANE_ROOT + "/packed/") + name.replace("train-", "")
            r = subprocess.run(["powershell", "-NoProfile", "-File", ROOT + "/scripts/kill_lane.ps1", "-Reason", f"auto-heal {name}: {why} (lead 81847); resumable push, tick relaunches", "-Only", sel], capture_output=True, text=True, timeout=120)
            acts.append(f"healed {name}: {why} -> {[x for x in r.stdout.splitlines() if 'STOPPED' in x]}"); hs.pop(name, None)
    json.dump(hs, open(Q + "/alarm-heal.json", "w"))
    return acts

def worker_diag(ps_all=None, log=ROOT + "/logs/backlog-upload-worker.log"):
    """lead 82236: the alarm body must say whether the uploader WORKER is alive, not only the push child ('push processes alive: none' is the normal state between retries and was read as 'uploader dead').
    Returns (verdict, text): verdict 'dead' | 'alive-retrying' | 'alive-moving-or-idle'."""
    pids = []
    for p in (ps_all if ps_all is not None else psutil.process_iter(["pid", "cmdline"])):
        c = p.info["cmdline"] or []
        if c and "python" in c[0].lower() and any(a.replace("\\", "/").endswith("scripts/upload_worker.py") for a in c[1:2]): pids.append(p.info["pid"])
    last = []
    try: last = [l.strip()[:150] for l in open(log, encoding="utf-8", errors="ignore").read().splitlines() if l.strip()][-2:]
    except Exception: pass
    try: a = psutil.net_io_counters(); time.sleep(5); b = psutil.net_io_counters(); nic = f"NIC now: down {(b.bytes_recv - a.bytes_recv)/5e6:.2f} MB/s, up {(b.bytes_sent - a.bytes_sent)/5e6:.2f} MB/s"
    except Exception: nic = "NIC n/a"
    verdict = "dead" if not pids else ("alive-retrying" if any(" stalled " in l or " FAILED " in l for l in last) else "alive-moving-or-idle")
    why = {"dead": "worker NOT running: the tick relaunches it this tick", "alive-retrying": "worker ALIVE and retrying; push children are killed between tries, so 'push processes: none' is normal here; a restart would not help, the link (uplink) is the limit",
           "alive-moving-or-idle": "worker alive; no recent failures in its log"}[verdict]
    return verdict, f"uploader worker pids {pids or 'none'}: {why}" + "\nlast worker log lines: " + str(last) + "\n" + nic


def heal_worker(qf, now, log=ROOT + "/logs/backlog-upload-worker.log", state=Q + "/alarm-heal-worker.json", kill=True):
    """Class fix (lead 82167): the shared uploader can be ALIVE yet failing every job (stale in-memory code, e.g. a removed reserve_plan.quiet_wait: AttributeError on each try), so 'no worker alive' never fires.
    If the queue is non-empty and the worker log's last 3 lines are all FAILED (log written in the last 15 min), restart it via kill_lane.ps1 (receipted); the tick relaunches it from current source. Cooldown 10 min. Returns a note or ''."""
    if qf <= 0 or not os.path.exists(log) or now - os.path.getmtime(log) > 900: return ""
    try: tail = [l for l in open(log, encoding="utf-8", errors="ignore").read().splitlines() if l.strip()][-3:]
    except Exception: return ""
    if len(tail) < 3 or not all(" FAILED " in l for l in tail): return ""
    hs = json.load(open(state)) if os.path.exists(state) else {}
    if now - hs.get("last", 0) < 600: return ""
    hs["last"] = now; json.dump(hs, open(state, "w"))
    if not kill: return "worker-heal would restart"
    why = "upload_worker alive but its last 3 log lines are FAILED with the queue non-empty (" + tail[-1][:90].replace('"', "'") + ") (lead 82167 class fix); tick relaunches from current source"
    r = subprocess.run(["powershell", "-NoProfile", "-File", ROOT + "/scripts/kill_lane.ps1", "-Reason", why, "-Only", "upload_worker.py"], capture_output=True, text=True, timeout=120)
    return "worker-healed: " + str([x.strip() for x in r.stdout.splitlines() if "STOPPED" in x][:3])

def _run_stall():
    try: st = json.load(open(Q + "/stats.json"))
    except Exception: st = {}
    now0 = time.time()
    ps = pushes(); rb = 0; socks = collections.Counter()
    for p in ps:
        try: rb += p.io_counters().read_bytes
        except Exception: pass
        try:
            for c in p.net_connections(): socks[c.status] += 1
        except Exception: pass
    import glob, re
    plog = {}
    for lf in glob.glob(ROOT + "/logs/hf-upload-*.log"):      # pack pushes (hf upload, xet) do not show as read_bytes: also count the CLI's own "transferred" progress while its log is fresh
        try:
            if now0 - os.path.getmtime(lf) > 900: continue
            tail = open(lf, "rb").read()[-600:].decode("utf-8", "ignore"); m = re.findall(r"([\d.]+)(MB|GB) transferred", tail)
            sig = ""
            if m: rb += int(float(m[-1][0]) * (1e9 if m[-1][1] == "GB" else 1e6)); sig += m[-1][0] + m[-1][1]
            n = re.findall(r"(\d+)/\d+ uploaded", tail)
            if n: rb += int(n[-1]) * 1000; sig += "|" + n[-1]     # completed-file count also counts as progress (resumed pushes dedupe bytes but still finish files)
            plog[lf] = sig
        except Exception: pass
    prog = st.get("uploaded_bytes", 0) + rb
    try: healed = heal(ps, plog, now0)
    except Exception as e: healed = [f"heal error {type(e).__name__} {str(e)[:80]}"]
    if healed: json.dump(dict(ts=now0, acts=healed), open(Q + "/last-heal.json", "w"))
    qf = len([f for f in os.listdir(Q) if f.endswith(".job.json")]) if os.path.isdir(Q) else 0
    try:
        wh = heal_worker(qf, now0)
        if wh: healed.append(wh)
    except Exception as e: healed.append(f"worker-heal error {type(e).__name__}")
    active = qf > 0 or any("hf.exe" in " ".join(p.info["cmdline"] or []) for p in ps)
    s = json.load(open(STATE)) if os.path.exists(STATE) else {}
    now = time.time()
    # a worker restart resets the push's read_bytes to 0, so progress may drop: treat any change as movement
    if s.get("prog") != prog or not active: s.update(prog=prog, since=now, alerted=0); json.dump(s, open(STATE, "w")); return ("HEAL: " + "; ".join(healed) if healed else "ok: " + ("idle" if not active else "moving"))
    flat = now - s.get("since", now)
    if flat >= THRESH and now - s.get("alerted", 0) >= REPEAT:
        last = ""
        try: last = [l for l in open(ROOT + "/logs/backlog-upload-worker.log", encoding="utf-8", errors="ignore") if " uploaded " in l][-1].strip()
        except Exception: pass
        qb = st.get("queue_bytes", 0)
        _wv, _wt = worker_diag(ps_all=None)
        body = (f"STALL ALARM: HF landed bytes flat for {flat/60:.0f} min while work is pending (threshold {THRESH/60:.0f} min).\nqueue: {qf} files {qb/2**30:.2f} GiB; push processes alive: {[p.pid for p in ps]}\n"
                f"{_wt}\nlast landed file: {last or 'n/a'}\nsocket states of push processes: {dict(socks) or 'none'}\nstats.json uploaded_bytes {st.get('uploaded_bytes',0)/2**30:.2f} GiB, heartbeat age "
                f"{(now - os.path.getmtime(Q + '/heartbeat')) if os.path.exists(Q + '/heartbeat') else -1:.0f} s\nAuto-mail from scripts/stall_alarm.py (lead 81807). Fix path: scripts/kill_lane.ps1 -Only upload_worker.py / the hf upload selector, then the tick relaunches.")
        subj = ("[TEST red, deliberate pause] " if os.environ.get("STALL_ALARM_TEST") else "") + f"STALL ALARM: HF uploads flat {flat/60:.0f} min, queue {qf} files"
        sys.path.insert(0, ROOT + "/scripts"); import mb_send
        try: mid = mb_send.send(SEAT_LEAD, subj, body)          # raises unless the id is confirmed by a mail_list readback (lead 81809)
        except Exception as e: return f"ALARM NOT DELIVERED (will retry next tick): {type(e).__name__} {str(e)[:160]}"
        s["alerted"] = now; json.dump(s, open(STATE, "w")); return f"ALARM delivered mail id {mid}, flat {flat/60:.0f} min"
    json.dump(s, open(STATE, "w")); return f"flat {flat/60:.1f} min (alarm at {THRESH/60:.0f})"
if __name__ == "__main__": print(run())

def run():
    """stall alarm + lead 81866 floor watch: mail lead (once/h) if B: free reads below 295 GiB; log the lease expiry once (floor returns to 301 automatically)."""
    r = _run_stall(); extra = ""
    try:
        import shutil
        free = shutil.disk_usage("B:/").free / 2**30; fs = ROOT + "/upq/floor-state.json"
        st = json.load(open(fs)) if os.path.exists(fs) else {}
        if free < 295 and time.time() - st.get("mailed", 0) > 3600:
            sys.path.insert(0, ROOT + "/scripts"); import mb_send
            mid = mb_send.send(SEAT_LEAD, f"B: BELOW 295 GiB: free {free:.1f} GiB", f"B free {free:.1f} GiB < 295 (lead 81866 asked for this mail). Lanes hold at their floors; the borrowing lane stages only items <= 3 GiB. Needs checkpoint/H44 space, not lane action."); st["mailed"] = time.time(); extra = f" B<295 mailed id {mid}"
        L = json.load(open(ROOT + "/loops/floor-borrow.json")) if os.path.exists(ROOT + "/loops/floor-borrow.json") else None
        if L and time.time() >= L["until_epoch"] and not st.get("expired_logged"): st["expired_logged"] = True; extra += " FLOOR LEASE EXPIRED: floor back to 301 (H44 window closed)"
        if L and time.time() < L["until_epoch"]: st["expired_logged"] = False
        json.dump(st, open(fs, "w"))
    except Exception as e: extra += f" floor-watch error {type(e).__name__}"
    try:
        import reserve_plan; extra += reserve_plan.alarm()
    except Exception as e: extra += f" reserve-plan error {type(e).__name__}"
    return r + extra
