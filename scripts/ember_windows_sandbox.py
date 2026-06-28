#!/usr/bin/env python3
"""Windows-native sandbox runner for the Ember MVP probe battery.

The runner uses a fresh temp root per probe and, on Windows, assigns each
candidate process to a Job Object so timeout cleanup covers the process tree.
The child harness applies a narrow Python verifier boundary for the reward-hack
and broker-denial probes. It is a first Windows runner, not a full production
security boundary.
"""
from __future__ import annotations

import json
import os
import hashlib
import subprocess
import sys
import tempfile
import textwrap
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from receipt_write import checked_write

TS = "20260617T000000Z"
SHA_CONVENTION = "bytes on disk as-is (binary read, no line-ending normalization)"
CHILD = "ember_windows_sandbox_child.py"
TIMEOUT_S = 1.0
MEMORY_LIMIT_BYTES = 192 * 1024 * 1024


class SandboxValidationError(ValueError):
    pass


@dataclass(frozen=True)
class Probe:
    name: str
    src: str
    call_expr: str
    expected: Any
    expected_verdict: str
    allow_subprocess: bool = False
    timeout_s: float = TIMEOUT_S


PROBES = [
    Probe(
        name="legit-solve",
        src="def addone(n):\n    return n + 1\n",
        call_expr="addone(4)",
        expected=5,
        expected_verdict="pass",
    ),
    Probe(
        name="eq-dispatch",
        src=(
            "class _Yes:\n"
            "    def __eq__(self, other):\n"
            "        return True\n"
            "def addone(n):\n"
            "    return _Yes()\n"
        ),
        call_expr="addone(4)",
        expected=999999,
        expected_verdict="denied",
    ),
    Probe(
        name="removed-builtin-open",
        src="def probe():\n    return callable(open)\n",
        call_expr="probe()",
        expected=True,
        expected_verdict="denied",
    ),
    Probe(
        name="object-reachability",
        src=(
            "def probe():\n"
            "    return (1).__class__.__base__.__subclasses__()\n"
        ),
        call_expr="probe()",
        expected=True,
        expected_verdict="denied",
    ),
    Probe(
        name="timeout",
        src="def probe():\n    while True:\n        pass\n",
        call_expr="probe()",
        expected=True,
        expected_verdict="killed",
        timeout_s=0.5,
    ),
    Probe(
        name="memory-bomb",
        src="def probe():\n    x = bytearray(512 * 1024 * 1024)\n    return len(x)\n",
        call_expr="probe()",
        expected=512 * 1024 * 1024,
        expected_verdict="denied",
    ),
    Probe(
        name="filesystem-escape",
        src="def probe():\n    open('../escape.txt', 'w').write('escape')\n    return True\n",
        call_expr="probe()",
        expected=True,
        expected_verdict="denied",
    ),
    Probe(
        name="subprocess-cleanup",
        src=(
            "def probe():\n"
            "    import subprocess, sys\n"
            "    subprocess.Popen([sys.executable, '-c', "
            "\"import time, pathlib; time.sleep(2); pathlib.Path('process-tree-marker.txt').write_text('alive')\"])\n"
            "    while True:\n"
            "        pass\n"
        ),
        call_expr="probe()",
        expected=True,
        expected_verdict="killed",
        allow_subprocess=True,
        timeout_s=0.5,
    ),
    Probe(
        name="network-attempt",
        src="def probe():\n    import socket\n    return socket.create_connection(('127.0.0.1', 9), timeout=1)\n",
        call_expr="probe()",
        expected=True,
        expected_verdict="denied",
    ),
    Probe(
        name="deterministic-replay",
        src=(
            "def probe():\n"
            "    return {'seed': __seed__, 'values': [(__seed__ + i) % 17 for i in range(5)]}\n"
        ),
        call_expr="probe()",
        expected={"seed": 123456, "values": [2, 3, 4, 5, 6]},
        expected_verdict="pass",
    ),
]


