# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Reds/greens for the M-NET-2 arbiter (lead 82238). Run: python scripts/tests/net_cap_red_test.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from lane_config import LANE_ROOT
import os, sys, json, time, tempfile, shutil, threading, http.server, hashlib
pass
import net_cap as N
ok = True
def check(l, c):
    global ok; ok &= bool(c); print("PASS" if c else "FAIL", l)
# ---- decide(): pure state machine
s = {}; s, a = N.decide(s, 0, 3, 0.1); check("queue>0 + low uplink starts the 120 s clock, no cap yet", a is None and s["low_since"] == 0)
s, a = N.decide(s, 119, 3, 0.1); check("RED at 119 s still off", a is None and not s.get("on"))
s, a = N.decide(s, 120, 3, 0.1); check("GREEN at 120 s the cap turns ON", a == "on" and s["on"])
s2, a = N.decide({}, 0, 3, 0.1); s2, a = N.decide(s2, 60, 3, 5.0); s2, a = N.decide(s2, 130, 3, 0.1); check("RED a good-uplink sample resets the clock (no cap at 130 s)", a is None and not s2.get("on"))
s3, a = N.decide({}, 0, 0, 0.1); s3, a = N.decide(s3, 500, 0, 0.1); check("RED empty queue never turns the cap on", a is None and not s3.get("on"))
s, a = N.decide(s, 200, 0, 0.1); s, a = N.decide(s, 229, 0, 0.1); check("RED queue empty 29 s: still on (debounce)", a is None and s["on"])
s, a = N.decide(s, 230, 0, 0.1); check("GREEN queue empty 30 s: cap lifts", a == "off" and not s["on"])
s, a = N.decide({"on": True}, 0, 0, 0); s, a = N.decide(s, 10, 2, 0); s, a = N.decide(s, 100, 0, 0); check("RED a queue refill resets the off timer", a is None and s["on"])
# ---- share + pacing
T = tempfile.mkdtemp(dir=(LANE_ROOT + "/scratch")); N.STATE = T + "/cap.json"; N.SHARE_PATH = T + "/share"; os.makedirs(N.SHARE_PATH)
check("no state file -> no share (cap off)", N.share_mbps() is None)
json.dump({"on": False, "cap_mbps": 2.5}, open(N.STATE, "w")); check("cap off -> None", N.share_mbps() is None)
json.dump({"on": True, "cap_mbps": 2.5}, open(N.STATE, "w"))
for pid in (1, 2, 3, 4, 5): open(f"{N.SHARE_PATH}/{pid}", "w").close()
check("GREEN cap on, 5 active downloaders -> 0.5 MB/s each (sum 2.5)", abs(N.share_mbps() - 0.5) < 1e-9)
old = time.time() - 100; os.utime(f"{N.SHARE_PATH}/1", (old, old)); check("a stale registry entry (100 s) is not counted", abs(N.share_mbps() - 2.5 / 4) < 1e-9)
check("pacing: 2 MiB read at 1 MiB/s over 0 s must sleep ~2 s", 1.9 < N.paced_sleep(2 * 2**20, time.time(), 1.0) < 2.1)
# ---- download(): local HTTP server with Range support
DATA = os.urandom(3 * 2**20); SHA = hashlib.sha256(DATA).hexdigest()
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        rg = self.headers.get("Range"); a = int(rg.split("=")[1].rstrip("-")) if rg else 0; body = DATA[a:]
        self.send_response(206 if rg else 200); self.send_header("Content-Length", str(len(body)))
        if rg: self.send_header("Content-Range", f"bytes {a}-{len(DATA)-1}/{len(DATA)}")
        self.end_headers(); self.wfile.write(body)
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
N.BASE = f"http://127.0.0.1:{srv.server_address[1]}"
json.dump({"on": False}, open(N.STATE, "w")); t0 = time.time(); p = N.download("o/r", "d/f.bin", local_dir=T + "/dl")
check("GREEN uncapped download is intact (sha) and fast", hashlib.sha256(open(p, "rb").read()).hexdigest() == SHA and time.time() - t0 < 2.5)
os.remove(p); open(p + ".part", "wb").write(DATA[:1_000_000]); p = N.download("o/r", "d/f.bin", local_dir=T + "/dl")
check("GREEN Range resume from a .part completes with the right bytes", hashlib.sha256(open(p, "rb").read()).hexdigest() == SHA)
os.remove(p); [os.remove(f"{N.SHARE_PATH}/{x}") for x in os.listdir(N.SHARE_PATH)]
json.dump({"on": True, "cap_mbps": 1.5}, open(N.STATE, "w")); t0 = time.time(); p = N.download("o/r", "d/g.bin", local_dir=T + "/dl"); dt = time.time() - t0
check(f"RED capped download (1.5 MB/s share, 3 MiB) takes >=1.2 s, the first MiB is free after the rate change (took {dt:.2f})", dt >= 1.2 and hashlib.sha256(open(p, "rb").read()).hexdigest() == SHA)
srv.shutdown(); shutil.rmtree(T, ignore_errors=True)
# ---- pace(): aggregate pacer across threads
T2 = tempfile.mkdtemp(dir=(LANE_ROOT + "/scratch")); N.STATE = T2 + "/cap.json"; N.SHARE_PATH = T2 + "/share"; os.makedirs(N.SHARE_PATH); json.dump({"on": True, "cap_mbps": 2.0}, open(N.STATE, "w"))
N._next[0] = 0.0; t0 = time.time(); ths = [threading.Thread(target=lambda: [N.pace(512 * 1024) for _ in range(2)]) for _ in range(4)]; [t.start() for t in ths]; [t.join() for t in ths]; dt = time.time() - t0
check(f"RED pace(): 4 MiB over 4 threads at a 2 MiB/s share take >=1.5 s (took {dt:.2f})", dt >= 1.5)
json.dump({"on": False}, open(N.STATE, "w")); N._next[0] = 0.0; t0 = time.time(); N.pace(50 * 2**20); check("GREEN pace(): no sleep while the cap is off", time.time() - t0 < 0.5)
shutil.rmtree(T2, ignore_errors=True)
src = open((LANE_ROOT + "/scripts/net_arbiter.py"), encoding="utf-8").read()
check("arbiter writes ledger rows for on/off and a 10-min check row", "net-cap-ledger" in open((LANE_ROOT + "/scripts/net_cap.py"), encoding="utf-8").read() and '"check"' in src)
print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)
