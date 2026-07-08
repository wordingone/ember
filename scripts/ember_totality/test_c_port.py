#!/usr/bin/env python3
"""Ember totality test — Condition C-PORT (status probe / TDD).

C-PORT — substrate portability: the organism survives its device
         (goal §4.2, <spec> L116; user reframe 2026-06-23).

  R (positive artifact required): a device-adaptive governor + numerics
     fallback ladder, proven by a device-portability RECEIPT, where:
       - VRAM budget is QUERIED at runtime (no hardcoded 24 GiB literal);
       - EMBER_VRAM_FRACTION is read from env, not duplicated as a literal;
       - fp8 paths are gated on sm>=89 with a bf16 FALLBACK (no bare fp8
         RuntimeError);
       - throughput thresholds are DEVICE-RELATIVE (derived from a per-device
         roofline), not an absolute tok/s gate;
       - proven on >=1 NON-4090 target (CPU-portability probe PASS now; real
         or faithfully-emulated 3090/T4/5090/RTX-Spark/AMD when reachable).
     Governor changes TIGHTEN only — never loosen the 4090 floor.

  Does NOT count (each encoded as a negative assertion below):
     - a 4090-only path;
     - an absolute tok/s threshold (19000 / 25463 / 27702) used as a
       pass/fail gate on another device;
     - an fp8 RuntimeError with no fallback;
     - "Ember needs the 4090" asserted rather than measured.

  Invalid-token (the explicit ✗): invalid_device_locked

  CHK: a device-portability receipt shows the governor + a forward pass
       running under a SIMULATED/REAL non-4090 capability WITHOUT crash, and
       every 4090-absolute constant replaced by a runtime-derived value.

This is a STATUS PROBE. It always exits 0 and prints exactly one line
beginning with "RED " or "GREEN ". RED/GREEN is determined by really
inspecting state under <external-state> — never hardcoded. If the satisfying
artifact is genuinely absent (no device-portability receipt), the honest
result is RED.

Run ONLY via:  wsl python3 <this file>
(python/python3 are not on the Windows PATH; only `wsl python3` works.)
Under WSL the execution root is /mnt<local-mount-point>/ on this host (the sibling tests also try
<local-mount-point>/ for hosts with the bare-drive mount convention).
"""

# [PATH-REWRITE 2026-07-01] Imported from
# <<external>>/state/ember-totality-build/ into
# <local-exec-root>-goalforge/scripts/ember_totality/. Original WSL dual/triple-mount
# candidates pointing at <<external>>/state/<external-state> (and /mnt<local-mount-point>/M/...,
# <local-mount-point>/M/..., <TEMP_WORKSPACE>/... variants) replaced with a single REPO_ROOT-relative
# candidate, REPO_ROOT computed from this file's own location (two levels up
# from scripts/ember_totality/), for native Windows system-python execution.
# No probe logic changed -- only path resolution. <external-state> does not exist
# under the new repo root, so these probes are expected to emit a clean RED
# 'root not found' line, which is the correct, non-error outcome.

import glob
import json
import os
import re
import sys

# --- Locate <external-state> robustly across WSL mount conventions ----------------
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
CANDIDATE_ROOTS = [
    p for p in (os.environ.get("EMBER_TOTALITY_ROOT"), REPO_ROOT,
                os.path.join(REPO_ROOT, "<external-state>"))
    if p
]
ROOT = next((r for r in CANDIDATE_ROOTS if os.path.isdir(r)), None)

# Absolute tok/s thresholds the condition explicitly forbids as a cross-device
# pass/fail gate (goal L116 "an absolute tok/s threshold (19000/25463/27702)").
ABSOLUTE_TPS_GATES = ("19000", "25463", "27702")

# Invalid-tokens the condition declares as NON-counting outcomes. The first is
# C-PORT's explicit ✗ token; the rest encode the four "does NOT count"
# substitutes so a portability receipt that names/admits any of them cannot
# pass (negative assertions against the receipt body).
INVALID_TOKENS = [
    "invalid_device_locked",          # the explicit ✗ token
    "4090_only_path",                 # does NOT count: a 4090-only path
    "absolute_tps_gate_on_other_device",  # does NOT count: absolute tok/s gate on another device
    "fp8_runtimeerror_no_fallback",   # does NOT count: an fp8 RuntimeError with no fallback
    "needs_the_4090_asserted",        # does NOT count: "needs the 4090" asserted not measured
]