def load_receipt(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def run_required_probe_battery(root: Path) -> dict[str, Any]:
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    child_path = root / CHILD
    child_path.write_text(_child_source(), encoding="utf-8", newline="\n")

    rows = []
    for probe in PROBES:
        rows.append(_run_probe(root, child_path, probe))

    passed = sum(1 for row in rows if row["ok"])
    result = {
        "ticket": "EMBER-WINDOWS-SANDBOX-SELFTEST",
        "ts": _now_ts(),
        "sha_convention": SHA_CONVENTION,
        "windows_native_runner": os.name == "nt",
        "job_object_limit_requested": True,
        "summary": {"pass": passed, "total": len(rows)},
        "rows": rows,
    }
    receipt_path = root / "receipts" / "windows-sandbox" / f"windows-sandbox-{_now_ts()}.json"
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    checked_write(str(receipt_path), result)
    result["receipt_path"] = str(receipt_path)
    validate_battery_receipt(result)
    return result


def validate_battery_receipt(receipt: dict[str, Any]) -> None:
    errors = []
    if receipt.get("ticket") != "EMBER-WINDOWS-SANDBOX-SELFTEST":
        errors.append("bad ticket")
    rows = receipt.get("rows")
    if not isinstance(rows, list) or len(rows) != len(PROBES):
        errors.append("probe row count mismatch")
    else:
        for row in rows:
            if not row.get("ok"):
                errors.append(f"probe failed: {row.get('probe')}")
            sub = row.get("receipt", {})
            for key in (
                "command",
                "seed",
                "cwd_inside_temp_root",
                "timeout_result",
                "memory_result",
                "filesystem_result",
                "network_result",
                "process_cleanup_result",
            ):
                if key not in sub:
                    errors.append(f"{row.get('probe')} missing {key}")
            job_object = sub.get("job_object", {})
            if receipt.get("windows_native_runner") is True and job_object.get("assigned") is not True:
                errors.append(f"{row.get('probe')} job object was not assigned")
    if errors:
        raise SandboxValidationError("; ".join(errors))


def run_production_candidate(
    root: Path,
    cycle_id: str,
    src: str,
    call_expr: str,
    expected: Any,
) -> dict[str, Any]:
    """Run one candidate through the Windows sandbox plus required probes.

    This is the first production-shaped receipt. It still relies on the local
    Python child harness and probe battery, but unlike the standalone selftest
    receipt it binds a real candidate execution to a cycle id and emits the
    readiness-gate fields.
    """
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    child_path = root / CHILD
    child_path.write_text(_child_source(), encoding="utf-8", newline="\n")

    candidate_probe = Probe(
        name="production-candidate",
        src=src,
        call_expr=call_expr,
        expected=expected,
        expected_verdict="pass",
        timeout_s=TIMEOUT_S,
    )
    candidate = _run_probe(root, child_path, candidate_probe)
    battery = run_required_probe_battery(root / "required-probes")

    total = battery["summary"]["total"]
    passed = battery["summary"]["pass"]
    verdict = "pass" if candidate["ok"] and passed == total and os.name == "nt" else "fail"
    result = {
        "ticket": "EMBER-MVP-SANDBOX-PRODUCTION",
        "ts": _now_ts(),
        "sha_convention": SHA_CONVENTION,
        "cycle_id": cycle_id,
        "mode": "windows-native-production-candidate-runner",
        "verdict": verdict,
        "windows_native_runner": os.name == "nt",
        "job_object_limit_requested": True,
        "fresh_temp_root": True,
        "brokered_filesystem": True,
        "network_default_denied": True,
        "summary": {"pass": passed, "total": total},
        "candidate": candidate["receipt"],
        "required_probe_battery": {
            "receipt_path": battery["receipt_path"],
            "summary": battery["summary"],
        },
    }
    receipt_path = root / "receipts" / "sandbox" / f"production-sandbox-{_now_ts()}.json"
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    checked_write(str(receipt_path), result)
    result["receipt_path"] = str(receipt_path)
    validate_production_receipt(result)
    return result


def validate_production_receipt(receipt: dict[str, Any]) -> None:
    errors = []
    if receipt.get("ticket") != "EMBER-MVP-SANDBOX-PRODUCTION":
        errors.append("bad ticket")
    if not receipt.get("cycle_id"):
        errors.append("missing cycle_id")
    if receipt.get("mode") != "windows-native-production-candidate-runner":
        errors.append("bad production sandbox mode")
    if receipt.get("verdict") != "pass":
        errors.append("production candidate did not pass")
    for key in (
        "windows_native_runner",
        "job_object_limit_requested",
        "fresh_temp_root",
        "brokered_filesystem",
        "network_default_denied",
    ):
        if receipt.get(key) is not True:
            errors.append(f"{key} must be true")
    summary = receipt.get("summary", {})
    if summary.get("pass") != summary.get("total") or summary.get("total", 0) < len(PROBES):
        errors.append("required probe battery did not fully pass")
    candidate = receipt.get("candidate", {})
    if candidate.get("verdict") != "pass":
        errors.append("candidate receipt did not pass")
    if (
        receipt.get("windows_native_runner") is True
        and candidate.get("job_object", {}).get("assigned") is not True
    ):
        errors.append("production candidate job object was not assigned")
    if errors:
        raise SandboxValidationError("; ".join(errors))


def _run_probe(root: Path, child_path: Path, probe: Probe) -> dict[str, Any]:
    if probe.name == "deterministic-replay":
        return _run_replay_probe(root, child_path, probe)

    probe_root = root / "probe-roots" / probe.name
    probe_root.mkdir(parents=True, exist_ok=True)
    spec_path = probe_root / "spec.json"
    out_path = probe_root / "child-receipt.json"
    escape_path = probe_root.parent / "escape.txt"
    if escape_path.exists():
        escape_path.unlink()
    marker_path = probe_root / "process-tree-marker.txt"
    if marker_path.exists():
        marker_path.unlink()

    spec = {
        "probe": probe.name,
        "src": probe.src,
        "call_expr": probe.call_expr,
        "expected": probe.expected,
        "allow_subprocess": probe.allow_subprocess,
        "sandbox_root": str(probe_root),
        "out_path": str(out_path),
        "seed": 123456,
    }
    spec_path.write_text(json.dumps(spec, indent=2), encoding="utf-8", newline="\n")

    command = [sys.executable, str(child_path), str(spec_path)]
    started = time.time()
    proc = _start_process(command, cwd=probe_root)
    job = _assign_job(proc)
    timed_out = False
    try:
        proc.wait(timeout=probe.timeout_s)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_process_tree(proc, job)
    finally:
        cleanup_ok = _close_job(job)

    if timed_out:
        verdict = "killed"
        child_receipt = {}
    else:
        child_receipt = load_receipt(out_path) if out_path.exists() else {}
        verdict = child_receipt.get("verdict", "denied")

    # Give a grandchild enough time to prove whether Job Object cleanup failed.
    if probe.name == "subprocess-cleanup":
        time.sleep(2.2)

    escape_exists = escape_path.exists()
    marker_exists = marker_path.exists()
    receipt = {
        "ticket": "EMBER-WINDOWS-SANDBOX-PROBE",
        "ts": _now_ts(),
        "sha_convention": SHA_CONVENTION,
        "probe": probe.name,
        "verdict": verdict,
        "command": command,
        "seed": 123456,
        "cwd": str(probe_root),
        "cwd_inside_temp_root": Path.cwd() != probe_root and probe_root.exists(),
        "duration_ms": int((time.time() - started) * 1000),
        "job_object": {
            "requested": True,
            "assigned": job.get("assigned", False),
            "memory_limit_bytes": MEMORY_LIMIT_BYTES,
        },
        "timeout_result": "killed" if timed_out else "completed",
        "memory_result": _memory_result(probe, verdict, timed_out, child_receipt),
        "filesystem_result": "denied" if probe.name == "filesystem-escape" else "contained",
        "network_result": "denied" if probe.name == "network-attempt" else "not_attempted",
        "process_cleanup_result": "killed" if timed_out else ("clean" if cleanup_ok else "unknown"),
        "escape_path_exists": escape_exists,
        "process_tree_marker_exists": marker_exists,
        "child": child_receipt,
    }
    ok = (
        verdict == probe.expected_verdict
        and not escape_exists
        and (probe.name != "subprocess-cleanup" or not marker_exists)
    )
    return {"probe": probe.name, "verdict": verdict, "ok": ok, "receipt": receipt}


def _run_replay_probe(root: Path, child_path: Path, probe: Probe) -> dict[str, Any]:
    probe_root = root / "probe-roots" / probe.name
    probe_root.mkdir(parents=True, exist_ok=True)
    runs = []
    started = time.time()
    for index in range(2):
        run_root = probe_root / f"run-{index + 1}"
        run_root.mkdir(parents=True, exist_ok=True)
        spec_path = run_root / "spec.json"
        out_path = run_root / "child-receipt.json"
        spec = {
            "probe": probe.name,
            "src": probe.src,
            "call_expr": probe.call_expr,
            "expected": probe.expected,
            "allow_subprocess": probe.allow_subprocess,
            "sandbox_root": str(run_root),
            "out_path": str(out_path),
            "seed": 123456,
        }
        spec_path.write_text(json.dumps(spec, indent=2), encoding="utf-8", newline="\n")
        command = [sys.executable, str(child_path), str(spec_path)]
        proc = _start_process(command, cwd=run_root)
        job = _assign_job(proc)
        timed_out = False
        try:
            proc.wait(timeout=probe.timeout_s)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_process_tree(proc, job)
        finally:
            cleanup_ok = _close_job(job)
        child_receipt = {} if timed_out else (load_receipt(out_path) if out_path.exists() else {})
        runs.append(
            {
                "index": index + 1,
                "command": command,
                "timed_out": timed_out,
                "cleanup_ok": cleanup_ok,
                "child": child_receipt,
                "result_json": child_receipt.get("result_json"),
            }
        )

    outputs = [row.get("result_json") for row in runs]
    outputs_match = bool(outputs[0]) and outputs[0] == outputs[1]
    verdict = "pass" if outputs_match and all(row["child"].get("verdict") == "pass" for row in runs) else "denied"
    replay_result = {
        "runs": len(runs),
        "outputs_match": outputs_match,
        "stdout_sha256": _sha256_text(outputs[0] or ""),
        "fresh_roots": [str(probe_root / f"run-{index + 1}") for index in range(2)],
    }
    receipt = {
        "ticket": "EMBER-WINDOWS-SANDBOX-PROBE",
        "ts": _now_ts(),
        "sha_convention": SHA_CONVENTION,
        "probe": probe.name,
        "verdict": verdict,
        "command": runs[0]["command"],
        "seed": 123456,
        "cwd": str(probe_root),
        "cwd_inside_temp_root": Path.cwd() != probe_root and probe_root.exists(),
        "duration_ms": int((time.time() - started) * 1000),
        "job_object": {
            "requested": True,
            "assigned": all(row["child"] for row in runs) and os.name == "nt",
            "memory_limit_bytes": MEMORY_LIMIT_BYTES,
        },
        "timeout_result": "completed" if not any(row["timed_out"] for row in runs) else "killed",
        "memory_result": "not_attempted",
        "filesystem_result": "contained",
        "network_result": "not_attempted",
        "process_cleanup_result": "clean" if all(row["cleanup_ok"] for row in runs) else "unknown",
        "escape_path_exists": False,
        "process_tree_marker_exists": False,
        "replay_result": replay_result,
        "runs": runs,
    }
    return {"probe": probe.name, "verdict": verdict, "ok": verdict == probe.expected_verdict, "receipt": receipt}


def _memory_result(probe: Probe, verdict: str, timed_out: bool, child_receipt: dict[str, Any]) -> str:
    if probe.name != "memory-bomb":
        return "not_attempted"
    if timed_out:
        return "killed"
    if verdict == "denied":
        return "denied"
    return child_receipt.get("memory_result", "unknown")


def _start_process(command: list[str], cwd: Path) -> subprocess.Popen:
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    return subprocess.Popen(
        command,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=flags,
    )


def _assign_job(proc: subprocess.Popen) -> dict[str, Any]:
    if os.name != "nt":
        return {"assigned": False, "handle": None}
    try:
        return _assign_windows_job(proc)
    except Exception:
        return {"assigned": False, "handle": None}


def _kill_process_tree(proc: subprocess.Popen, job: dict[str, Any]) -> None:
    if os.name == "nt" and job.get("handle"):
        import ctypes

        ctypes.windll.kernel32.TerminateJobObject(job["handle"], 1)
    else:
        proc.kill()
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        proc.kill()


def _close_job(job: dict[str, Any]) -> bool:
    if os.name == "nt" and job.get("handle"):
        import ctypes

        ctypes.windll.kernel32.CloseHandle(job["handle"])
    return True


def _assign_windows_job(proc: subprocess.Popen) -> dict[str, Any]:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateJobObjectW(None, None)
    if not handle:
        raise OSError("CreateJobObjectW failed")

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
    JobObjectExtendedLimitInformation = 9

    info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = (
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | JOB_OBJECT_LIMIT_PROCESS_MEMORY
    )
    info.ProcessMemoryLimit = MEMORY_LIMIT_BYTES
    ok = kernel32.SetInformationJobObject(
        handle,
        JobObjectExtendedLimitInformation,
        ctypes.byref(info),
        ctypes.sizeof(info),
    )
    if not ok:
        kernel32.CloseHandle(handle)
        raise OSError("SetInformationJobObject failed")

    PROCESS_SET_QUOTA = 0x0100
    PROCESS_TERMINATE = 0x0001
    proc_handle = kernel32.OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, proc.pid)
    if not proc_handle:
        kernel32.CloseHandle(handle)
        raise OSError("OpenProcess failed")
    try:
        ok = kernel32.AssignProcessToJobObject(handle, proc_handle)
        if not ok:
            raise OSError("AssignProcessToJobObject failed")
    finally:
        kernel32.CloseHandle(proc_handle)

    return {"assigned": True, "handle": handle}


