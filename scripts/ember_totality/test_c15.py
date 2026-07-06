#!/usr/bin/env python3
"""test_c15.py — STATUS PROBE for Ember goal condition C15.

C15 (from <<external>>/state/<spec>, §4.2):
  "Immediate tiny BitNet comparison after the fp16 neural gate."
  R: first valid action after C14's fp16 gate is a REAL tiny BitNet/1.58 neural
     comparison (same harness/verifier/frozen slices/seeds/budget; record both
     model identities, trainable param counts, precision scheme, pre/post param
     hashes, training command, quality delta, footprint, throughput/latency,
     memory, transfer, deletion/revert).
  Does NOT count: quantized naming without a neural comparison; benchmark/
     readiness/D3 continuation first; silent skip or demotion to docs (missing
     support -> BITNET_BLOCKED naming the exact surface + next command).
  Invalid-token: BITNET_BLOCKED (as the ONLY allowed non-pass).
  CHK: comparison receipt present with both identities and pre/post hashes,
     OR a BITNET_BLOCKED receipt naming the surface.

This probe ALSO enforces the C15 dependency on C14 (the fp16 *neural* gate):
the BitNet comparison only counts if the resident gate it rides was a REAL
neural update, never a SYMBOLIC_PROXY_PASS (§2 receipted reality + the C14
does-NOT-count token). A PASS BitNet receipt sitting on a symbolic-proxy gate
would be a smuggled C15 clear, so the probe re-derives the gate's neural-ness
from the gate receipt's own fields.

DISCIPLINE: this is a STATUS PROBE. It ALWAYS exits 0. It prints exactly one
line determined by really inspecting the receipts under the resolved root.
Nothing is hardcoded to a verdict; every branch is decided by reading real
bytes on disk. C15 is a STANDING PROCESS-INVARIANT (GOAL.md §4.0(9)), not a
STATE-condition: it never prints RED/GREEN. It renders one of AUDIT-OK /
AUDIT-INCIDENT (a cadence audit from the goalforge-clear epoch) or, pre-epoch
(no operator-acceptance object exists yet), AUDIT-PENDING-EPOCH — never RED.
Pre-epoch history is explicitly OUT OF AUDIT SCOPE (§4.0(9)): this probe only
ever considers receipts dated at/after the epoch once one exists.

Run ONLY via:  wsl python3 test_c15.py
(python/python3 are not on the Windows PATH; the B: drive is <local-mount-point>/ under this WSL.)
"""

# [PATH-REWRITE 2026-07-01] Imported from
# <<external>>/state/ember-totality-build/ into
# <local-exec-root>-goalforge/scripts/ember_totality/. Original WSL dual/triple-mount
# candidates pointing at <<external>>/state/<external-state> (and /mnt<local-mount-point>/M/...,
# <local-mount-point>/M/..., B:\\M\\... variants) replaced with a single REPO_ROOT-relative
# candidate, REPO_ROOT computed from this file's own location (two levels up
# from scripts/ember_totality/), for native Windows system-python execution.
# No probe logic changed -- only path resolution. <external-state> does not exist
# under the new repo root, so these probes are expected to emit a clean RED
# 'root not found' line, which is the correct, non-error outcome.
from __future__ import annotations

import glob
import hashlib
import json
import os
import re
from typing import Any

# ---------------------------------------------------------------------------
# Roots. The probe runs under WSL where the B: drive is mounted at <local-mount-point>/.
# Fall back to a couple of alternates so the probe is portable, but the
# canonical location is the <external-state> checkout.
# ---------------------------------------------------------------------------
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
_ROOT_CANDIDATES = [
    p for p in (os.environ.get("EMBER_TOTALITY_ROOT"), REPO_ROOT,
                os.path.join(REPO_ROOT, "<external-state>"))
    if p
]


def _resolve_root() -> str | None:
    for c in _ROOT_CANDIDATES:
        if os.path.isdir(c):
            return c
    return None


_TS_RE = re.compile(r"(\d{8}T\d{6}Z)")


def _norm_ts(ts: str) -> str:
    """Normalize an ISO8601-ish timestamp to the compact YYYYMMDDTHHMMSSZ
    form used by this codebase's receipt filenames."""
    return re.sub(r"[^0-9A-Za-z]", "", ts or "")


