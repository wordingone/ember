import argparse
import hashlib
import json
import os
import pathlib
import re
import shutil
import secrets
import subprocess
import sys
import time
from typing import Mapping, Sequence

# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember


GIB = 1024 ** 3
OPERATING_RESERVES_GIB = {"C": 150.0, "B": 250.0}
FINAL_RECEIPT_RESERVATION_BYTES = 64 * 1024

def _receipt_sha256(receipt: Mapping[str, object]) -> str:
    payload = dict(receipt)
    payload.pop("receipt_sha256", None)
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()

_CHILD_ENV_BOOTSTRAP = """
import json
import os
import pathlib
import sys
import subprocess

bindings = json.loads(sys.argv[1])
assertion_path = pathlib.Path(sys.argv[2])
nonce = sys.argv[3]
custody = pathlib.Path(bindings["TEMP"]).parent.resolve()
actual = {name: os.environ.get(name) for name in bindings}
if actual != bindings or any(not pathlib.Path(value).resolve().is_relative_to(custody) for value in actual.values()):
    raise SystemExit("disk-budget child cache binding mismatch")
assertion_path.write_text(json.dumps({"schema_version": 1, "nonce": nonce, "bindings": actual}, sort_keys=True) + chr(10), encoding="utf-8")
raise SystemExit(subprocess.run(sys.argv[4:], env=os.environ, check=False).returncode)
"""

def current_free_gib() -> dict[str, float]:
    return {
        drive: shutil.disk_usage(f"{drive}:\\").free / GIB
        for drive in OPERATING_RESERVES_GIB
    }


def _validate_budgets(max_write_gib: Mapping[str, float]) -> dict[str, float]:
    if set(max_write_gib) != set(OPERATING_RESERVES_GIB):
        raise ValueError("write budgets must name exactly C and B")
    budgets = {drive: float(max_write_gib[drive]) for drive in OPERATING_RESERVES_GIB}
    if any(value < 0 for value in budgets.values()):
        raise ValueError("write budgets cannot be negative")
    if not any(value > 0 for value in budgets.values()):
        raise ValueError("at least one write budget must be positive")
    return budgets


def assess_capacity(
    free_gib: Mapping[str, float],
    floors_gib: Mapping[str, float],
    max_write_gib: Mapping[str, float],
) -> list[str]:
    """Reject launches whose declared writes could consume an operating reserve."""

    budgets = _validate_budgets(max_write_gib)
    return [
        (
            f"{drive}: {free_gib.get(drive, 0.0):.2f} GiB free minus "
            f"{budgets[drive]:.2f} GiB declared writes would not remain above "
            f"the {floor:.2f} GiB operating reserve"
        )
        for drive, floor in floors_gib.items()
        if free_gib.get(drive, 0.0) - budgets[drive] <= floor
    ]


def _root_identity(path: pathlib.Path) -> str:
    stat = path.stat()
    return f"{stat.st_dev}:{stat.st_ino}"


def _canonical_write_root(label: str, raw_path: pathlib.Path) -> pathlib.Path:
    path = pathlib.Path(raw_path).resolve(strict=True)
    if not path.is_dir():
        raise ValueError(f"write root is not a directory: {label}")
    system_drive = pathlib.Path(os.environ.get("SystemDrive", "C:"))
    local_app_data = os.environ.get("LOCALAPPDATA")
    broad_roots = {system_drive / "tmp"}
    if local_app_data:
        broad_roots.add(pathlib.Path(local_app_data))
    broad_roots = {candidate.resolve() for candidate in broad_roots}
    if path == pathlib.Path(path.anchor) or path in broad_roots or len(path.parts) < 3:
        raise ValueError(f"write root must be a bounded explicit directory: {label}")
    return path