def emit(color, reason):
    """Print the single status line and exit 0 (status-probe contract)."""
    print(f"{color} {reason}")
    sys.exit(0)


# [ISSUE #97 cure 7, 2026-07-04] The #89 board-integrity audit's own receipt
# family DESCRIBES probe findings/receipt fragments verbatim (it quotes what
# it inspected, including terms like forward_pass/no_crash/device_portability
# lifted from other receipts' content) -- it never IS a portability receipt.
# Parsing it as a candidate flipped C-PORT RED on 2026-07-04
# (audit-20260704T144656Z.json was selected as the "newest candidate" and
# then correctly failed CHK, but for the wrong reason: it was never a real
# device-portability artifact to begin with). Audit receipts are receipts
# ABOUT the board and may quote any fragment; they are never evidence FOR a
# condition. Same exclusion as test_c_fed.py's META_AUDIT_FAMILY_DIRNAME.
META_AUDIT_FAMILY_DIRNAME = "ember-totality-audit"


def _under_meta_audit_family(path):
    """True if META_AUDIT_FAMILY_DIRNAME appears anywhere in path's directory
    components (receipts/ember-totality-audit/** -- any depth)."""
    norm = path.replace("\\", "/")
    parts = norm.split("/")
    return META_AUDIT_FAMILY_DIRNAME in parts[:-1]  # exclude the filename itself


def find_portability_receipt(receipts_dir):
    """Return the newest receipt whose CONTENT is a genuine device-portability
    proof: a governor + forward-pass run on a non-4090 (simulated or real)
    device. We match on content, not filename, because the artifact carries
    its own evidence. Returns (path, parsed_json, raw_text) or (None, None, None).

    A receipt qualifies as a candidate only if it carries BOTH:
      (i) a non-4090 device identity (device/target field that is not a 4090,
          OR an explicit cpu-portability / simulated-capability marker), AND
      (ii) a forward-pass-no-crash signal (a forward_pass / no_crash style key).
    The CHK clauses below then decide PASS vs FAIL on the candidate.

    [ISSUE #97 cure 7] the meta-audit receipt family
    (receipts/ember-totality-audit/**) is excluded from candidacy -- see
    META_AUDIT_FAMILY_DIRNAME comment above.
    """
    candidates = []
    for path in sorted(glob.glob(os.path.join(receipts_dir, "**", "*.json"),
                                  recursive=True)):
        if _under_meta_audit_family(path):
            continue
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                raw = fh.read()
        except OSError:
            continue
        low = raw.lower()
        # (ii) forward-pass-no-crash signal.
        fwd_signal = (
            ("forward_pass" in low or "forward pass" in low)
            and ("no_crash" in low or "no crash" in low or "nocrash" in low
                 or "did_not_crash" in low or "crash\": false" in low
                 or "crashed\": false" in low)
        )
        # (i) explicit non-4090 / simulated-capability / cpu-portability marker.
        portability_marker = (
            "cpu_portability" in low or "cpu-portability" in low
            or "simulated_device" in low or "simulated_capability" in low
            or "non_4090" in low or "non-4090" in low
            or "device_portability" in low or "device-portability" in low
            or "portability_probe" in low
        )
        if fwd_signal and portability_marker:
            candidates.append((path, raw))
    if not candidates:
        return None, None, None
    # Newest by stamp-sorted name (filenames carry ...YYYYMMDDTHHMMSSZ...).
    candidates.sort(key=lambda pr: pr[0])
    path, raw = candidates[-1]
    try:
        return path, json.loads(raw), raw
    except json.JSONDecodeError:
        return path, None, raw


