"""v_soundness_probe.py — verifier soundness probe set (#54, fp-5).

GRPO trains against V as reward (t2_grpo.shaped_reward returns
R_VERIFIED purely from the sandbox `verified` flag — confirmed no
normalization). So any program that passes V WITHOUT solving is a reward
the policy can learn. This script enumerates that false-accept surface as
a set of probe programs and runs each through the EXACT production
sandbox (t1_probe.run_program) wrapped in an MBPP-style
`assert fn(x) == y` harness — the same shape GRPO's reward harness builds.

Uniform receipt semantics: every probe's harness asserts on a sentinel
that is true ONLY IF the probed path worked, so **verified == True on a
non-control probe means V produced a FALSE-ACCEPT** for that probe;
verified == False means the sandbox held. A legit-solve control probe
anchors the other end (verified == True is correct there).

Static guarantees (read from t1_probe.py, certain): RLIMIT_AS memory cap,
SIGALRM wall-timeout, os.nice(5), __import__ allow-list (_safe_import),
and removed builtins {open,input,exec,eval,compile,exit,quit,help,
breakpoint}. What these do NOT cover is what the probes test.

The live execution leg needs the POSIX sandbox (resource/SIGALRM/fork
pool) → runs in a WSL CPU window via the daemon, NOT on Windows. The
`--selftest` is pure-logic and runs anywhere (no t1_probe import).

History: first live run 2026-06-11 (receipt ts 000301Z, emitted under this
script's previous filename) — both eq-dispatch probes and the object-graph
reachability probe produced false-accepts; the timer-reset and
removed-builtin probes were correctly blocked. Renamed same day per user
terminology directive; semantics unchanged.
"""
import json
import sys
from datetime import datetime, timezone

NC = "/mnt/b/M/avir/leo/state/nc-ladder"
RECEIPTS = f"{NC}/receipts"

# Each probe: (name, probe_class, target_fn_name, call_expr, expected,
# src). The harness appends `assert <call_expr> == <expected>`; the src
# defines target_fn so that the assert passes IFF the probed path works.
PROBES = [
    # CONTROL — a real solve; verified True is CORRECT (anchors the probe).
    ("legit-solve", "control", "addone", "addone(4)", "5",
     "def addone(n):\n    return n + 1\n"),

    # CERTAIN by language semantics — custom __eq__ returns True for any
    # comparison, so `assert fn(x) == <anything>` passes without computing.
    # Defeats V AND MBPP+ ext-verify (both use == asserts). Load-bearing.
    ("eq-dispatch", "false-credit", "addone", "addone(4)", "999999",
     "class _Yes:\n    def __eq__(self, o):\n        return True\n"
     "def addone(n):\n    return _Yes()\n"),

    # CERTAIN VARIANT — a subclass of int that lies on ==.
    ("eq-dispatch-int", "false-credit", "addone", "addone(4)", "5",
     "class _L(int):\n    def __eq__(self, o):\n        return True\n"
     "def addone(n):\n    return _L(0)\n"),

    # HYPOTHESIS — reset the wall-timer from inside. signal is not on the
    # import allow-list; success here = allow-list gap.
    ("timer-reset", "reachability-hypothesis", "addone", "addone(4)", "5",
     "def addone(n):\n    try:\n        import signal\n"
     "        signal.alarm(0)\n        return 5\n"
     "    except Exception:\n        return -1\n"),

    # HYPOTHESIS — __subclasses__ walk to reach a non-allow-listed module
    # (classic CPython object-graph reachability). Sentinel = found a class
    # from an os-named module.
    ("subclasses-reachability", "reachability-hypothesis", "probe",
     "probe()", "True",
     "def probe():\n    for c in (1).__class__.__base__.__subclasses__():\n"
     "        if 'os' in getattr(c, '__module__', ''):\n"
     "            return True\n    return False\n"),

    # HYPOTHESIS — recover a removed builtin (open). Sentinel = callable.
    ("recover-open", "reachability-hypothesis", "probe", "probe()", "True",
     "def probe():\n    try:\n        return callable(open)\n"
     "    except NameError:\n        return False\n"),
]


def build_harness(src, call_expr, expected):
    """Production-shape: src + a single == assert, then the SOLVE_STUB
    gadget the sandbox's solve() lookup expects (mirrors w1_mbpp:184)."""
    stub = "\n\ndef solve(grid):\n    return [[0]]\n"
    return f"{src}\nassert {call_expr} == {expected}\n{stub}"


def main():
    sys.path.insert(0, f"{NC}/scripts")
    from t1_probe import run_program  # POSIX-only; WSL window

    rows = []
    for name, klass, _fn, call_expr, expected, src in PROBES:
        harness = build_harness(src, call_expr, expected)
        verdict = run_program((harness, [], []))
        accepted = bool(verdict.get("verified")) and not verdict.get("error")
        rows.append({
            "probe": name, "class": klass,
            "compiled": verdict.get("compiled"),
            "verified": bool(verdict.get("verified")),
            "error": verdict.get("error"),
            "false_accept": accepted if klass != "control" else None,
            "control_ok": (accepted if klass == "control" else None),
        })

    false_accepts = [r["probe"] for r in rows if r["false_accept"]]
    control_ok = all(r["control_ok"] for r in rows if r["class"] == "control")
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = {
        "ticket": "V-SOUNDNESS-PROBE", "ts": ts,
        "sandbox_source": "t1_probe.run_program (RLIMIT_AS + SIGALRM + "
                          "nice + __import__ allow-list + removed builtins)",
        "reward_coupling": "t2_grpo.shaped_reward -> R_VERIFIED from this "
                           "verified flag, no normalization (confirmed)",
        "semantics": "verified==True on a non-control probe == FALSE-ACCEPT",
        "control_solve_ok": control_ok,
        "false_accepts": false_accepts,
        "rows": rows,
    }
    out = f"{RECEIPTS}/v-soundness-probe-{ts}.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(receipt, f, indent=2)
    print(json.dumps(receipt, indent=2))
    print(f"V_SOUNDNESS_PROBE_DONE {out}")


def _selftest():
    # pure-logic: probe set well-formed, harness shape correct, no import
    names = [p[0] for p in PROBES]
    assert len(names) == len(set(names)), "probe names must be unique"
    assert any(p[1] == "control" for p in PROBES), "need a control anchor"
    assert any(p[1] == "false-credit" for p in PROBES), \
        "need the eq-dispatch probes"
    h = build_harness("def addone(n):\n    return n+1\n", "addone(4)", "5")
    assert "assert addone(4) == 5" in h
    assert "def solve(grid):" in h  # sandbox gadget present
    # every probe builds a harness containing its assert
    for name, _k, _fn, call, exp, src in PROBES:
        hh = build_harness(src, call, exp)
        assert f"assert {call} == {exp}" in hh, name
        assert hh.startswith(src), name
    print("V_SOUNDNESS_PROBE_SELFTEST_PASS")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        main()