def _snapshot_write_roots(
    write_roots: Mapping[str, pathlib.Path],
    *,
    expected: Mapping[str, Mapping[str, object]] | None = None,
) -> dict[str, dict[str, object]]:
    """Scan bounded named roots; nested entries are charged to the deepest root.

    File disappearance is evidence of scan uncertainty, not a reason to lose the
    receipt. A missing or substituted root remains a fail-closed binding error.
    """

    if not write_roots:
        raise ValueError("at least one named write root is required")
    if expected is not None and set(expected) != set(write_roots):
        raise ValueError("write root binding changed")

    resolved: dict[str, pathlib.Path] = {}
    identities: dict[str, str] = {}
    for label, raw_path in write_roots.items():
        if not isinstance(label, str) or not re.fullmatch(r"[a-z][a-z0-9_-]*", label):
            raise ValueError("write roots require lowercase unique names")
        path = _canonical_write_root(label, pathlib.Path(raw_path))
        if path in resolved.values():
            raise ValueError(f"write roots cannot bind the same directory: {label}")
        drive = path.drive.rstrip(":").upper()
        if drive not in OPERATING_RESERVES_GIB:
            raise ValueError(f"write root must be on C or B: {label}")
        identity = _root_identity(path)
        if expected is not None and (
            expected[label]["canonical_path"] != str(path)
            or expected[label]["identity"] != identity
        ):
            raise ValueError(f"write root binding changed: {label}")
        resolved[label] = path
        identities[label] = identity

    ordered = sorted(resolved, key=lambda item: len(resolved[item].parts), reverse=True)
    bytes_by_root = {label: 0 for label in resolved}
    files_by_root = {label: 0 for label in resolved}
    errors_by_root: dict[str, list[str]] = {label: [] for label in resolved}
    started = time.monotonic()
    for label in ordered:
        root = resolved[label]
        try:
            for item in root.rglob("*"):
                try:
                    if not item.is_file():
                        continue
                    owner = next(candidate for candidate in ordered if item.is_relative_to(resolved[candidate]))
                    if owner != label:
                        continue
                    bytes_by_root[label] += item.stat().st_size
                    files_by_root[label] += 1
                except OSError as error:
                    errors_by_root[label].append(f"{type(error).__name__}: {error}")
        except OSError as error:
            errors_by_root[label].append(f"{type(error).__name__}: {error}")
    scan_seconds = time.monotonic() - started
    for label, path in resolved.items():
        try:
            if _root_identity(path) != identities[label]:
                raise ValueError(f"write root binding changed during scan: {label}")
        except OSError as error:
            raise ValueError(f"write root binding lost during scan: {label}: {error}") from error
    return {
        label: {
            "canonical_path": str(path),
            "identity": identities[label],
            "drive": path.drive.rstrip(":").upper(),
            "bytes": bytes_by_root[label],
            "files_scanned": files_by_root[label],
            "scan_seconds": scan_seconds,
            "scan_errors": errors_by_root[label],
        }
        for label, path in resolved.items()
    }

def _file_deltas(
    start: Mapping[str, Mapping[str, object]],
    end: Mapping[str, Mapping[str, object]],
) -> tuple[dict[str, int], dict[str, int]]:
    by_root: dict[str, int] = {}
    by_drive = {drive: 0 for drive in OPERATING_RESERVES_GIB}
    for label, before in start.items():
        after = end[label]
        delta = max(0, int(after["bytes"]) - int(before["bytes"]))
        by_root[label] = delta
        by_drive[str(before["drive"])] += delta
    return by_root, by_drive


def _backing_indicators() -> dict[str, object]:
    pagefile = pathlib.Path("C:/pagefile.sys")
    try:
        pagefile_bytes: int | None = pagefile.stat().st_size
    except OSError:
        pagefile_bytes = None
    return {
        "pagefile_logical_bytes": pagefile_bytes,
        "file_delta_attribution": "named_write_roots_only",
        "free_space_delta_attribution": "host_reserve_signal_not_child_write_accounting",
    }


def _file_budget_stop_reason(file_growth_bytes_by_drive: Mapping[str, int], budgets: Mapping[str, float]) -> str | None:
    for drive, budget in budgets.items():
        if file_growth_bytes_by_drive.get(drive, 0) > budget * GIB:
            return f"{drive}: declared file write budget exceeded"
    return None


