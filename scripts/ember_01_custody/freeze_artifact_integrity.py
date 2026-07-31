#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Re-verify in-tree files named by SHA-pinned JSON receipts.

The probe is intentionally narrower than a generic hash search.  A digest is
actionable only when its containing receipt also names a repository-relative
file, either as ``{"path"|"name", "sha256"}`` or as a sibling
``<role>_path``/``<role>_file`` plus ``<role>_sha256``.  Every actionable pin
is re-hashed from current bytes.  Known artifact classes also receive a real
format probe.

Provenance transitions may replace a stale pin only when the transition names
the same field.  The replacement hash is then checked against disk like every
other pin; a transition is never a waiver.  Containers whose names include
``superseded`` are historical evidence and cannot override current authority.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Mapping


SCHEMA_VERSION = "ember-freeze-artifact-integrity/v1"
GOAL_ID = "EMBER-02"
WORKSTREAM_ID = "EMBER-02A"
NEXT_EXECUTED_OUTCOME = "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
FormatProbe = Callable[[Path], dict[str, str]]


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(chunk_size)
            if not chunk:
                return digest.hexdigest()
            digest.update(chunk)


def canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    ).encode("utf-8")


def _walk_dicts(
    value: object, path: tuple[str, ...] = ()
) -> Iterable[tuple[tuple[str, ...], Mapping[str, Any]]]:
    if isinstance(value, dict):
        yield path, value
        for key, child in value.items():
            if isinstance(key, str):
                yield from _walk_dicts(child, (*path, key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_dicts(child, (*path, str(index)))


def _flatten_strings(
    value: object, path: tuple[str, ...] = ()
) -> Iterable[tuple[str, str]]:
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                continue
            if isinstance(child, str):
                yield ".".join((*path, key)), child
            else:
                yield from _flatten_strings(child, (*path, key))


def _transition_digest(row: Mapping[str, Any], field: str) -> str | None:
    declared = row.get("field")
    declared_many = row.get("fields")
    if declared == field:
        allowed = True
    elif isinstance(declared_many, list) and field in declared_many:
        allowed = True
    else:
        allowed = False
    if not allowed:
        return None

    candidates: list[tuple[str, str]] = []
    new_value = row.get("new")
    if isinstance(new_value, dict):
        candidates.extend(_flatten_strings(new_value))
    for key, value in row.items():
        if isinstance(key, str) and key.startswith("new_") and isinstance(value, str):
            candidates.append((key[4:], value))

    normalized_field = field.replace(".", "_")
    for candidate, value in candidates:
        normalized_candidate = candidate.replace(".", "_")
        if (
            candidate == field
            or field.endswith("." + candidate)
            or normalized_candidate == normalized_field
            or normalized_field.endswith("_" + normalized_candidate)
        ) and SHA256_RE.fullmatch(value):
            return value
    return None


def _provenance_transitions(receipt: object) -> dict[str, str]:
    transitions: dict[str, str] = {}

    def visit(value: object, container_name: str = "") -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if not isinstance(key, str):
                    continue
                lowered = key.lower()
                if "superseded" in lowered:
                    continue
                if "provenance" in lowered:
                    rows = child if isinstance(child, list) else [child]
                    for row in rows:
                        if not isinstance(row, dict):
                            continue
                        fields: list[str] = []
                        if isinstance(row.get("field"), str):
                            fields.append(row["field"])
                        if isinstance(row.get("fields"), list):
                            fields.extend(
                                item for item in row["fields"] if isinstance(item, str)
                            )
                        for field in fields:
                            digest = _transition_digest(row, field)
                            if digest is not None:
                                transitions[field] = digest
                visit(child, key)
        elif isinstance(value, list):
            for child in value:
                visit(child, container_name)

    visit(receipt)
    return transitions


def _safe_relative_path(raw: str) -> PurePosixPath | None:
    if not raw or "\x00" in raw:
        return None
    normalized = raw.replace("\\", "/")
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
        return None
    parts = normalized.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        return None
    return PurePosixPath(*parts)


def _inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def _resolve_artifact(
    root: Path,
    receipts_dir: Path,
    receipt_path: Path,
    raw: str,
    source_kind: str,
    directory_hint: str | None = None,
) -> tuple[Path | None, str | None]:
    relative = _safe_relative_path(raw)
    if relative is None:
        return None, "PATH_OUTSIDE_REPOSITORY"

    resolved_root = root.resolve()
    if directory_hint is not None:
        normalized_hint = directory_hint.replace("\\", "/")
        hint = PurePosixPath(normalized_hint)
        if (
            not normalized_hint
            or hint.is_absolute()
            or re.match(r"^[A-Za-z]:", normalized_hint)
        ):
            return None, "PATH_OUTSIDE_REPOSITORY"
        candidate = receipt_path.parent.joinpath(
            *hint.parts, *relative.parts
        ).resolve(strict=False)
        if not _inside(resolved_root, candidate):
            return None, "PATH_OUTSIDE_REPOSITORY"
        return candidate, None

    if source_kind == "name":
        candidates = [
            receipt_path.parent.joinpath(*relative.parts),
            receipts_dir.joinpath(*relative.parts),
            root.joinpath(*relative.parts),
        ]
    else:
        candidates = [root.joinpath(*relative.parts)]

    safe_candidates: list[Path] = []
    for candidate in candidates:
        resolved = candidate.resolve(strict=False)
        if not _inside(resolved_root, resolved):
            continue
        safe_candidates.append(resolved)
        if resolved.is_file():
            return resolved, None
    if not safe_candidates:
        return None, "PATH_OUTSIDE_REPOSITORY"
    return safe_candidates[0], None


def _extract_pins(
    root: Path,
    receipts_dir: Path,
    receipt_path: Path,
    receipt: object,
) -> list[dict[str, Any]]:
    transitions = _provenance_transitions(receipt)
    shard_dir = receipt.get("shard_dir") if isinstance(receipt, Mapping) else None
    pins: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for object_path, node in _walk_dicts(receipt):
        candidates: list[tuple[str, str, str, str]] = []
        direct_digest = node.get("sha256")
        if isinstance(direct_digest, str):
            for path_key in ("path", "name", "file"):
                raw_path = node.get(path_key)
                if isinstance(raw_path, str):
                    candidates.append(
                        (
                            ".".join((*object_path, "sha256")),
                            direct_digest,
                            raw_path,
                            "name" if path_key == "name" else "path",
                        )
                    )
                    break

        for key, digest in node.items():
            if (
                not isinstance(key, str)
                or key == "sha256"
                or not key.endswith("_sha256")
                or not isinstance(digest, str)
            ):
                continue
            base = key[: -len("_sha256")]
            for path_key in (f"{base}_path", f"{base}_file", base):
                raw_path = node.get(path_key)
                if isinstance(raw_path, str):
                    candidates.append(
                        (
                            ".".join((*object_path, key)),
                            digest,
                            raw_path,
                            "path",
                        )
                    )
                    break

        for field, original_digest, raw_path, source_kind in candidates:
            identity = (field, raw_path)
            if identity in seen:
                continue
            seen.add(identity)
            expected = transitions.get(field, original_digest)
            pin_source = "provenance_transition" if field in transitions else "receipt"
            directory_hint = (
                shard_dir
                if (
                    source_kind == "name"
                    and object_path[:1] == ("shards",)
                    and isinstance(shard_dir, str)
                )
                else None
            )
            artifact, path_error = _resolve_artifact(
                root, receipts_dir, receipt_path, raw_path, source_kind, directory_hint
            )
            pins.append(
                {
                    "receipt_path": receipt_path.relative_to(root).as_posix(),
                    "field": field,
                    "artifact_path": (
                        None
                        if artifact is None
                        else artifact.relative_to(root.resolve()).as_posix()
                    ),
                    "raw_artifact_reference": raw_path,
                    "expected_sha256": expected,
                    "original_expected_sha256": original_digest,
                    "pin_source": pin_source,
                    "_artifact": artifact,
                    "_path_error": path_error,
                }
            )
    return pins


def probe_tokenizer(path: Path) -> dict[str, str]:
    try:
        from tokenizers import Tokenizer

        Tokenizer.from_file(str(path))
        return {"kind": "tokenizer", "status": "PASS"}
    except Exception as exc:
        detail = str(exc).replace(str(path), "<artifact>")
        return {
            "kind": "tokenizer",
            "status": "FAIL",
            "error_class": type(exc).__name__,
            "detail": detail[:500],
        }


def probe_pytorch_header(path: Path) -> dict[str, str]:
    with path.open("rb") as stream:
        header = stream.read(4)
    valid = header.startswith(b"PK\x03\x04") or (
        len(header) >= 2 and header[0] == 0x80 and 0 < header[1] <= 5
    )
    return {
        "kind": "pytorch_header",
        "status": "PASS" if valid else "FAIL",
    }


DEFAULT_FORMAT_PROBES: Mapping[str, FormatProbe] = {
    "tokenizer.json": probe_tokenizer,
    ".pt": probe_pytorch_header,
}


def _select_probe(path: Path, probes: Mapping[str, FormatProbe]) -> FormatProbe | None:
    if path.name == "tokenizer.json" and "tokenizer.json" in probes:
        return probes["tokenizer.json"]
    return probes.get(path.suffix.lower())


def scan_receipts(
    root: Path,
    receipts_dir: Path,
    *,
    format_probes: Mapping[str, FormatProbe] | None = None,
    exclude_paths: Iterable[Path] = (),
) -> dict[str, Any]:
    root = root.resolve()
    receipts_dir = receipts_dir.resolve()
    probes = DEFAULT_FORMAT_PROBES if format_probes is None else format_probes
    excluded = {path.resolve() for path in exclude_paths}
    receipt_errors: list[dict[str, str]] = []
    pins: list[dict[str, Any]] = []
    receipt_paths = sorted(
        path for path in receipts_dir.rglob("*.json") if path.resolve() not in excluded
    )

    for receipt_path in receipt_paths:
        try:
            receipt = json.loads(
                receipt_path.read_text(encoding="utf-8", errors="strict")
            )
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            receipt_errors.append(
                {
                    "receipt_path": receipt_path.relative_to(root).as_posix(),
                    "code": "RECEIPT_UNREADABLE",
                    "error_class": type(exc).__name__,
                }
            )
            continue
        pins.extend(_extract_pins(root, receipts_dir, receipt_path, receipt))

    public_rows: list[dict[str, Any]] = []
    for pin in pins:
        artifact = pin.pop("_artifact")
        path_error = pin.pop("_path_error")
        violations: list[str] = []
        actual: str | None = None
        format_result: dict[str, str] | None = None

        if path_error is not None:
            violations.append(path_error)
        elif artifact is None or not artifact.is_file():
            violations.append("FILE_MISSING")
        elif not SHA256_RE.fullmatch(pin["expected_sha256"]):
            violations.append("EXPECTED_SHA256_INVALID")
        else:
            try:
                actual = sha256_file(artifact)
            except OSError:
                violations.append("FILE_UNREADABLE")
            if actual is not None and actual != pin["expected_sha256"]:
                violations.append("SHA256_MISMATCH")
            if actual is not None:
                probe = _select_probe(artifact, probes)
                if probe is not None:
                    format_result = probe(artifact)
                    if format_result.get("status") != "PASS":
                        violations.append("FORMAT_INVALID")

        public_rows.append(
            {
                **pin,
                "actual_sha256": actual,
                "format_probe": format_result,
                "status": "VERIFIED" if not violations else "VIOLATION",
                "violations": violations,
            }
        )

    public_rows.sort(
        key=lambda row: (
            row["receipt_path"],
            row["field"],
            row["raw_artifact_reference"],
        )
    )
    violation_count = len(receipt_errors) + sum(
        1 for row in public_rows if row["violations"]
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "goal_id": GOAL_ID,
        "workstream_id": WORKSTREAM_ID,
        "next_executed_outcome": NEXT_EXECUTED_OUTCOME,
        "receipts_directory": receipts_dir.relative_to(root).as_posix(),
        "summary": {
            "receipt_count": len(receipt_paths),
            "pin_count": len(public_rows),
            "verified_count": sum(1 for row in public_rows if not row["violations"]),
            "violation_count": violation_count,
        },
        "receipt_errors": receipt_errors,
        "pins": public_rows,
        "claim_limits": [
            "This receipt reports hash and known-format integrity only.",
            "A verified pin is not model, training, checkpoint-admission, or capability evidence.",
            "A violation remains open custody work; this probe grants no mutation or waiver authority.",
        ],
    }


def _git_head(root: Path) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    value = result.stdout.strip()
    return (
        value
        if result.returncode == 0 and re.fullmatch(r"[0-9a-f]{40}", value)
        else None
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[2]
    )
    parser.add_argument("--receipts", type=Path)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args(argv)
    root = arguments.root.resolve()
    receipts_dir = (
        arguments.receipts.resolve()
        if arguments.receipts is not None
        else root / "receipts"
    )
    output = arguments.output.resolve() if arguments.output is not None else None
    report = scan_receipts(
        root, receipts_dir, exclude_paths=() if output is None else (output,)
    )
    report["captured_at"] = (
        datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    )
    report["source_commit"] = _git_head(root)
    report["verifier_sha256"] = sha256_file(Path(__file__).resolve())
    report["report_sha256"] = hashlib.sha256(canonical_json_bytes(report)).hexdigest()
    encoded = canonical_json_bytes(report)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(encoded)
    else:
        sys.stdout.buffer.write(encoded)
    return 1 if report["summary"]["violation_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