def _find_epoch(root: str) -> tuple[str | None, str | None]:
    """Return (epoch_ts, epoch_path) for the goalforge-clear operator-
    acceptance object (docs/spec/operator-acceptance-v1.md schema
    acceptance/v1, scope goalforge-clear, stored at
    receipts/acceptance/goalforge-clear-<date>.json), or (None, None) if no
    epoch has been recorded yet. GOAL.md §4.0(9): the epoch is the operator
    acceptance of this goal; C15 is a process-invariant with no meaning
    before it exists."""
    acc_dir = os.path.join(root, "receipts", "acceptance")
    if not os.path.isdir(acc_dir):
        return None, None
    candidates = sorted(glob.glob(os.path.join(acc_dir, "goalforge-clear-*.json")))
    for path in reversed(candidates):
        try:
            obj = _load_json(path)
        except Exception:
            continue
        if obj.get("schema") == "acceptance/v1" and obj.get("scope") == "goalforge-clear":
            ts = obj.get("ts")
            if ts:
                return _norm_ts(ts), path
    return None, None


def _receipt_ts(path: str, obj: Any) -> str | None:
    """Best-effort receipt timestamp for epoch filtering: prefer a
    YYYYMMDDTHHMMSSZ stamp embedded anywhere in the path (directory or
    filename), fall back to the receipt's own internal 'ts' field."""
    m = _TS_RE.search(path)
    if m:
        return m.group(1)
    if isinstance(obj, dict):
        ts = obj.get("ts")
        if isinstance(ts, str) and ts:
            return _norm_ts(ts)
    return None


# C15 does-NOT-count invalid-tokens, encoded as the set this probe scans for.
# BITNET_BLOCKED is the ONLY allowed non-pass verdict, so it is NOT treated as a
# disqualifier when it appears as the receipt's own verdict with a named surface;
# it is only a disqualifier if it leaks into a receipt that otherwise claims PASS.
# The cross-cutting C14 token SYMBOLIC_PROXY_PASS invalidates the underlying gate.
C15_DOES_NOT_COUNT_TOKENS = [
    "SYMBOLIC_PROXY_PASS",          # C14 gate was symbolic, not neural -> C15 rides nothing real
    "quantized_naming_only",        # naming without a neural comparison
    "benchmark_readiness_d3_first", # D3/readiness continuation taken before the comparison
    "silent_skip",                  # comparison skipped / demoted to docs without BITNET_BLOCKED
    "demotion_to_docs",
]


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def _load_json(path: str) -> Any:
    # tolerate UTF-8 BOM (receipts are written by Windows python)
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def _find_deep(obj: Any, key: str) -> list[Any]:
    """Return all values stored under *key* anywhere in a nested dict/list."""
    out: list[Any] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key:
                out.append(v)
            out.extend(_find_deep(v, key))
    elif isinstance(obj, list):
        for v in obj:
            out.extend(_find_deep(v, key))
    return out