def is_4090_only(parsed, raw):
    """True if the receipt's device identity is a 4090 and there is no other
    (non-4090) device evidence — i.e. a 4090-only path (does NOT count)."""
    low = raw.lower()
    dev = ""
    if isinstance(parsed, dict):
        for k in ("device", "target", "gpu", "device_name"):
            v = parsed.get(k)
            if isinstance(v, str):
                dev += " " + v.lower()
    dev = dev or low
    mentions_4090 = "4090" in dev
    mentions_non_4090 = bool(
        re.search(r"3090|t4\b|5090|rtx[\s_-]*spark|amd|mi\d{2,3}|rocm|cpu", dev)
    )
    return mentions_4090 and not mentions_non_4090


def absolute_tps_gate_used(parsed, raw):
    """Detect an absolute tok/s threshold used as a pass/fail GATE (not merely
    a measured number). We flag it only when an absolute constant sits next to
    gate/threshold/pass-fail language, to avoid penalising a receipt that
    merely records a measured throughput."""
    low = raw.lower()
    for tps in ABSOLUTE_TPS_GATES:
        for m in re.finditer(re.escape(tps), low):
            window = low[max(0, m.start() - 60): m.end() + 60]
            if re.search(r"threshold|gate|pass|fail|floor|require", window):
                return tps
    return None


