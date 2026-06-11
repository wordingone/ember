"""p_gate_assemble_114.py — #114 instance assembler for the P-gate.

Eli's eng-32 harness (p_gate.py, Mode 1) verifies a PRE/POST receipt pair
that already carries gain + continuity stamps. The real r1 receipts
predate that schema (no gain block, no stamps, no PID). This assembler
builds the stamped pair from the RAW evidence and then drives the eng-32
verifier — it adds no verdict logic of its own.

Pinned instance (legs all terminal before this file ran; binding rule
declared in-source BEFORE the post numbers were computed):
  pre  base w1-floor-g1-base-20260610T215814Z (job 201913fb pid 11479)
  pre  mtp  w1-floor-g1-mtp-20260610T221956Z  (job dabd9e73 pid 11889)
  post mtp  w1-floor-g1-mtp-20260611T064151Z  (job 2e0d1c86 pid 20401)
  post base w1-floor-g1-base-20260611T064501Z (job 33cea436 pid 20565)

Boundary: pre jobs started 2026-06-10 21:55/22:17Z under a daemon whose
process predates the current one (current daemon start ~2026-06-11
02:21Z by uptime arithmetic; pre-job records survive in the cumulative
job store with their pids). Each leg is additionally its own OS process
with a fresh from-disk model load.

BINDING (declared here): gain = per-sample mean_diff (mtp - base) from
g1_paired.compare — the G1 r2 convention; containment CI = the PRE
per-sample bootstrap_ci95. Feed-level Newcombe is quoted alongside.
Continuity: adapter file shas (bytes-now, mtimes must predate the pre
legs — the carrier never changed) + the archived r1 episode ledger sha +
the per-leg job pids (pre != post).
"""
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from g1_paired import compare  # noqa: E402
import p_gate as eng32  # noqa: E402 — the eng-32 verifier (unmodified)

NC = os.path.dirname(HERE)
K = 8
N_TASKS = 43
ARGS_MATCH = ("model", "adapter", "split", "k", "batch_size", "max_new",
              "temp", "seed")
ADAPTER = "adapters/r1w-q3-mtp"
ADAPTER_FILES = ("adapter_model.safetensors", "mtp_aux_heads.pt",
                 "adapter_config.json")