def scan(root: str, min_ts: "str | None") -> tuple[str, str]:
    """Run the C15 detection logic over receipts in the given window and
    return (status, reason) with status in {'RED','GREEN'} -- a raw finding,
    not the final printed status. min_ts=None means unfiltered (whole-corpus,
    informational -- used pre-epoch); min_ts=<stamp> means filtered to
    receipts dated >= min_ts (the real post-epoch audit)."""
    window = f">= {min_ts}" if min_ts is not None else "ALL (unfiltered, pre-epoch)"

    # ---- locate every tiny-bitnet comparison receipt actually on disk,
    # filtered to the window --------------------------------------------
    pattern = os.path.join(
        root, "receipts", "ember-tiny-bitnet-comparison", "**",
        "tiny_bitnet_comparison_receipt.json",
    )
    all_receipt_paths = sorted(glob.glob(pattern, recursive=True))
    if min_ts is None:
        receipt_paths = list(all_receipt_paths)
    else:
        receipt_paths = []
        for p in all_receipt_paths:
            try:
                probe_obj = _load_json(p)
            except Exception:
                probe_obj = None
            stamp = _receipt_ts(p, probe_obj)
            if stamp is not None and stamp >= min_ts:
                receipt_paths.append(p)
    if not receipt_paths:
        return "GREEN", (
            f"no tiny_bitnet_comparison_receipt.json under "
            f"{root}/receipts/ember-tiny-bitnet-comparison/ in window "
            f"{window} ({len(all_receipt_paths)} total on disk) -> "
            "vacuously no BitNet-comparison incident in the audited window"
        )

    # Pick the newest receipt by mtime; that is the live cursor.
    receipt_paths.sort(key=lambda p: os.path.getmtime(p), reverse=True)

    # We accept the FIRST receipt (newest-first) that cleanly PASSes the full
    # positive CHK with a real neural C14 gate -> AUDIT-OK. A well-formed
    # BITNET_BLOCKED naming the surface is PROCESS-COMPLIANT (honestly
    # disclosed, not silently skipped) -> AUDIT-OK, tracked separately from
    # genuine incidents (malformed BLOCKED, an unrecognized verdict, or a
    # PASS-labeled receipt that fails its own CHK -- a false-claim pattern).
    # We report on the newest one inspected.
    incidents: list[str] = []
    benign_blocks: list[str] = []
    for rpath in receipt_paths:
        rel = os.path.relpath(rpath, root)
        try:
            r = _load_json(rpath)
        except Exception as exc:  # broken receipt -> keep looking, record reason
            incidents.append(f"receipt {rel} is unreadable JSON: {exc}")
            continue

        verdict = r.get("verdict")

        # ---- allowed non-pass: BITNET_BLOCKED naming a surface --------------
        if verdict == "BITNET_BLOCKED":
            mis = r.get("missing_implementation_surface")
            nec = r.get("next_executable_command")
            if isinstance(mis, str) and mis.strip() and isinstance(nec, str) and nec.strip():
                # Legitimately-blocked, honestly disclosed -> process
                # discipline held even though the comparison itself has not
                # landed yet.
                benign_blocks.append(
                    f"{rel}: BITNET_BLOCKED naming surface '{mis.strip()}' "
                    f"(next: {nec.strip()}) — honest block, no incident"
                )
                continue
            incidents.append(
                f"{rel}: BITNET_BLOCKED but missing surface/next-command "
                "fields -> incomplete disclosure"
            )
            continue

        if verdict != "BITNET_COMPARISON_PASS":
            incidents.append(
                f"{rel}: verdict {verdict!r} is neither BITNET_COMPARISON_PASS "
                "nor BITNET_BLOCKED -> unrecognized status on a C15 artifact"
            )
            continue

        # ===================================================================
        # POSITIVE CHK branch: verdict == BITNET_COMPARISON_PASS
        # Every assertion below is read from the real receipt bytes.
        # ===================================================================
        problems: list[str] = []

        # (1) both model identities present and non-empty
        fp16_id = r.get("fp16_baseline_identity")
        bit_id = r.get("bitnet_model_identity")
        if not (isinstance(fp16_id, str) and fp16_id.strip()):
            problems.append("fp16_baseline_identity missing/empty")
        if not (isinstance(bit_id, str) and bit_id.strip()):
            problems.append("bitnet_model_identity missing/empty")

        # (2) pre/post hashes present AND pre != post for BOTH arms (a real
        #     parameter update changes the hash; equal hashes = no update).
        fp16_pre = r.get("fp16_pre_parameter_hash")
        fp16_post = r.get("fp16_post_parameter_hash")
        bit_pre = r.get("bitnet_pre_parameter_hash")
        bit_post = r.get("bitnet_post_parameter_hash")
        for name, v in (
            ("fp16_pre", fp16_pre), ("fp16_post", fp16_post),
            ("bitnet_pre", bit_pre), ("bitnet_post", bit_post),
        ):
            if not (isinstance(v, str) and v.strip()):
                problems.append(f"{name}_parameter_hash missing/empty")
        if isinstance(fp16_pre, str) and fp16_pre == fp16_post:
            problems.append("fp16 pre == post hash (no parameter update)")
        if isinstance(bit_pre, str) and bit_pre == bit_post:
            problems.append("bitnet pre == post hash (no STE update)")

        # (3) trainable param counts positive ints
        for k in ("fp16_trainable_parameter_count", "bitnet_trainable_parameter_count"):
            c = r.get(k)
            if not (isinstance(c, int) and c > 0):
                problems.append(f"{k} is {c!r}, expected positive int")

        # (4) precision/quantization scheme records the ternary BitNet arm
        scheme = r.get("precision_quantization_scheme")
        if not isinstance(scheme, dict) or "bitnet" not in scheme:
            problems.append("precision_quantization_scheme missing bitnet entry")

        # (5) footprint records 1.58-bit effective weights
        fp = r.get("footprint")
        if not (isinstance(fp, dict) and fp.get("bitnet_effective_weight_bits") == 1.58):
            problems.append("footprint.bitnet_effective_weight_bits != 1.58")

        # (6) quality_delta, throughput_latency, memory, transfer, deletion present
        if not isinstance(r.get("quality_delta"), dict):
            problems.append("quality_delta missing")
        if not isinstance(r.get("throughput_latency"), dict):
            problems.append("throughput_latency missing")
        if not isinstance(r.get("memory_cpu_measurements"), dict):
            problems.append("memory_cpu_measurements missing")
        tr = r.get("transfer_rows")
        if not (isinstance(tr, list) and tr):
            problems.append("transfer_rows missing/empty")
        dr = r.get("deletion_revert_evidence")
        if not (isinstance(dr, list) and dr):
            problems.append("deletion_revert_evidence missing/empty")

        # (7) training command recorded
        if not (isinstance(r.get("verifier_conditioned_training_command"), str)
                and r["verifier_conditioned_training_command"].strip()):
            problems.append("verifier_conditioned_training_command missing/empty")

        # -------------------------------------------------------------------
        # NEGATIVE assertions: NONE of the C15 does-NOT-count invalid-tokens
        # may appear in the receipt text. A PASS receipt must not carry the
        # C14 SYMBOLIC_PROXY_PASS token, nor any silent-skip/demotion marker.
        # -------------------------------------------------------------------
        receipt_text = json.dumps(r)
        matched_tokens = [t for t in C15_DOES_NOT_COUNT_TOKENS if t in receipt_text]
        # A PASS receipt that names BITNET_BLOCKED as a fallback (it shouldn't)
        # would also be a contradiction:
        if "BITNET_BLOCKED" in receipt_text:
            matched_tokens.append("BITNET_BLOCKED-leaked-into-PASS-receipt")
        if matched_tokens:
            problems.append("invalid-token(s) present in PASS receipt: " + ",".join(matched_tokens))

        # -------------------------------------------------------------------
        # C14 DEPENDENCY: the comparison must ride a REAL neural fp16 gate.
        # Re-derive the gate's neural-ness from the gate receipt's own bytes;
        # never trust the bitnet receipt's prose status alone.
        # -------------------------------------------------------------------
        gate_status = r.get("resident_gate_receipt_status")
        if gate_status != "PASS":
            problems.append(f"resident_gate_receipt_status is {gate_status!r}, expected PASS")
        gate_rel = r.get("resident_gate_receipt_path")
        gate_sha_recorded = r.get("resident_gate_receipt_sha256")
        gate_abs = None
        if isinstance(gate_rel, str) and gate_rel.strip():
            # the receipt records a windows-style relative path; normalise it
            cand = gate_rel.replace("\\", "/")
            cand = os.path.join(root, cand) if not os.path.isabs(cand) else cand
            if os.path.isfile(cand):
                gate_abs = cand
            else:
                # fall back: search the repo for the basename
                base = os.path.basename(cand)
                hits = glob.glob(os.path.join(root, "receipts", "**", base), recursive=True)
                gate_abs = hits[0] if hits else None
        if gate_abs is None:
            problems.append(f"referenced C14 resident gate receipt not found on disk ({gate_rel!r})")
        else:
            # sha integrity: the recorded gate sha must match the real bytes
            real_sha = _sha256_file(gate_abs)
            recorded = (gate_sha_recorded or "")
            if not recorded.startswith("sha256:"):
                recorded = "sha256:" + recorded if recorded else recorded
            if recorded and real_sha != recorded:
                problems.append(
                    f"C14 gate sha mismatch: recorded {recorded} != actual {real_sha}"
                )
            # neural-vs-symbolic: inspect the gate receipt's own fields
            try:
                g = _load_json(gate_abs)
            except Exception as exc:
                problems.append(f"C14 gate receipt unreadable: {exc}")
                g = None
            if g is not None:
                gate_text = json.dumps(g)
                if "SYMBOLIC_PROXY_PASS" in gate_text:
                    problems.append("C14 gate receipt contains SYMBOLIC_PROXY_PASS (not a real neural gate)")
                # symbolic_substitution_check.status must be NEURAL_UPDATE_PRESENT
                statuses = _find_deep(g, "status")
                if "NEURAL_UPDATE_PRESENT" not in statuses:
                    problems.append("C14 gate missing NEURAL_UPDATE_PRESENT status")
                # symbolic_template_policy must be explicitly False somewhere
                stp = _find_deep(g, "symbolic_template_policy")
                if not stp or any(v is not False for v in stp):
                    problems.append("C14 gate symbolic_template_policy not False")
                # gate must show a real parameter update (distinct neural hashes)
                pre = _find_deep(g, "pre_neural_parameter_hash")
                post = _find_deep(g, "post_neural_parameter_hash")
                if not pre or not post or not pre[0] or not post[0]:
                    problems.append("C14 gate missing pre/post neural parameter hashes")
                elif pre[0] == post[0]:
                    problems.append("C14 gate pre == post neural hash (no neural update)")
                # gate top-level status / verdict must be a PASS
                if g.get("resident_training_gate_status") != "PASS":
                    problems.append("C14 gate resident_training_gate_status != PASS")

        if problems:
            # PASS-labeled but fails its own CHK: a false-claim pattern, a
            # genuine process-invariant incident.
            incidents.append(f"{rel}: PASS receipt fails CHK -> " + "; ".join(problems))
            continue

        # Everything held: a real BITNET_COMPARISON_PASS on a real neural C14 gate.
        return "GREEN", (
            f"{rel}: BITNET_COMPARISON_PASS with both identities "
            f"({fp16_id} | {bit_id}), distinct fp16 & bitnet pre/post hashes, "
            f"1.58-bit footprint, transfer+deletion rows, riding C14 neural gate "
            f"{os.path.relpath(gate_abs, root)} (sha verified, NEURAL_UPDATE_PRESENT, "
            f"no invalid-token)"
        )

    # No receipt reached a clean PASS. A genuine incident (malformed BLOCKED,
    # unrecognized verdict, or a false PASS claim) outranks a benign block --
    # either state means at least one receipt in the window violated process
    # discipline. Only if EVERY receipt in the window was a well-formed,
    # honestly-disclosed BITNET_BLOCKED is the window clean (GREEN).
    if incidents:
        return "RED", incidents[-1] + (
            f" ({len(incidents)} incident(s), {len(benign_blocks)} benign "
            "block(s) also seen)" if len(incidents) > 1 or benign_blocks else ""
        )
    if benign_blocks:
        return "GREEN", benign_blocks[-1] + (
            f" ({len(benign_blocks)} honest block(s), no incidents)"
            if len(benign_blocks) > 1 else ""
        )
    # Unreachable in practice (receipt_paths was non-empty, so every receipt
    # fell into incidents or benign_blocks above) -- fail safe to RED rather
    # than silently claiming clean on an unclassified state.
    return "RED", "no receipt in window was classified (unreachable state)"


