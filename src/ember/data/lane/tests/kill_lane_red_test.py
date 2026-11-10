# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Red/green test for kill_lane.ps1 (python port of kill_lane_red_test.ps1; the ps1 form is launcher-shaped to the repo guard).
Stand-in "foreign python": a copy of ping.exe named python_dummy.exe under a child_nll_dummy folder (matches the helper's ^python name filter but is NOT a real python,
so the test does not disturb any python census). Uses a temp receipt file and a temp spawn file, never the real ones."""
import os, sys, json, time, shutil, tempfile, subprocess, psutil

HELPER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "kill_lane.ps1")
tmp = tempfile.mkdtemp(prefix="klt-"); dd = os.path.join(tmp, "child_nll_dummy"); os.makedirs(dd)
dummy = os.path.join(dd, "python_dummy.exe"); shutil.copy(os.path.join(os.environ["WINDIR"], "System32", "PING.EXE"), dummy)
rcpt = os.path.join(tmp, "receipts.jsonl"); spawn = os.path.join(tmp, "spawn.jsonl"); fail = 0
NOWIN = 0x08000000      # CREATE_NO_WINDOW


def alive(pid):
    try: return psutil.Process(pid).is_running()
    except psutil.Error: return False


def check(name, cond):
    global fail
    print(("PASS  " if cond else "FAIL  ") + name)
    if not cond: fail += 1


def helper(reason):
    return subprocess.run(["powershell", "-NoProfile", "-File", HELPER, "-Reason", reason, "-SpawnFile", spawn, "-ReceiptFile", rcpt], capture_output=True, text=True).stdout


def write_spawn(**row):
    open(spawn, "w", encoding="utf-8").write(json.dumps(row, separators=(",", ":")) + "\n" if row else "")


def start(cmdline):
    return subprocess.Popen(cmdline, creationflags=NOWIN, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def kill_dummies():
    for p in psutil.process_iter(["name"]):
        if (p.info["name"] or "").lower() == "python_dummy.exe":
            try: p.kill()
            except psutil.Error: pass


try:
    # RED 1: foreign "python" not in the spawn file -> must survive, must be reported
    f1 = start([dummy, "-n", "60", "127.0.0.1"]); write_spawn()
    o = helper("red1")
    check("RED1 foreign python not in spawn file survives", alive(f1.pid))
    check("RED1 foreign python is reported", str(f1.pid) in o)

    # RED 2: spawn-file entry for the foreign pid but wrong spawn time (PID reuse) -> refused, survives
    write_spawn(pid=f1.pid, ts=time.time() - 3600, cmd=dummy)
    o = helper("red2")
    check("RED2 recorded pid with mismatched creation time is refused and survives", alive(f1.pid) and "REFUSED entries: 1" in o)
    f1.kill()

    # RED 3: lane wrapper (recorded, correct time + cmd) that has a FOREIGN python descendant -> whole entry refused, nothing killed
    cmd3 = '"%s" -n 60 127.0.0.1' % dummy
    w3 = start("cmd.exe /c " + cmd3); time.sleep(2)
    write_spawn(pid=w3.pid, ts=time.time(), cmd=cmd3)
    o = helper("red3")
    check("RED3 wrapper with foreign python descendant is refused, wrapper and child survive", alive(w3.pid) and "foreign python" in o)
    kill_dummies(); w3.kill()

    # GREEN: genuine lane job (recorded, no python descendant) -> stopped, receipt row written first with selector note
    cmd4 = "ping -n 60 127.0.0.1 >nul & rem scripts/dummy_lane_job.py"
    w4 = start("cmd.exe /c " + cmd4); time.sleep(2)
    write_spawn(pid=w4.pid, ts=time.time(), cmd=cmd4)
    o = helper("green"); time.sleep(2)
    check("GREEN recorded lane job is stopped", not alive(w4.pid))
    check("GREEN receipt row names the selector", "spawn-pid-file root pid" in open(rcpt, encoding="utf-8").read())
finally:
    kill_dummies(); shutil.rmtree(tmp, ignore_errors=True)
print("RESULT: %s" % ("%d FAILED" % fail if fail else "all passed")); sys.exit(1 if fail else 0)
