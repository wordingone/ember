# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Pack gates at intake and upload (#2449 item 2; lead 82716 item 3, 83284): a text pack is neither announced (intake.json) nor pushed until BOTH gates hold a PASS row
bound to the pack's CURRENT ledger sha256:
  degenerate  scripts/degenerate_scan.py PACK_DIR     (exit 0 clean; 1 refused objects; anything else = error, never a pass)
  heldout     scripts/heldout_check_pack.py NAME      (unsampled sentence hashes vs the full held-out index; exit 0 only with zero hit docs)
Rows live in logs/pack-gates/<gate>-<pack>.json (one file per gate and pack, overwritten by a newer run; the old row is kept as <name>.prev). A row carries the verdict,
the exit code and the last output lines (counts and object shas only; the scripts print no document text). A repacked pack has a new ledger sha, so its old rows are stale
(= pending). Fail closed: a missing, stale, errored or unreadable row is "pending", never "pass".
CLI: pack_gates.py run NAME [PACK_DIR]  | status NAME [PACK_DIR] | selftest.   Library: status(name, pack_dir) -> (state, detail), state in pass|refused|pending; run(name, pack_dir)."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import os, sys, json, time, hashlib, subprocess

from lane_config import LANE_ROOT as ROOT; OUT = ROOT + "/logs/pack-gates"; SCRIPTS = ROOT + "/scripts"
GATES = ("degenerate", "heldout")


def _sha256f(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
    return h.hexdigest()


def row_path(name, gate, out=None): return (out or OUT) + "/" + gate + "-" + name + ".json"


def _cmd(gate, name, pack_dir):
    if gate == "degenerate": return [sys.executable, SCRIPTS + "/degenerate_scan.py", pack_dir]
    return [sys.executable, SCRIPTS + "/heldout_check_pack.py", name]


def verdict_of(rc): return "pass" if rc == 0 else ("refused" if rc == 1 else "error")


def read_row(name, gate, out=None):
    try: return json.load(open(row_path(name, gate, out), encoding="utf-8"))
    except Exception: return None


def status(name, pack_dir, out=None):
    """-> (state, detail). pass = both rows pass and bound to the current ledger sha; refused = a current row refused; pending = anything else (missing, stale, error, unreadable)."""
    try: cur = _sha256f(pack_dir.rstrip("/\\") + "/ledger.jsonl")
    except Exception as e: return "pending", "no readable ledger (%s)" % type(e).__name__
    pend = []
    for g in GATES:
        r = read_row(name, g, out)
        if not isinstance(r, dict) or r.get("ledger_sha256") != cur: pend.append(g + ":" + ("missing" if r is None else "stale")); continue
        if r.get("verdict") == "refused": return "refused", "%s refused (%s)" % (g, str(r.get("summary", ""))[:160])
        if r.get("verdict") != "pass": pend.append(g + ":" + str(r.get("verdict", "unreadable")))
    return ("pending", ", ".join(pend)) if pend else ("pass", "degenerate+heldout PASS on ledger " + cur[:12])


def run(name, pack_dir, out=None, runner=None, env=None):
    """Run each gate that has no current PASS row and write its row. runner(cmd, env) -> (rc, text) lets a red inject outcomes. Returns the status after the run."""
    out = out or OUT; os.makedirs(out, exist_ok=True); pack_dir = pack_dir.rstrip("/\\")
    cur = _sha256f(pack_dir + "/ledger.jsonl")
    e = dict(os.environ); e.update(env or {})
    for g in GATES:
        r = read_row(name, g, out)
        if isinstance(r, dict) and r.get("ledger_sha256") == cur and r.get("verdict") in ("pass", "refused"): continue
        t0 = time.time(); cmd = _cmd(g, name, pack_dir)
        if runner: rc, text = runner(cmd, e)
        else:
            p = subprocess.run(cmd, capture_output=True, text=True, env=e); rc, text = p.returncode, (p.stdout or "") + (p.stderr or "")
        lines = [l for l in text.splitlines() if l.strip()]
        row = dict(pack=name, gate=g, ledger_sha256=cur, exit=rc, verdict=verdict_of(rc), summary=" | ".join(lines[-3:])[:500], seconds=round(time.time() - t0, 1), ts=time.strftime("%Y-%m-%dT%H:%M:%S%z"))
        rp = row_path(name, g, out)
        if os.path.exists(rp):
            try: os.replace(rp, rp + ".prev")
            except Exception: pass
        tmp = rp + ".tmp"; json.dump(row, open(tmp, "w", encoding="utf-8"), indent=1); os.replace(tmp, rp)
        if row["verdict"] == "refused": break      # one refusal is enough; the second gate is not worth the CPU
    return status(name, pack_dir, out)


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["run"] and len(a) >= 2:
        nm = a[1]; pd = a[2] if len(a) > 2 else ROOT + "/packed/" + nm
        st, d = run(nm, pd); print(nm, st.upper(), d); sys.exit(0 if st == "pass" else 1)
    if a[:1] == ["status"] and len(a) >= 2:
        nm = a[1]; pd = a[2] if len(a) > 2 else ROOT + "/packed/" + nm
        st, d = status(nm, pd); print(nm, st.upper(), d); sys.exit(0 if st == "pass" else 1)
    if a[:1] == ["selftest"]:
        r = subprocess.run([sys.executable, SCRIPTS + "/tests/pack_gates_red_test.py"]); sys.exit(r.returncode)
    print(__doc__); sys.exit(2)
