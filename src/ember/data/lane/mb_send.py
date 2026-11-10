# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Send a mail via the mailbox MCP server (stdio JSON-RPC) and READ IT BACK by subject; raises if the id is not confirmed (lead 81809: the mailbox.exe CLI has no `send` subcommand, exits 0 and sends nothing)."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import M_ROOT, SEAT_DATA
import subprocess, json, sys, time, threading, queue
MB = (M_ROOT + "/avir/infra/mailbox/target/release/mailbox.exe")
def send(to, subject, body, identity=SEAT_DATA, timeout=60):
    pr = subprocess.Popen([MB, "--identity", identity, "--no-notify"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
    q = queue.Queue()
    threading.Thread(target=lambda: [q.put(l) for l in pr.stdout], daemon=True).start()
    def rpc(i, method, params=None, notify=False):
        m = {"jsonrpc": "2.0", "method": method}
        if params is not None: m["params"] = params
        if not notify: m["id"] = i
        pr.stdin.write(json.dumps(m) + "\n"); pr.stdin.flush()
        if notify: return None
        end = time.time() + timeout
        while time.time() < end:
            try: l = q.get(timeout=1)
            except queue.Empty: continue
            try: r = json.loads(l)
            except Exception: continue
            if r.get("id") == i: return r
        raise RuntimeError(f"mailbox MCP: no reply to {method}")
    try:
        rpc(1, "initialize", {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "stall-alarm", "version": "1"}})
        rpc(0, "notifications/initialized", notify=True)
        r = rpc(2, "tools/call", {"name": "mail_send", "arguments": {"to": to, "subject": subject, "body": body}})
        txt = json.dumps(r)
        if r.get("error") or r.get("result", {}).get("isError"): raise RuntimeError("mail_send error: " + txt[:300])
        m = None
        for c in r["result"].get("content", []):
            try: m = json.loads(c["text"]).get("id") or m
            except Exception: pass
        if m is None: raise RuntimeError("mail_send returned no id: " + txt[:300])
        # read back: the sent message must be listed from me, with this id and subject
        r2 = rpc(3, "tools/call", {"name": "mail_list", "arguments": {"from": identity, "limit": 10}})
        t2 = json.dumps(r2)
        ok = False
        for c in r2["result"].get("content", []):
            try:
                d = json.loads(c["text"])
                for x in (d.get("messages") if isinstance(d, dict) else d) or []:
                    if x.get("id") == m and x.get("subject") == subject: ok = True
            except Exception: pass
        if not ok: raise RuntimeError(f"sent id {m} NOT confirmed by mail_list readback: " + t2[:300])
        return m
    finally:
        try: pr.stdin.close()
        except Exception: pass
        try: pr.wait(timeout=5)
        except Exception: pr.kill()
if __name__ == "__main__": print(send(sys.argv[1], sys.argv[2], sys.argv[3]))