def _reserve_stop_reason(current_free: Mapping[str, float]) -> str | None:
    for drive, reserve in OPERATING_RESERVES_GIB.items():
        if current_free.get(drive, 0.0) < reserve:
            return f"{drive}: operating reserve crossed"
    return None


def _child_cache_environment(write_roots: Mapping[str, pathlib.Path]) -> tuple[dict[str, str], dict[str, str], pathlib.Path]:
    """Bind ordinary child cache homes beneath the explicitly measured custody root."""

    if "custody" not in write_roots:
        raise ValueError("--write-root custody=PATH is required for child cache custody")
    custody = _canonical_write_root("custody", pathlib.Path(write_roots["custody"]))
    cache_paths = {
        "TEMP": custody / "tmp",
        "TMP": custody / "tmp",
        "TORCH_HOME": custody / "torch",
        "TRITON_CACHE_DIR": custody / "triton",
        "CUDA_CACHE_PATH": custody / "cuda",
        "HF_HOME": custody / "hf",
        "XDG_CACHE_HOME": custody / "xdg-cache",
    }
    for path in set(cache_paths.values()):
        path.mkdir(parents=True, exist_ok=True)
    assertion_path = custody / "child-env-startup.json"
    environment = os.environ.copy()
    bindings = {name: str(path.resolve()) for name, path in cache_paths.items()}
    environment.update(bindings)
    environment["EMBER_DISK_BUDGET_ENV_ASSERTION"] = str(assertion_path)
    # No -I/-B on this spawn (argv[4:] is the certificate-visible command),
    # so bytecode suppression must ride the child env; the bootstrap script
    # re-execs argv[4:] with env=os.environ, so this propagates unbroken.
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return environment, bindings, assertion_path

def _load_child_cache_assertion(
    path: pathlib.Path,
    bindings: Mapping[str, str],
    nonce: str,
) -> tuple[dict[str, object] | None, str | None, str | None]:
    try:
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        payload = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        return None, None, f"child cache assertion unreadable: {type(error).__name__}: {error}"
    if not isinstance(payload, dict) or set(payload) != {"schema_version", "nonce", "bindings"}:
        return None, digest, "child cache assertion schema mismatch"
    if payload["schema_version"] != 1 or payload["nonce"] != nonce or payload["bindings"] != dict(bindings):
        return None, digest, "child cache assertion binding mismatch"
    return payload, digest, None

def _scan_cost(snapshot: Mapping[str, Mapping[str, object]]) -> dict[str, object]:
    values = list(snapshot.values())
    return {
        "files_scanned": sum(int(value["files_scanned"]) for value in values),
        "scan_seconds": float(values[0]["scan_seconds"]) if values else 0.0,
        "root_labels": sorted(snapshot),
    }


