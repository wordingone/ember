#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Run and verify the governed #1949 two-OS fresh-clone proof plan."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Mapping, Sequence


NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
WHEEL_SHA256 = "51a52592b3b99e102b609654876bd65f19f999935166d1352678931132b0c670"
SDIST_SHA256 = "f4695c21257f0d9b537ec2692c941d02ee143b7cc1276941349a546573b2ef73"
REQUIRED_LEG_IDS = (
    "exact_dependency_wheel",
    "refused_dependency_sdist",
    "canonical_domain_imports",
    "deterministic_data",
    "direct_training_checkpoint_evaluation_runtime_governance",
    "lab_training_checkpoint_evaluation_runtime_governance",
    "external_data_present",
    "external_data_absent_refusal",
    "zero_adapter_dangling_duplicate_authority_scan",
)
NEGATIVE_LEG_IDS = frozenset(("refused_dependency_sdist", "external_data_absent_refusal"))
SHELL_EXECUTABLES = {
    "bash", "bash.exe", "cmd", "cmd.exe", "powershell", "powershell.exe",
    "pwsh", "pwsh.exe", "sh", "sh.exe",
}


class ACleanRefusal(RuntimeError):
    pass


def canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def derive_self(value: Mapping[str, object]) -> str:
    unsigned = dict(value)
    unsigned.pop("self_sha256", None)
    return sha256_bytes(canonical_json(unsigned))