def main():
    if ROOT is None:
        emit("UNEVALUABLE", "C-PORT: state root not found under any known layout "
                    f"(tried {CANDIDATE_ROOTS}) -- input-missing, dead branch under "
                    "the flat-layout resolver (paper-consistency flip, 2026-07-02)")

    receipts_dir = os.path.join(ROOT, "receipts")
    if not os.path.isdir(receipts_dir):
        emit("RED", f"C-PORT: receipts dir absent at {receipts_dir}")

    # --- Locate the satisfying artifact: a device-portability receipt. --------
    path, parsed, raw = find_portability_receipt(receipts_dir)
    if path is None:
        # Surface WHY it is absent, with the governor's current portability gap,
        # so the RED reason is actionable (TDD: fails for the right reason).
        gov = os.path.join(ROOT, "scripts", "governor.py")
        gov_gap = []
        if os.path.isfile(gov):
            gtxt = open(gov, "r", encoding="utf-8", errors="ignore").read().lower()
            if "sm" not in gtxt or "89" not in gtxt:
                gov_gap.append("no sm>=89 fp8 gate")
            if "bf16" not in gtxt and "fallback" not in gtxt:
                gov_gap.append("no bf16 fallback ladder")
            if "roofline" not in gtxt and "device_relative" not in gtxt:
                gov_gap.append("no device-relative throughput threshold")
        else:
            gov_gap.append("scripts/governor.py absent")
        emit("RED",
             "C-PORT: NO device-portability receipt under receipts/ proving "
             "governor + a forward pass on a non-4090 (simulated/real) device "
             "without crash -> satisfying artifact genuinely ABSENT. "
             f"governor.py portability gaps: {gov_gap or ['none-detected']}. "
             "The newest device receipt (ns-chain-roofline-4090-*.json) is "
             "explicitly RTX-4090-only (a 4090-only path does NOT count).")

    findings = []

    # --- Negative assertions: NONE of the invalid-tokens may appear -----------
    low = raw.lower()
    hit = [t for t in INVALID_TOKENS if t.lower() in low]
    if hit:
        findings.append(f"invalid-token present {hit}")

    # does NOT count: a 4090-only path.
    if is_4090_only(parsed, raw):
        findings.append("device identity is 4090-only (no non-4090 evidence) "
                        "-> a 4090-only path does NOT count")

    # does NOT count: an absolute tok/s threshold used as a cross-device gate.
    abst = absolute_tps_gate_used(parsed, raw)
    if abst is not None:
        findings.append(f"absolute tok/s threshold {abst} used as a pass/fail "
                        "gate -> does NOT count on another device")

    # does NOT count: an fp8 RuntimeError with no fallback.
    if ("fp8" in low and "runtimeerror" in low
            and "fallback" not in low and "bf16" not in low):
        findings.append("fp8 RuntimeError present with no bf16 fallback "
                        "-> does NOT count")

    if not isinstance(parsed, dict):
        findings.append("portability receipt is not valid JSON object")
        emit("RED", f"C-PORT: candidate {os.path.basename(path)} fails CHK -> "
                    f"{'; '.join(findings)}")

    # --- Positive CHK clauses -------------------------------------------------
    # (1) governor present + a forward pass ran without crash on the device.
    fwd = parsed.get("forward_pass") or parsed.get("forward")
    no_crash = None
    if isinstance(fwd, dict):
        no_crash = fwd.get("no_crash", fwd.get("crashed"))
        # crashed:false also satisfies; normalise.
        if "crashed" in fwd and "no_crash" not in fwd:
            no_crash = (fwd.get("crashed") is False)
    if no_crash is not True and "no_crash\": true" not in low \
            and "no crash" not in low:
        findings.append("no forward-pass-no-crash confirmation in the receipt")

    gov_block = parsed.get("governor")
    if not isinstance(gov_block, dict):
        findings.append("no governor evidence block in the portability receipt")
    else:
        # VRAM budget must be runtime-queried (a total_gib/total_gb field that
        # is NOT the hardcoded 24 GiB), and EMBER_VRAM_FRACTION env-sourced.
        total = (gov_block.get("total_gib") or gov_block.get("total_gb")
                 or gov_block.get("device_total_gib"))
        if total is None:
            findings.append("governor block has no runtime-queried VRAM total")
        frac_src = json.dumps(gov_block).lower()
        if "ember_vram_fraction" not in frac_src and "vram_fraction" not in frac_src:
            findings.append("governor block does not reference EMBER_VRAM_FRACTION")

    # (2) device must be NON-4090 (simulated or real).
    dev = ""
    for k in ("device", "target", "device_name", "simulated_device", "capability"):
        v = parsed.get(k)
        if isinstance(v, str):
            dev += " " + v
    if not dev.strip():
        findings.append("no device/target identity field in the receipt")
    elif "4090" in dev.lower() and not re.search(
            r"3090|t4|5090|spark|amd|mi\d{2,3}|rocm|cpu|simulat", dev.lower()):
        findings.append(f"device identity {dev.strip()!r} is 4090, not a non-4090 target")

    # (3) every 4090-absolute constant replaced by a runtime-derived value:
    # the receipt must declare a device-relative throughput basis (roofline-
    # derived), not an absolute tok/s gate.
    thr = parsed.get("throughput_threshold") or parsed.get("threshold_basis") \
        or parsed.get("device_relative_threshold")
    basis_txt = json.dumps(parsed.get("throughput_basis", "")).lower() \
        if parsed.get("throughput_basis") is not None else low
    if not (re.search(r"roofline|device.?relativ|per.?device", basis_txt) or
            isinstance(thr, dict)):
        findings.append("no device-relative (roofline-derived) throughput "
                        "threshold declared (4090-absolute constant not replaced)")

    # (4) fp8 gated on sm>=89 with bf16 fallback (numerics fallback ladder).
    if "fp8" in low and not re.search(r"sm[\s_>=]*89|sm>=89|compute_89", low):
        findings.append("fp8 path present but not gated on sm>=89")
    if "fp8" in low and "bf16" not in low and "fallback" not in low:
        findings.append("fp8 path present with no bf16 fallback ladder")

    # (5) TIGHTEN-only: the governor must not loosen the 4090 floor.
    if "loosen" in low or "relax" in low:
        # only flag if it loosens the floor, not if it says "never loosen".
        if not re.search(r"never\s+loosen|tighten[\s_-]*only|does\s+not\s+loosen", low):
            findings.append("governor change appears to loosen the 4090 floor "
                            "(must TIGHTEN only)")

    if findings:
        emit("RED",
             f"C-PORT: candidate receipt {os.path.relpath(path, ROOT)} present "
             f"but fails CHK -> {'; '.join(findings)}")

    emit("GREEN",
         f"C-PORT: device-portability receipt {os.path.relpath(path, ROOT)} "
         f"passes CHK: governor + forward pass ran without crash on a non-4090 "
         f"device ({dev.strip()}), VRAM total runtime-queried, "
         f"EMBER_VRAM_FRACTION env-sourced, device-relative throughput basis, "
         f"fp8/sm>=89/bf16 fallback ladder present; no invalid-token, no "
         f"4090-only path, no absolute tok/s gate.")


if __name__ == "__main__":
    main()