def terminate_tree(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        process.terminate()


def _require_receipt_within_write_root(
    receipt_path: pathlib.Path,
    write_roots: Mapping[str, pathlib.Path],
) -> pathlib.Path:
    """Keep the durable runner receipt inside the monitored write envelope."""

    resolved_receipt = pathlib.Path(receipt_path).resolve()
    roots = [
        _canonical_write_root(label, pathlib.Path(raw_path))
        for label, raw_path in write_roots.items()
    ]
    if not any(resolved_receipt.is_relative_to(root) for root in roots):
        raise ValueError("runner receipt must be under a declared write root")
    return resolved_receipt


def run_budgeted(
    command: Sequence[str],
    max_write_gib: Mapping[str, float],
    receipt_path: pathlib.Path,
    *,
    write_roots: Mapping[str, pathlib.Path],
    poll_seconds: float = 0.25,
) -> int:
    receipt_path = _require_receipt_within_write_root(receipt_path, write_roots)
    budgets = _validate_budgets(max_write_gib)
    child_environment, child_cache_bindings, child_assertion_path = _child_cache_environment(write_roots)
    child_assertion_nonce = secrets.token_hex(16)
    child_environment["EMBER_DISK_BUDGET_ENV_NONCE"] = child_assertion_nonce
    root_start = _snapshot_write_roots(write_roots)
    root_last = root_start
    max_root_bytes = {label: int(value["bytes"]) for label, value in root_start.items()}
    max_concurrent_growth_by_drive = {drive: 0 for drive in OPERATING_RESERVES_GIB}
    receipt_root = next(label for label, value in root_start.items() if receipt_path.is_relative_to(pathlib.Path(str(value["canonical_path"]))))
    receipt_drive = str(root_start[receipt_root]["drive"])
    receipt_start_bytes = receipt_path.stat().st_size if receipt_path.is_file() else 0
    receipt_reservation_growth = max(0, FINAL_RECEIPT_RESERVATION_BYTES - receipt_start_bytes)
    receipt_reservation_by_drive = {drive: 0 for drive in OPERATING_RESERVES_GIB}
    receipt_reservation_by_drive[receipt_drive] = receipt_reservation_growth
    if _file_budget_stop_reason(receipt_reservation_by_drive, budgets):
        raise ValueError("declared file write budget cannot reserve the final runner receipt")
    root_scan_samples = [_scan_cost(root_start)]
    root_scan_uncertainty = [
        {"label": label, "errors": value["scan_errors"]}
        for label, value in root_start.items() if value["scan_errors"]
    ]
    root_binding_error: str | None = None
    child_started = False
    child_pid: int | None = None
    child_start_time_ns: int | None = None
    child_executable_sha256: str | None = None
    start_free = current_free_gib()
    start_backing = _backing_indicators()
    errors = assess_capacity(start_free, OPERATING_RESERVES_GIB, budgets)
    started_at = time.time()
    free_samples = [{"at_unix": started_at, "free_gib": start_free}]
    operating_reserve_breaches: set[str] = set()

    def growth_with_receipt_reservation() -> dict[str, int]:
        return {
            drive: max_concurrent_growth_by_drive[drive] + receipt_reservation_by_drive[drive]
            for drive in OPERATING_RESERVES_GIB
        }

    def observe_roots() -> dict[str, dict[str, object]]:
        nonlocal root_last, root_binding_error
        try:
            snapshot = _snapshot_write_roots(write_roots, expected=root_start)
        except ValueError as error:
            root_binding_error = str(error)
            root_scan_uncertainty.append({"label": "binding", "errors": [str(error)]})
            return root_last
        root_last = snapshot
        root_scan_samples.append(_scan_cost(snapshot))
        for label, value in snapshot.items():
            max_root_bytes[label] = max(max_root_bytes[label], int(value["bytes"]))
            if value["scan_errors"]:
                root_scan_uncertainty.append({"label": label, "errors": value["scan_errors"]})
        _, current_growth_by_drive = _file_deltas(root_start, snapshot)
        for drive, growth in current_growth_by_drive.items():
            max_concurrent_growth_by_drive[drive] = max(max_concurrent_growth_by_drive[drive], growth)
        return snapshot

    def finalize_receipt(*, outcome: str, stop_reason: str | None, child_exit_code: int | None, termination_wait_timed_out: bool) -> int:
        child_assertion: dict[str, object] | None = None
        child_assertion_sha256: str | None = None
        child_assertion_error: str | None = None
        if child_started:
            child_assertion, child_assertion_sha256, child_assertion_error = _load_child_cache_assertion(
                child_assertion_path, child_cache_bindings, child_assertion_nonce
            )
        end_free = current_free_gib()
        finished_at = time.time()
        free_samples.append({"at_unix": finished_at, "free_gib": end_free})
        for drive, reserve in OPERATING_RESERVES_GIB.items():
            if end_free[drive] < reserve:
                operating_reserve_breaches.add(drive)
        root_end = observe_roots()
        max_root_bytes[receipt_root] = max(
            max_root_bytes[receipt_root],
            int(root_start[receipt_root]["bytes"]) + receipt_reservation_growth,
        )
        end_by_root, end_by_drive = _file_deltas(root_start, root_end)
        max_snapshot = {label: {**root_end[label], "bytes": max_root_bytes[label]} for label in root_start}
        max_by_root, _ = _file_deltas(root_start, max_snapshot)
        if outcome != "PRELAUNCH_REJECTED":
            stop_reason = (
                stop_reason
                or (f"write root binding lost: {root_binding_error}" if root_binding_error else None)
                or _file_budget_stop_reason(growth_with_receipt_reservation(), budgets)
                or _reserve_stop_reason(end_free)
            )
            if stop_reason:
                outcome = "STOPPED_BY_BUDGET"
        free_delta = {drive: max(0.0, start_free[drive] - end_free[drive]) for drive in OPERATING_RESERVES_GIB}
        receipt = {
            "schema_version": 7,
            "command": list(command),
            "started_at_unix": started_at,
            "finished_at_unix": finished_at,
            "max_write_gib": budgets,
            "write_budget_statistic": "NAMED_FILE_ROOT_MAX_GROWTH_BYTES",
            "final_receipt_reserved_bytes": receipt_reservation_growth,
            "write_roots": {
                label: {
                    "canonical_path": root_start[label]["canonical_path"],
                    "identity": root_start[label]["identity"],
                    "drive": root_start[label]["drive"],
                    "start_bytes": root_start[label]["bytes"],
                    "max_bytes": max_root_bytes[label],
                    "end_bytes": root_end[label]["bytes"],
                }
                for label in root_start
            },
            "file_delta_bytes_by_root": end_by_root,
            "file_delta_bytes_by_drive": end_by_drive,
            "file_max_growth_bytes_by_root": max_by_root,
            "file_max_concurrent_growth_bytes_by_drive": max_concurrent_growth_by_drive,
            "child_cache_bindings": child_cache_bindings,
            "child_cache_assertion_path": str(child_assertion_path),
            "child_cache_assertion": child_assertion,
            "child_cache_assertion_sha256": child_assertion_sha256,
            "child_cache_assertion_error": child_assertion_error,
            "unredirected_cache_roots": [],
            "root_scan_cost": {
                "mode": "bounded_explicit_roots_most_specific",
                "samples": root_scan_samples,
                "total_files_scanned": sum(int(sample["files_scanned"]) for sample in root_scan_samples),
                "total_scan_seconds": sum(float(sample["scan_seconds"]) for sample in root_scan_samples),
            },
            "root_scan_uncertainty": root_scan_uncertainty,
            "free_space_samples": free_samples,
            "free_space_delta_gib": free_delta,
            "unattributed_free_space_delta_gib": {
                drive: max(0.0, free_delta[drive] - end_by_drive[drive] / GIB)
                for drive in OPERATING_RESERVES_GIB
            },
            "backing_indicators": {"start": start_backing, "end": _backing_indicators()},
            "runtime_stop_floors_gib": OPERATING_RESERVES_GIB,
            "operating_reserve_breaches": sorted(operating_reserve_breaches),
            "start_free_gib": start_free,
            "end_free_gib": end_free,
            "stop_reason": stop_reason,
            "child_exit_code": child_exit_code,
            "child_pid": child_pid,
            "child_start_time_ns": child_start_time_ns,
            "child_executable_sha256": child_executable_sha256,
            "termination_wait_timed_out": termination_wait_timed_out,
            "runner_exit_code": 125 if outcome in {"STOPPED_BY_BUDGET", "CHILD_TERMINATION_TIMEOUT", "PRELAUNCH_REJECTED"} else child_exit_code or 0,
            "outcome": outcome,
        }
        if child_started and child_assertion_error and outcome in {"COMPLETED", "CHILD_FAILED"}:
            receipt["outcome"] = "CHILD_ENV_ASSERTION_FAILED"
            receipt["stop_reason"] = child_assertion_error
            receipt["runner_exit_code"] = 125
        receipt["receipt_sha256"] = _receipt_sha256(receipt)
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        return int(receipt["runner_exit_code"])

    if errors:
        return finalize_receipt(outcome="PRELAUNCH_REJECTED", stop_reason="; ".join(errors), child_exit_code=None, termination_wait_timed_out=False)

    process = subprocess.Popen(
        [sys.executable, "-c", _CHILD_ENV_BOOTSTRAP, json.dumps(child_cache_bindings, sort_keys=True), str(child_assertion_path), child_assertion_nonce, *command],
        env=child_environment,
    )
    child_started = True
    child_pid = int(process.pid)
    child_start_time_ns = time.time_ns()
    child_executable_sha256 = hashlib.sha256(pathlib.Path(sys.executable).resolve(strict=True).read_bytes()).hexdigest()
    stop_reason = None
    child_exit_code: int | None = None
    termination_wait_timed_out = False
    try:
        while process.poll() is None:
            time.sleep(poll_seconds)
            observed_free = current_free_gib()
            free_samples.append({"at_unix": time.time(), "free_gib": observed_free})
            for drive, reserve in OPERATING_RESERVES_GIB.items():
                if observed_free[drive] < reserve:
                    operating_reserve_breaches.add(drive)
            observe_roots()
            stop_reason = (
                (f"write root binding lost: {root_binding_error}" if root_binding_error else None)
                or _file_budget_stop_reason(growth_with_receipt_reservation(), budgets)
                or _reserve_stop_reason(observed_free)
            )
            if stop_reason:
                terminate_tree(process)
                break
        try:
            child_exit_code = process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            termination_wait_timed_out = True
            terminate_tree(process)
            child_exit_code = process.poll()
    finally:
        if process.poll() is None:
            terminate_tree(process)

    if stop_reason:
        outcome = "STOPPED_BY_BUDGET"
    elif termination_wait_timed_out:
        outcome = "CHILD_TERMINATION_TIMEOUT"
    elif child_exit_code:
        outcome = "CHILD_FAILED"
    else:
        outcome = "COMPLETED"
    return finalize_receipt(outcome=outcome, stop_reason=stop_reason, child_exit_code=child_exit_code, termination_wait_timed_out=termination_wait_timed_out)

def _parse_write_roots(values: Sequence[str]) -> dict[str, pathlib.Path]:
    roots: dict[str, pathlib.Path] = {}
    for value in values:
        label, separator, raw_path = value.partition("=")
        if not separator or not re.fullmatch(r"[a-z][a-z0-9_-]*", label) or not raw_path or label in roots:
            raise ValueError("--write-root requires unique lowercase NAME=PATH values")
        roots[label] = pathlib.Path(raw_path)
    if not roots:
        raise ValueError("at least one --write-root is required")
    return roots


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-write-gib", type=float)
    parser.add_argument("--max-c-write-gib", type=float)
    parser.add_argument("--max-b-write-gib", type=float)
    parser.add_argument("--receipt", type=pathlib.Path, required=True)
    parser.add_argument("--write-root", action="append", required=True, metavar="NAME=PATH")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.max_write_gib is None and (args.max_c_write_gib is None or args.max_b_write_gib is None):
        parser.error("provide --max-write-gib or both per-drive write budgets")
    common = args.max_write_gib
    budgets = {
        "C": args.max_c_write_gib if args.max_c_write_gib is not None else common,
        "B": args.max_b_write_gib if args.max_b_write_gib is not None else common,
    }
    try:
        write_roots = _parse_write_roots(args.write_root)
    except ValueError as error:
        parser.error(str(error))
    command = list(args.command)
    if command and command[0] == "--":
        command.pop(0)
    if not command:
        parser.error("a command is required after --")
    return run_budgeted(command, budgets, args.receipt, write_roots=write_roots)


if __name__ == "__main__":
    sys.exit(main())