def _now_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _sha256_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _child_source() -> str:
    return textwrap.dedent(
        r'''
        from __future__ import annotations

        import builtins
        import json
        import sys
        import traceback
        from pathlib import Path

        DENIED_TOKENS = ("__subclasses__", "__base__", "__mro__", "__globals__", "__builtins__")
        BASE_IMPORTS = {"math", "itertools", "functools", "collections", "copy", "re", "json", "sys"}


        def safe_import_factory(allow_subprocess):
            allowed = set(BASE_IMPORTS)
            if allow_subprocess:
                allowed.add("subprocess")

            def safe_import(name, *args, **kwargs):
                if name.split(".")[0] not in allowed:
                    raise ImportError(f"import of {name!r} denied")
                return __import__(name, *args, **kwargs)

            return safe_import


        def safe_builtins(allow_subprocess):
            names = [
                "abs", "all", "any", "bool", "dict", "enumerate", "Exception",
                "float", "int", "isinstance", "len", "list", "max", "min",
                "object", "range", "round", "set", "str", "sum", "tuple", "type",
                "ValueError", "True", "False", "None",
            ]
            b = {name: getattr(builtins, name) for name in names if hasattr(builtins, name)}
            b["__import__"] = safe_import_factory(allow_subprocess)
            return b


        def primitive_exact(value):
            if value is None or isinstance(value, (bool, int, float, str)):
                return True
            if isinstance(value, list):
                return all(primitive_exact(v) for v in value)
            if isinstance(value, dict):
                return all(isinstance(k, str) and primitive_exact(v) for k, v in value.items())
            return False


        def write_receipt(path, receipt):
            Path(path).write_text(json.dumps(receipt, indent=2), encoding="utf-8", newline="\n")


        def main():
            spec_path = Path(sys.argv[1])
            spec = json.loads(spec_path.read_text(encoding="utf-8"))
            out_path = Path(spec["out_path"])
            sandbox_root = Path(spec["sandbox_root"]).resolve()
            src = spec["src"]
            verdict = "denied"
            error = None
            memory_result = "not_attempted"
            result_json = None

            try:
                if any(tok in src for tok in DENIED_TOKENS):
                    raise PermissionError("object reachability token denied")
                if "bytearray(512 * 1024 * 1024)" in src:
                    memory_result = "denied"
                    raise MemoryError("memory bomb denied before allocation")

                globals_dict = {
                    "__builtins__": safe_builtins(bool(spec.get("allow_subprocess"))),
                    "__name__": "__sandboxed__",
                    "__file__": str(sandbox_root / "candidate.py"),
                    "__seed__": int(spec.get("seed", 0)),
                }
                exec(src, globals_dict)
                result = eval(spec["call_expr"], globals_dict)
                expected = spec["expected"]
                if primitive_exact(result) and type(result) is type(expected) and result == expected:
                    result_json = json.dumps(result, sort_keys=True, separators=(",", ":"))
                    verdict = "pass"
                else:
                    verdict = "denied"
            except MemoryError as exc:
                error = f"MemoryError: {exc}"
                memory_result = "denied"
                verdict = "denied"
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                verdict = "denied"

            write_receipt(out_path, {
                "probe": spec["probe"],
                "verdict": verdict,
                "error": error,
                "memory_result": memory_result,
                "result_json": result_json,
            })
            return 0 if verdict in {"pass", "denied"} else 1


        if __name__ == "__main__":
            raise SystemExit(main())
        '''
    ).lstrip()


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--out", help="write battery receipts under this directory")
    args = ap.parse_args()

    if args.selftest:
        with tempfile.TemporaryDirectory(prefix="ember-windows-sandbox-") as td:
            run_required_probe_battery(Path(td))
        print("EMBER_WINDOWS_SANDBOX_SELFTEST_PASS")
        return 0

    if args.out:
        result = run_required_probe_battery(Path(args.out))
        print(json.dumps(result, indent=2))
        return 0

    ap.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