def main() -> int:
    """Resolve the epoch, run scan() in the appropriate window, and relabel
    the raw RED/GREEN finding against the AUDIT-OK/AUDIT-INCIDENT/
    AUDIT-PENDING-EPOCH contract (GOAL.md §4.0(9)) before printing."""
    root = _resolve_root()
    if root is None:
        print("AUDIT-PENDING-EPOCH state root not found under any of "
              f"{_ROOT_CANDIDATES}; cannot even locate receipts/acceptance to "
              "check for an epoch")
        return 0

    epoch_ts, epoch_path = _find_epoch(root)
    raw_status, raw_reason = scan(root, epoch_ts)

    if epoch_ts is None:
        print(
            f"AUDIT-PENDING-EPOCH {raw_reason} "
            f"[PRE-EPOCH INFORMATIONAL finding={raw_status} -- no "
            "goalforge-clear operator-acceptance object exists yet at "
            "receipts/acceptance/goalforge-clear-*.json (schema "
            "acceptance/v1); this is NOT an audit verdict, pre-epoch "
            "history is OUT OF AUDIT SCOPE per GOAL.md §4.0(9), the actual "
            "status is never RED/GREEN for this row]"
        )
        return 0

    final_status = "AUDIT-OK" if raw_status == "GREEN" else "AUDIT-INCIDENT"
    print(f"{final_status} {raw_reason}")
    return 0  # STATUS PROBE: always exit 0


if __name__ == "__main__":
    raise SystemExit(main())