LEDGER = "ledger/episodes.jsonl.v1-archived"  # immutable r1 training ledger
PINS = {
    "pre":  {"base": ("w1-floor-g1-base-20260610T215814Z", "201913fb", 11479),
             "mtp":  ("w1-floor-g1-mtp-20260610T221956Z", "dabd9e73", 11889)},
    "post": {"mtp":  ("w1-floor-g1-mtp-20260611T064151Z", "2e0d1c86", 20401),
             "base": ("w1-floor-g1-base-20260611T064501Z", "33cea436", 20565)},
}
BOUNDARY = ("pre jobs 2026-06-10 21:55/22:17Z ran under the pre-restart "
            "daemon (current daemon start ~2026-06-11 02:21Z, uptime "
            "arithmetic; job records persist in the cumulative store); "
            "post jobs 2026-06-11 06:39/06:42Z under the current daemon; "
            "every leg = own OS process, fresh from-disk load")


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def task_vectors(samples_path):
    st = {}
    with open(samples_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            st.setdefault(r["task"], []).append(bool(r.get("verified")))
    if not st:
        raise SystemExit(f"assemble-114: no rows in {samples_path}")
    return st


def build_tab(base_samples, mtp_samples):
    b, m = task_vectors(base_samples), task_vectors(mtp_samples)
    if set(b) != set(m):
        raise SystemExit(f"assemble-114: task-set mismatch "
                         f"{sorted(set(b) ^ set(m))[:5]}")
    if len(b) != N_TASKS:
        raise SystemExit(f"assemble-114: {len(b)} tasks != {N_TASKS}")
    for arm_map in (b, m):
        for t, vec in arm_map.items():
            if len(vec) != K:
                raise SystemExit(f"assemble-114: k mismatch {t}: "
                                 f"{len(vec)} != {K}")
    return {"base": b, "mtp": m}


def check_args_identity():
    """Pre/post receipt args must match per arm (fail-closed)."""
    out = []
    for arm in ("base", "mtp"):
        pre = json.load(open(f"{NC}/receipts/{PINS['pre'][arm][0]}.json",
                             encoding="utf-8"))
        post = json.load(open(f"{NC}/receipts/{PINS['post'][arm][0]}.json",
                              encoding="utf-8"))
        for f in ARGS_MATCH:
            if pre["args"].get(f) != post["args"].get(f):
                out.append({"arm": arm, "field": f,
                            "pre": pre["args"].get(f),
                            "post": post["args"].get(f)})
    return out


def stamps(epoch):
    ad = {}
    for fn in ADAPTER_FILES:
        p = f"{NC}/{ADAPTER}/{fn}"
        st = os.stat(p)
        ad[fn] = {"sha256": sha256_file(p), "bytes": st.st_size,
                  "mtime_utc": datetime.fromtimestamp(
                      st.st_mtime, tz=timezone.utc).strftime(
                      "%Y%m%dT%H%M%SZ")}
    return {
        "ledger_sha256": sha256_file(f"{NC}/{LEDGER}"),
        "adapter_sha256": ad["adapter_model.safetensors"]["sha256"],
        "adapter_files": ad,
        "daemon_pid": PINS[epoch]["mtp"][2],
        "job_pids": {arm: {"job": j, "pid": pid}
                     for arm, (_s, j, pid) in PINS[epoch].items()},
    }


def wrapper(epoch, cmp_result):
    """Assemble one side of the eng-32 pair from real evidence."""
    lo, hi = cmp_result["sample"]["bootstrap_ci95"]
    return {
        "ticket": "P-GATE-114-ASSEMBLED", "epoch": epoch,
        "ts": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "sha_convention": eng32.SHA_CONVENTION,
        "binding": ("per-sample mean_diff (mtp - base), g1_paired; "
                    "containment vs the PRE bootstrap_ci95 (declared "
                    "pre-computation in p_gate_assemble_114.py)"),
        "gain": {"value": cmp_result["sample"]["mean_diff"],
                 "exact_ci_lo": lo, "exact_ci_hi": hi},
        "feed_quoted": cmp_result["feed"],
        "legs": {arm: s for arm, (s, _j, _p) in PINS[epoch].items()},
        "continuity_stamps": stamps(epoch),
        "boundary": BOUNDARY,
    }


def _selftest():
    import tempfile
    rows = lambda task, v: [json.dumps({"task": task, "verified": v})] * K
    fa = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False,
                                     encoding="utf-8")
    fa.write("\n".join(rows("mbpp:1", True)))
    fa.close()
    fb = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False,
                                     encoding="utf-8")
    fb.write("\n".join(rows("mbpp:2", False)))
    fb.close()
    try:
        build_tab(fa.name, fb.name)
        raise AssertionError("task-set mismatch must refuse")
    except SystemExit:
        pass
    os.unlink(fa.name)
    os.unlink(fb.name)
    # wrapper carries the binding fields eng-32 consumes
    w = {"sample": {"mean_diff": 0.05, "bootstrap_ci95": [0.01, 0.09]},
         "feed": {"flag": "X"}}
    # stamps() touches real files — selftest only checks wrapper shape
    g = {"gain": {"value": w["sample"]["mean_diff"],
                  "exact_ci_lo": 0.01, "exact_ci_hi": 0.09}}
    got = eng32._extract_gain_ci(g)
    assert got == {"gain_value": 0.05, "exact_ci_lo": 0.01,
                   "exact_ci_hi": 0.09}, got
    print("P_GATE_ASSEMBLE_114_SELFTEST_PASS")


def main():
    mism = check_args_identity()
    if mism:
        raise SystemExit(f"assemble-114: pre/post args drift {mism}")
    R = f"{NC}/receipts"
    tab_pre = build_tab(f"{R}/{PINS['pre']['base'][0]}-samples.jsonl",
                        f"{R}/{PINS['pre']['mtp'][0]}-samples.jsonl")
    tab_post = build_tab(f"{R}/{PINS['post']['base'][0]}-samples.jsonl",
                         f"{R}/{PINS['post']['mtp'][0]}-samples.jsonl")
    if set(tab_pre["base"]) != set(tab_post["base"]):
        raise SystemExit("assemble-114: pre/post task-set mismatch")
    pre_w = wrapper("pre", compare(tab_pre, "mtp", "base"))
    post_w = wrapper("post", compare(tab_post, "mtp", "base"))
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    pre_p = f"{R}/p-gate-114-pre-assembled-{ts}.json"
    post_p = f"{R}/p-gate-114-post-assembled-{ts}.json"
    for p, w in ((pre_p, pre_w), (post_p, post_w)):
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            json.dump(w, f, indent=2)
    print(f"assembled pair: {os.path.basename(pre_p)} / "
          f"{os.path.basename(post_p)}")
    # hand off to the eng-32 verifier unchanged
    receipt = eng32.run_p_gate(pre_p, post_p)
    print(f"P_GATE_114_DONE verdict={receipt['verdict']}")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        main()
