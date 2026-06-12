#!/usr/bin/env python3
"""sp-3 terminal-audit row 8 — round-harness loop-path locality manifest (#212).

Exercises the heartbeat_runner loop-path in config-only (dry_run=True) mode
and emits a locality manifest derived from t2_round.py source bytes (eng-53
pattern: every read/write path and offline-enforcement line audited from bytes,
never from declared flags or runtime self-report).

AC:
1. heartbeat_runner selftest exits 0 (loop path traversable, chain complete).
2. Locality manifest: per-leg endpoint list from t2_round.py source bytes.
3. zero_cloud_assert: HF offline enforcement confirmed from source bytes;
   no unguarded network-eligible call survives the scan.
4. Receipt emitted: ticket=ROUND-LOCAL-LOOP, sha_convention present.

CLI:
  --run     required to execute (staged guard)
  --write   write receipt to receipts/round-local-loop-<ts>.json
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from nck.replay_rig import REPO_ROOT

T2_ROUND_PATH = _SCRIPTS_DIR / "t2_round.py"
HEARTBEAT_PATH = _SCRIPTS_DIR / "heartbeat_runner.py"

_STAGED_MSG = (
    "STAGED: round_local_loop loaded but not triggered. "
    "Pass --run to exercise the loop path and emit a locality manifest. "
    "Pass --write to record the receipt. "
    "Exit-1 is the evidence-promotion gate."
)

_LEG_NAMES = ("sample_round", "ingest_samples", "build_dataset", "train_lora")


# ---------------------------------------------------------------------------
# Source-byte audit helpers (eng-53 pattern)
# ---------------------------------------------------------------------------


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _check_no_crlf(path: Path) -> list[int]:
    """Return list of 1-based line numbers containing CRLF. Empty = clean."""
    crlf_lines: list[int] = []
    with open(path, "rb") as f:
        for i, line in enumerate(f, 1):
            if b"\r\n" in line:
                crlf_lines.append(i)
    return crlf_lines


def _extract_leg_body(src_lines: list[str], leg_name: str) -> list[str]:
    """Extract lines of a top-level function body by exact name."""
    in_func = False
    body: list[str] = []
    for line in src_lines:
        if re.match(rf"^def {re.escape(leg_name)}\b", line):
            in_func = True
            body.append(line)
            continue
        if in_func:
            # Non-blank, non-comment, non-indented line = next top-level item
            if line and not line[0].isspace() and not line.startswith("#"):
                break
            body.append(line)
    return body


def _audit_t2_source(path: Path) -> dict:
    """Derive locality facts from t2_round.py source bytes (eng-53 pattern).

    Produces:
    - hf_hub_offline_lines: where HF_HUB_OFFLINE is set via setdefault
    - transformers_offline_lines: where TRANSFORMERS_OFFLINE is set via setdefault
    - local_files_only_lines: where local_files_only=True appears
    - nc_path_lines: NC + per-leg constant path assignments
    - network_calls_found: unguarded network-eligible calls (requests/urllib/
      snapshot_download without local_files_only on same line)
    - leg_endpoints: per-leg path-reference lines (read/write endpoints)
    - offline_enforced: bool — all three offline guards present in source
    - zero_cloud: bool — offline_enforced AND zero unguarded network calls
    """
    src_lines = path.read_text(encoding="utf-8").splitlines()

    hf_hub_offline: list[dict] = []
    transformers_offline: list[dict] = []
    local_files_only: list[dict] = []
    nc_path_lines: list[dict] = []
    network_calls: list[dict] = []

    for i, line in enumerate(src_lines, 1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue

        # Offline enforcement guards
        if "HF_HUB_OFFLINE" in line and "setdefault" in line:
            hf_hub_offline.append({"line": i, "text": stripped})
        if "TRANSFORMERS_OFFLINE" in line and "setdefault" in line:
            transformers_offline.append({"line": i, "text": stripped})
        if "local_files_only" in line and "True" in line:
            local_files_only.append({"line": i, "text": stripped})

        # NC path constants (module-level)
        if re.match(r"^(NC|LEDGER|CONTROL_POOL|ADAPTERS|RECEIPTS)\s*=", line):
            nc_path_lines.append({"line": i, "text": stripped})

        # Unguarded network-eligible calls
        if re.search(r"\brequests\.(get|post|put|patch|delete|head)\b", line):
            network_calls.append({"line": i, "text": stripped, "type": "requests_call"})
        if re.search(r"\burllib\.request\b", line):
            network_calls.append({"line": i, "text": stripped, "type": "urllib_request"})
        # snapshot_download call (not import) without local_files_only on same line
        if ("snapshot_download" in line and "local_files_only" not in line
                and not stripped.startswith("from ") and not stripped.startswith("import ")):
            network_calls.append({"line": i, "text": stripped,
                                  "type": "snapshot_download_unguarded"})

    # Per-leg endpoint extraction: path-like references inside each leg function
    leg_endpoints: dict[str, list[str]] = {}
    _PATH_KEYWORDS = frozenset((
        "NC", "LEDGER", "CONTROL_POOL", "ADAPTERS", "RECEIPTS",
        "ARC_TRAIN", "open(", "os.path", "samples_path",
        "ledger_path", "out_dir", "model_path", "/mnt/",
    ))
    for leg in _LEG_NAMES:
        body = _extract_leg_body(src_lines, leg)
        endpoints: list[str] = []
        for bline in body:
            bstrip = bline.strip()
            if not bstrip or bstrip.startswith("#"):
                continue
            if any(kw in bstrip for kw in _PATH_KEYWORDS):
                endpoints.append(bstrip[:120])
        leg_endpoints[leg] = endpoints[:10]

    offline_enforced = (
        len(hf_hub_offline) > 0
        and len(transformers_offline) > 0
        and len(local_files_only) > 0
    )
    zero_cloud = offline_enforced and len(network_calls) == 0

    return {
        "hf_hub_offline_lines": hf_hub_offline,
        "transformers_offline_lines": transformers_offline,
        "local_files_only_lines": local_files_only,
        "nc_path_lines": nc_path_lines,
        "network_calls_found": network_calls,
        "leg_endpoints": leg_endpoints,
        "offline_enforced": offline_enforced,
        "zero_cloud": zero_cloud,
    }


# ---------------------------------------------------------------------------
# Heartbeat loop-path selftest
# ---------------------------------------------------------------------------


def _run_heartbeat_selftest() -> dict:
    """Run heartbeat_runner.py selftest. Returns result dict."""
    t0 = time.time()
    r = subprocess.run(
        [sys.executable, str(HEARTBEAT_PATH), "selftest"],
        capture_output=True, text=True,
        cwd=str(_SCRIPTS_DIR),
    )
    elapsed = round(time.time() - t0, 2)

    # Extract the JSON receipt from stdout (last JSON object in output)
    receipt_json: dict | None = None
    for line in reversed(r.stdout.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                receipt_json = json.loads(line)
                break
            except json.JSONDecodeError:
                continue

    return {
        "exit_code": r.returncode,
        "stdout_tail": r.stdout.strip()[-600:] if r.stdout else "",
        "stderr_tail": r.stderr.strip()[-300:] if r.stderr else "",
        "elapsed_s": elapsed,
        "pass": r.returncode == 0,
        "receipt": receipt_json,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_commit_sha() -> str:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, cwd=str(REPO_ROOT),
        )
        return r.stdout.strip()
    except Exception:
        return "unknown"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    args = sys.argv[1:]
    if "--run" not in args:
        print(_STAGED_MSG)
        return 1

    write = "--write" in args

    if not T2_ROUND_PATH.exists():
        print(f"ROUND_LOCAL_LOOP_NO_SOURCE: t2_round.py not found at {T2_ROUND_PATH}")
        return 1
    if not HEARTBEAT_PATH.exists():
        print(f"ROUND_LOCAL_LOOP_NO_RUNNER: heartbeat_runner.py not found at {HEARTBEAT_PATH}")
        return 1

    # Drift-guard: t2_round.py must be LF-only (*.py text eol=lf in .gitattributes)
    crlf_lines = _check_no_crlf(T2_ROUND_PATH)
    if crlf_lines:
        print(f"CRLF_DRIFT_DETECTED: t2_round.py has CRLF on {len(crlf_lines)} line(s): "
              f"{crlf_lines[:5]}{'...' if len(crlf_lines) > 5 else ''}")
        print("  Fix: git checkout -- scripts/t2_round.py (or normalize CRLF→LF)")
        return 1

    # AC2+3: source-byte audit (eng-53 pattern — facts from bytes, not flags)
    print("Auditing t2_round.py source bytes (eng-53 pattern)...")
    t2_sha = _sha256_file(T2_ROUND_PATH)
    heartbeat_sha = _sha256_file(HEARTBEAT_PATH)
    audit = _audit_t2_source(T2_ROUND_PATH)

    print(f"  t2_round.py sha256:       {t2_sha[:24]}...")
    print(f"  HF_HUB_OFFLINE lines:     {[e['line'] for e in audit['hf_hub_offline_lines']]}")
    print(f"  TRANSFORMERS_OFFLINE:     {[e['line'] for e in audit['transformers_offline_lines']]}")
    print(f"  local_files_only lines:   {[e['line'] for e in audit['local_files_only_lines']]}")
    print(f"  NC path constants:        {[e['line'] for e in audit['nc_path_lines'][:5]]}")
    print(f"  network_calls (unguarded):{len(audit['network_calls_found'])}")
    print(f"  offline_enforced:         {audit['offline_enforced']}")
    print(f"  zero_cloud:               {audit['zero_cloud']}")

    if not audit["zero_cloud"]:
        print("ZERO_CLOUD_ASSERT_FAIL")
        if not audit["offline_enforced"]:
            print("  offline enforcement missing from source")
        for nc in audit["network_calls_found"]:
            print(f"  line {nc['line']} [{nc['type']}]: {nc['text'][:80]}")
        return 1

    print("zero_cloud PASS\n")

    # AC1: heartbeat_runner selftest (loop path IDLE→DISPATCH→…→NEXT)
    print("Running heartbeat_runner selftest (loop path)...")
    selftest = _run_heartbeat_selftest()
    if selftest["stdout_tail"]:
        for line in selftest["stdout_tail"].splitlines()[-15:]:
            print(f"  {line}")
    print(f"  exit_code={selftest['exit_code']}, elapsed={selftest['elapsed_s']}s")

    if not selftest["pass"]:
        print(f"HEARTBEAT_SELFTEST_FAIL: exit_code={selftest['exit_code']}")
        if selftest["stderr_tail"]:
            print(selftest["stderr_tail"][:300])
        return 1

    print("Selftest PASS")

    commit_sha = _get_commit_sha()
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    receipt = {
        "ticket": "ROUND-LOCAL-LOOP",
        "label": "LOOP-PATH-LOCALITY-MANIFEST",
        "ts": ts,
        "commit_sha": commit_sha,
        "sources": {
            "t2_round_py": {
                "path": str(T2_ROUND_PATH),
                "sha256": t2_sha,
            },
            "heartbeat_runner_py": {
                "path": str(HEARTBEAT_PATH),
                "sha256": heartbeat_sha,
            },
        },
        "locality_manifest": {
            "hf_hub_offline_lines": audit["hf_hub_offline_lines"],
            "transformers_offline_lines": audit["transformers_offline_lines"],
            "local_files_only_lines": audit["local_files_only_lines"],
            "nc_path_lines": audit["nc_path_lines"],
            "network_calls_found": audit["network_calls_found"],
            "leg_endpoints": audit["leg_endpoints"],
        },
        "zero_cloud_assert": {
            "offline_enforced": audit["offline_enforced"],
            "network_calls_found_count": len(audit["network_calls_found"]),
            "zero_cloud": audit["zero_cloud"],
            "derivation": (
                "source-bytes scan (eng-53 pattern) — "
                "not a self-reported flag or runtime check"
            ),
        },
        "selftest": {
            "exit_code": selftest["exit_code"],
            "elapsed_s": selftest["elapsed_s"],
            "pass": selftest["pass"],
            "receipt": selftest["receipt"],
        },
        "flags": [
            "config-only dry_run=True — loop path exercised, no GPU dispatch",
            "locality manifest derived from source bytes (eng-53 pattern)",
            "sp-3 terminal-audit row 8 of 9 — loop-path locality",
            "round-1 semantics NOT claimed (fp-23 floor chain not yet satisfied)",
            "live run 12c050e7 NOT touched",
        ],
        "live_run_untouched": "12c050e7",
        "sha_convention": (
            "sha256 over on-disk raw bytes (binary read, no line-ending normalization)"
        ),
    }

    if write:
        receipt_dir = REPO_ROOT / "receipts"
        receipt_dir.mkdir(exist_ok=True)
        fname = receipt_dir / f"round-local-loop-{ts}.json"
        fname.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        print(f"\nRECEIPT: {fname}")
    else:
        print("\n(dry-run: pass --write to save receipt)")
        print(json.dumps({
            "zero_cloud": audit["zero_cloud"],
            "offline_enforced": audit["offline_enforced"],
            "network_calls_found_count": len(audit["network_calls_found"]),
            "selftest_pass": selftest["pass"],
            "t2_sha256": t2_sha[:24] + "...",
        }, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())