def write_receipt_no_overwrite(path: Path, value: Mapping[str, object]) -> dict[str, object]:
    payload = dict(value)
    payload["self_sha256"] = derive_self(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(canonical_json(payload) + b"\n")
    return payload


def _is_absolute_executable(value: str) -> bool:
    return PureWindowsPath(value).is_absolute() or PurePosixPath(value).is_absolute()


def _hex64(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _hex40(value: object) -> bool:
    return isinstance(value, str) and len(value) == 40 and all(character in "0123456789abcdef" for character in value)


def validate_plan(plan: Mapping[str, object]) -> dict[str, Any]:
    if plan.get("schema_version") != "ember-issue1949-a-clean-plan-v1":
        raise ACleanRefusal("PLAN_SCHEMA_REFUSED")
    if plan.get("self_sha256") != derive_self(plan):
        raise ACleanRefusal("PLAN_SELF_REFUSED")
    declared_head = plan.get("declared_head")
    if not _hex40(declared_head):
        raise ACleanRefusal("PLAN_HEAD_REFUSED")
    setuptools = plan.get("setuptools")
    if not isinstance(setuptools, dict):
        raise ACleanRefusal("DEPENDENCY_AUTHORITY_REFUSED")
    if (
        setuptools.get("wheel") != "setuptools-84.0.0-py3-none-any.whl"
        or setuptools.get("wheel_sha256") != WHEEL_SHA256
        or setuptools.get("refused_sdist") != "setuptools-84.0.0.tar.gz"
        or setuptools.get("refused_sdist_sha256") != SDIST_SHA256
    ):
        raise ACleanRefusal("DEPENDENCY_AUTHORITY_REFUSED")
    legs = plan.get("legs")
    if not isinstance(legs, list) or tuple(row.get("id") for row in legs if isinstance(row, dict)) != REQUIRED_LEG_IDS:
        raise ACleanRefusal("PLAN_LEG_SET_REFUSED")
    leg_contracts: set[bytes] = set()
    for row in legs:
        if not isinstance(row, dict):
            raise ACleanRefusal("PLAN_LEG_REFUSED")
        argv = row.get("argv")
        if not isinstance(argv, list) or not argv or not all(isinstance(part, str) and part for part in argv):
            raise ACleanRefusal(f"LEG_ARGV_REFUSED:{row.get('id')}")
        executable = argv[0]
        if not _is_absolute_executable(executable) or Path(executable).name.lower() in SHELL_EXECUTABLES:
            raise ACleanRefusal(f"LEG_EXECUTABLE_REFUSED:{row.get('id')}:{executable}")
        expected_exit = row.get("expected_exit")
        if not isinstance(expected_exit, int):
            raise ACleanRefusal(f"LEG_EXPECTED_EXIT_REFUSED:{row.get('id')}")
        if row.get("id") in NEGATIVE_LEG_IDS and expected_exit == 0:
            raise ACleanRefusal(f"NEGATIVE_LEG_EXPECTED_EXIT_REFUSED:{row.get('id')}")
        if row.get("id") not in NEGATIVE_LEG_IDS and expected_exit != 0:
            raise ACleanRefusal(f"POSITIVE_LEG_EXPECTED_EXIT_REFUSED:{row.get('id')}")
        if (
            row.get("semantic_contract_id") != row.get("id")
            or not _hex64(row.get("semantic_contract_sha256"))
            or not _hex64(row.get("executable_raw_sha256"))
            or row.get("argv_sha256") != sha256_bytes(canonical_json(argv))
        ):
            raise ACleanRefusal(f"LEG_CONTRACT_REFUSED:{row.get('id')}")
        signature = canonical_json({
            "argv": argv,
            "executable_raw_sha256": row["executable_raw_sha256"],
            "semantic_contract_sha256": row["semantic_contract_sha256"],
        })
        if signature in leg_contracts:
            raise ACleanRefusal(f"LEG_CONTRACT_REFUSED:{row.get('id')}:duplicate")
        leg_contracts.add(signature)
    topology = plan.get("topology_canary")
    if topology is not None:
        if not isinstance(topology, dict) or topology.get("result") != "PASS":
            raise ACleanRefusal("TOPOLOGY_CANARY_REFUSED")
        if not _hex64(topology.get("raw_sha256")) or not _hex64(topology.get("self_sha256")):
            raise ACleanRefusal("TOPOLOGY_CANARY_IDENTITY_REFUSED")
    return json.loads(json.dumps(plan))


def _is_relative_to(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def validate_checkout_identity(
    *, declared_head: str, actual_head: str, porcelain: bytes, repo_root: Path,
    caller_cwd: Path, declared_platform: str, actual_platform: str,
) -> None:
    if declared_head != actual_head:
        raise ACleanRefusal(f"CHECKOUT_HEAD_REFUSED:{actual_head}")
    if porcelain:
        raise ACleanRefusal("CHECKOUT_DIRTY_REFUSED")
    root_text = str(repo_root)
    if " " not in root_text or root_text.isascii():
        raise ACleanRefusal("ARBITRARY_ROOT_SHAPE_REFUSED")
    if _is_relative_to(caller_cwd, repo_root):
        raise ACleanRefusal("CALLER_CWD_INSIDE_CHECKOUT_REFUSED")
    if declared_platform not in {"windows", "linux"} or declared_platform != actual_platform:
        raise ACleanRefusal(f"PLATFORM_IDENTITY_REFUSED:{declared_platform}:{actual_platform}")


def _git(repo_root: Path, *arguments: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(repo_root), *arguments], stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=NO_WINDOW, check=False,
    )
    if result.returncode:
        raise ACleanRefusal(f"GIT_REFUSED:{arguments}:{result.stderr.decode(errors='replace')}")
    return result.stdout


def validate_fresh_clone(repo_root: Path) -> None:
    if not (repo_root / ".git").is_dir():
        raise ACleanRefusal("FRESH_CLONE_IDENTITY_REFUSED")


def validate_executable_identity(row: Mapping[str, object]) -> None:
    argv = row["argv"]
    assert isinstance(argv, list)
    executable = Path(argv[0])
    if not executable.is_file():
        raise ACleanRefusal(f"LEG_EXECUTABLE_MISSING:{row.get('id')}:{executable}")
    actual = sha256_file(executable)
    if actual != row.get("executable_raw_sha256"):
        raise ACleanRefusal(f"LEG_EXECUTABLE_IDENTITY_REFUSED:{row.get('id')}:{actual}")


def _actual_platform() -> str:
    system = platform.system().lower()
    if system == "windows":
        return "windows"
    if system == "linux":
        return "linux"
    raise ACleanRefusal(f"PLATFORM_UNSUPPORTED:{system}")


def run_plan(repo_root: Path, plan_path: Path, output: Path, declared_platform: str) -> dict[str, object]:
    if output.exists():
        raise FileExistsError(f"OUTPUT_EXISTS_REFUSED:{output}")
    repo_root = repo_root.resolve(strict=True)
    plan_path = plan_path.resolve(strict=True)
    plan_raw = plan_path.read_bytes()
    validate_fresh_clone(repo_root)
    plan = validate_plan(json.loads(plan_raw))
    caller_cwd = Path.cwd().resolve()
    actual_head = _git(repo_root, "rev-parse", "HEAD").decode().strip()
    porcelain = _git(repo_root, "status", "--porcelain")
    validate_checkout_identity(
        declared_head=plan["declared_head"], actual_head=actual_head, porcelain=porcelain,
        repo_root=repo_root, caller_cwd=caller_cwd,
        declared_platform=declared_platform, actual_platform=_actual_platform(),
    )
    stream_root = output.parent / f"{output.stem}.streams"
    if stream_root.exists():
        raise FileExistsError(f"STREAM_ROOT_EXISTS_REFUSED:{stream_root}")
    stream_root.mkdir(parents=True)
    rows = []
    for leg in plan["legs"]:
        validate_executable_identity(leg)
        stdout_path = stream_root / f"{leg['id']}.stdout.log"
        stderr_path = stream_root / f"{leg['id']}.stderr.log"
        result = subprocess.run(
            leg["argv"], cwd=caller_cwd, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=float(leg.get("timeout_seconds", 300)),
            creationflags=NO_WINDOW, check=False,
        )
        stdout_path.write_bytes(result.stdout)
        stderr_path.write_bytes(result.stderr)
        if result.returncode != leg["expected_exit"]:
            raise ACleanRefusal(f"LEG_EXIT_REFUSED:{leg['id']}:{result.returncode}")
        rows.append({
            "id": leg["id"], "argv": leg["argv"], "expected_exit": leg["expected_exit"],
            "actual_exit": result.returncode,
            "argv_sha256": leg["argv_sha256"],
            "executable_raw_sha256": leg["executable_raw_sha256"],
            "semantic_contract_id": leg["semantic_contract_id"],
            "semantic_contract_sha256": leg["semantic_contract_sha256"],
            "stdout_raw_sha256": sha256_bytes(result.stdout),
            "stderr_raw_sha256": sha256_bytes(result.stderr),
        })
    final_head = _git(repo_root, "rev-parse", "HEAD").decode().strip()
    final_porcelain = _git(repo_root, "status", "--porcelain")
    if final_head != actual_head or final_porcelain:
        raise ACleanRefusal("CHECKOUT_POST_RUN_MUTATION_REFUSED")
    return write_receipt_no_overwrite(output, {
        "schema_version": "ember-issue1949-a-clean-v1",
        "result": "PASS",
        "platform": declared_platform,
        "source_head": actual_head,
        "repo_root": str(repo_root),
        "caller_cwd": str(caller_cwd),
        "plan_raw_sha256": sha256_bytes(plan_raw),
        "plan_self_sha256": plan["self_sha256"],
        "legs": rows,
        "topology_canary": plan.get("topology_canary"),
        "claim_boundary": "ARCHITECTURE_AND_PORTABILITY_MATRIX_ONLY; NO CORPUS CAPABILITY TRAINING THROUGHPUT OR MILESTONE CREDIT",
    })


def verify_receipt(path: Path) -> dict[str, object]:
    raw = path.read_bytes()
    supplied = json.loads(raw)
    if raw != canonical_json(supplied) + b"\n":
        raise ACleanRefusal("RECEIPT_RAW_REFUSED")
    if supplied.get("self_sha256") != derive_self(supplied):
        raise ACleanRefusal("RECEIPT_SELF_REFUSED")
    if supplied.get("result") != "PASS":
        raise ACleanRefusal("RECEIPT_RESULT_REFUSED")
    return {"result": "PASS", "raw_sha256": sha256_bytes(raw), "self_sha256": supplied["self_sha256"]}


def write_refusal_receipt(
    *, output: Path, repo_root: Path, plan_path: Path, declared_platform: str, refusal: BaseException,
) -> dict[str, object]:
    streams = []
    stream_root = output.parent / f"{output.stem}.streams"
    if stream_root.is_dir():
        for path in sorted(candidate for candidate in stream_root.rglob("*") if candidate.is_file()):
            streams.append({
                "path": path.relative_to(stream_root).as_posix(),
                "bytes": path.stat().st_size,
                "raw_sha256": sha256_file(path),
            })
    plan_identity: dict[str, object] = {"path": str(plan_path)}
    if plan_path.is_file():
        plan_identity.update({"bytes": plan_path.stat().st_size, "raw_sha256": sha256_file(plan_path)})
    detail = str(refusal)
    return write_receipt_no_overwrite(output, {
        "schema_version": "ember-issue1949-a-clean-refusal-v1",
        "result": "REFUSED",
        "refusal_class": detail.split(":", 1)[0],
        "refusal_detail": detail,
        "platform": declared_platform,
        "repo_root": str(repo_root),
        "plan": plan_identity,
        "streams": streams,
        "claim_boundary": "FAIL_CLOSED_DIAGNOSTIC_ONLY; ZERO ARCHITECTURE PORTABILITY OR CAMPAIGN CREDIT",
    })


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--repo-root", type=Path, required=True)
    run_parser.add_argument("--plan", type=Path, required=True)
    run_parser.add_argument("--output", type=Path, required=True)
    run_parser.add_argument("--platform", choices=["windows", "linux"], required=True)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = (
            run_plan(args.repo_root, args.plan, args.output, args.platform)
            if args.command == "run" else verify_receipt(args.receipt)
        )
    except (ACleanRefusal, FileExistsError, json.JSONDecodeError, OSError, subprocess.TimeoutExpired) as exc:
        if args.command == "run" and not args.output.exists():
            refusal = write_refusal_receipt(
                output=args.output, repo_root=args.repo_root, plan_path=args.plan,
                declared_platform=args.platform, refusal=exc,
            )
            print(json.dumps({
                "result": "REFUSED", "raw_sha256": sha256_file(args.output),
                "self_sha256": refusal["self_sha256"], "refusal_class": refusal["refusal_class"],
            }, sort_keys=True))
        print(f"A_CLEAN_REFUSED:{exc}", file=os.sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
