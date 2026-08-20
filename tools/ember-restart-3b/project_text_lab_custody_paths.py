# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Project the one reviewed 12-row authority class onto portable receipt locators."""

from __future__ import annotations

import copy
import argparse
import ctypes
import errno
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

from text_lab_corpus import (
    _authority_split_root,
    _receipt_custody_path,
    local_license_provenance_v1,
    validate_authority_index,
)


PARTITION_SOURCE_IDS = frozenset(
    {
        "candidate-statistics-heldout-1",
        "candidate-training_infrastructure-train-1",
        "candidate-software_engineering-train-0",
        "candidate-software_engineering-train-1",
        "candidate-software_engineering-heldout-0",
        "candidate-software_engineering-heldout-1",
        "candidate-application_worlds-train-0",
        "candidate-application_worlds-train-1",
        "candidate-application_worlds-heldout-1",
    }
)
PDF_SOURCE_IDS = frozenset(
    {
        "candidate-physics-heldout-0",
        "candidate-computer_science-train-0",
        "candidate-scientific_method-heldout-0",
    }
)
PROJECTED_SOURCE_IDS = PARTITION_SOURCE_IDS | PDF_SOURCE_IDS
ARTIFACTS = {
    "bundle": "text-lab-source-receipt-bundle-v4.json",
    "corpus": "owned-text-lab-corpus-v4.json",
    "identity": "owned-text-lab-input-identity-v4.json",
    "index": "text-lab-authority-index-v2.json",
}
SOURCE_SHA256 = {
    "bundle": "d2d74b1258843a8eccd4ff2a7903507afd3aa7cf34b7b2ce9aa3ed95be8fba41",
    "corpus": "137c533dd6bd185d0f0618fcd27ed7643872882a0a62d5d4650bf75bd6080c68",
    "identity": "7b6dbe56c6a0b462db4091bb6c481efab9d94bc6cdffcd7309ae5b3498f0fba6",
    "index": "4305be780f4b4b68028a796b940d1866ac495c01aeef11d58a534faf1323f73c",
}
PROJECTION_RECEIPT = "custody-projection-receipt.json"
PROJECTION_LOG = "custody-projection-mint-log.json"
PROJECTION_SCHEMA = "ember-text-lab-custody-projection-v1"


def atomic_publish_no_replace(source: Path, destination: Path) -> None:
    """Atomically publish one directory while refusing every existing destination."""
    if os.name == "nt":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        move_file = kernel32.MoveFileExW
        move_file.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
        move_file.restype = ctypes.c_int
        if move_file(str(source), str(destination), 0) != 0:
            return
        error = ctypes.get_last_error()
        if error in {80, 183}:
            raise FileExistsError(error, "destination already exists", str(destination))
        raise OSError(error, os.strerror(error), str(destination))
    libc = ctypes.CDLL(None, use_errno=True)
    source_raw = os.fsencode(source)
    destination_raw = os.fsencode(destination)
    if sys.platform.startswith("linux"):
        rename = getattr(libc, "renameat2", None)
        if rename is None:
            raise RuntimeError("atomic no-replace directory publication is unsupported")
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        result = rename(-100, source_raw, -100, destination_raw, 1)
    elif sys.platform == "darwin":
        rename = getattr(libc, "renamex_np", None)
        if rename is None:
            raise RuntimeError("atomic no-replace directory publication is unsupported")
        rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        result = rename(source_raw, destination_raw, 4)
    else:
        raise RuntimeError("atomic no-replace directory publication is unsupported")
    if result == 0:
        return
    error = ctypes.get_errno()
    if error in {errno.EEXIST, errno.ENOTEMPTY}:
        raise FileExistsError(error, "destination already exists", str(destination))
    raise OSError(error, os.strerror(error), str(destination))


def _portable_locator(receipt_custody_root: Path, value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("projection source path is absent")
    source = Path(value)
    if not source.is_absolute():
        raise ValueError("projection source path must be absolute")
    try:
        relative = source.resolve(strict=True).relative_to(
            receipt_custody_root.resolve(strict=True)
        ).as_posix()
    except (OSError, ValueError) as error:
        raise ValueError("projection source path is outside receipt custody root") from error
    _receipt_custody_path(receipt_custody_root, relative)
    return relative


def project_rows(
    rows: list[dict[str, Any]],
    *,
    receipt_custody_root: Path,
) -> list[dict[str, Any]]:
    """Rewrite only the closed class's receipt locators; preserve all other values."""
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("projection rows must be objects")
    by_id = {row.get("source_id"): row for row in rows}
    if len(by_id) != len(rows) or set(by_id) != PROJECTED_SOURCE_IDS:
        raise ValueError("projection requires the exact reviewed 12-row class")

    projected = copy.deepcopy(rows)
    for row in projected:
        source_id = row["source_id"]
        if source_id in PARTITION_SOURCE_IDS:
            row["license_partition_receipt"] = _portable_locator(
                receipt_custody_root,
                row.get("license_partition_receipt"),
            )
            continue
        evidence = row.get("license_evidence")
        if not isinstance(evidence, dict) or evidence.get("kind") != "publisher_terms":
            raise ValueError("projected PDF row lacks publisher-terms evidence")
        evidence["connector_receipt_path"] = _portable_locator(
            receipt_custody_root,
            evidence.get("connector_receipt_path"),
        )
        transform_locator = _portable_locator(
            receipt_custody_root,
            evidence.get("transform_receipt_path"),
        )
        transform_raw = _receipt_custody_path(
            receipt_custody_root,
            transform_locator,
        ).read_bytes()
        try:
            transform_receipt = json.loads(transform_raw)
        except json.JSONDecodeError as error:
            raise ValueError("projected PDF transform receipt is not JSON") from error
        if (
            not isinstance(transform_receipt, dict)
            or transform_receipt.get("receipt_sha256")
            != evidence.get("transform_receipt_sha256")
        ):
            raise ValueError("projected PDF transform receipt identity changed")
        evidence["transform_receipt_path"] = transform_locator
        evidence["transform_receipt_raw_sha256"] = _sha(transform_raw)
    return projected


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _source_packet(source_custody: Path) -> dict[str, dict[str, Any]]:
    packet: dict[str, dict[str, Any]] = {}
    for role, name in ARTIFACTS.items():
        path = source_custody / name
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"source authority artifact is absent: {name}")
        raw = path.read_bytes()
        if _sha(raw) != SOURCE_SHA256[role]:
            raise ValueError(f"source authority artifact bytes changed: {name}")
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError(f"source authority artifact is not an object: {name}")
        packet[role] = value
    return packet


def _source_raw(source_custody: Path) -> dict[str, bytes]:
    raw = {name: (source_custody / name).read_bytes() for name in ARTIFACTS.values()}
    for role, name in ARTIFACTS.items():
        if _sha(raw[name]) != SOURCE_SHA256[role]:
            raise ValueError(f"source authority artifact bytes changed: {name}")
    return raw


def _mapping_rows(source_raw: dict[str, bytes], generated: dict[str, bytes]) -> list[dict[str, Any]]:
    source_rows = json.loads(source_raw[ARTIFACTS["corpus"]]).get("sources")
    projected_rows = json.loads(generated[ARTIFACTS["corpus"]]).get("sources")
    if not isinstance(source_rows, list) or not isinstance(projected_rows, list):
        raise ValueError("projection corpus rows are unavailable")
    source_by_id = {row.get("source_id"): row for row in source_rows if isinstance(row, dict)}
    projected_by_id = {row.get("source_id"): row for row in projected_rows if isinstance(row, dict)}
    if set(source_by_id) != set(projected_by_id) or not PROJECTED_SOURCE_IDS.issubset(source_by_id):
        raise ValueError("projection row stores differ")
    mappings = []
    for source_id in sorted(PROJECTED_SOURCE_IDS):
        source = source_by_id[source_id]
        projected = projected_by_id[source_id]
        if source_id in PARTITION_SOURCE_IDS:
            locators = [{
                "field": "license_partition_receipt",
                "source": source.get("license_partition_receipt"),
                "projected": projected.get("license_partition_receipt"),
                "receipt_sha256": source.get("license_partition_sha256"),
            }]
        else:
            source_evidence = source.get("license_evidence")
            projected_evidence = projected.get("license_evidence")
            if not isinstance(source_evidence, dict) or not isinstance(projected_evidence, dict):
                raise ValueError("projection PDF evidence changed shape")
            locators = [
                {
                    "field": field,
                    "source": source_evidence.get(field),
                    "projected": projected_evidence.get(field),
                    "receipt_sha256": source_evidence.get(hash_field),
                }
                for field, hash_field in (
                    ("connector_receipt_path", "connector_receipt_sha256"),
                    ("transform_receipt_path", "transform_receipt_sha256"),
                )
            ]
        restored = copy.deepcopy(projected)
        if source_id in PARTITION_SOURCE_IDS:
            restored["license_partition_receipt"] = source["license_partition_receipt"]
        else:
            for locator in locators:
                restored["license_evidence"][locator["field"]] = locator["source"]
            restored["license_evidence"].pop("transform_receipt_raw_sha256", None)
            if "l4_receipt" in source:
                restored["l4_receipt"] = source["l4_receipt"]
            else:
                restored.pop("l4_receipt", None)
        if restored != source:
            raise ValueError(f"projection changed non-locator row authority: {source_id}")
        mappings.append({
            "source_id": source_id,
            "content_sha256": source.get("content_sha256"),
            "locators": sorted(locators, key=lambda value: value["field"]),
        })
    return mappings


def packet_localize_projected_index(
    generated: dict[str, bytes],
) -> tuple[dict[str, bytes], dict[str, str]]:
    """Rewrite only external artifact locators for one derived custody packet."""
    localized = dict(generated)
    index_name = ARTIFACTS["index"]
    pre_raw = generated[index_name]
    index = json.loads(pre_raw)
    for role, binding_name in (
        ("bundle", "receipt_bundle"),
        ("corpus", "corpus"),
        ("identity", "input_identity"),
    ):
        binding = index.get(binding_name)
        expected = f"data/ember-restart-3b/{ARTIFACTS[role]}"
        if not isinstance(binding, dict) or binding.get("path") != expected:
            raise ValueError(f"projected index locator changed: {binding_name}")
        binding["path"] = ARTIFACTS[role]
    post_raw = _canonical(index)
    localized[index_name] = post_raw
    return localized, {
        "artifact": index_name,
        "pre_rewrite_sha256": _sha(pre_raw),
        "post_rewrite_sha256": _sha(post_raw),
        "reason": "derived-root binding",
    }


def _projection_receipt(
    *, repo: Path, source_custody: Path, source_receipt_name: str,
    source_receipt_sha256: str, receipt_custody_root: Path,
    source_base_commit: str, source_raw: dict[str, bytes], generated: dict[str, bytes],
    validation_receipt: dict[str, Any],
    locator_rewrite: dict[str, str],
) -> dict[str, Any]:
    return {
        "schema_version": PROJECTION_SCHEMA,
        "result": "VERIFIED_DERIVED_CUSTODY",
        "source_base_commit": source_base_commit,
        "source_custody_path": str(source_custody.resolve(strict=True)),
        "source_receipt_name": source_receipt_name,
        "source_receipt_sha256": source_receipt_sha256,
        "receipt_custody_root": str(receipt_custody_root.resolve(strict=True)),
        "source_artifacts": {
            name: {"bytes": len(raw), "sha256": _sha(raw)}
            for name, raw in sorted(source_raw.items())
        },
        "projected_artifacts": {
            name: {"bytes": len(raw), "sha256": _sha(raw)}
            for name, raw in sorted(generated.items())
        },
        "row_mappings": _mapping_rows(source_raw, generated),
        "validation_receipt": validation_receipt,
        "locator_rewrites": [locator_rewrite],
        "producer": {
            "path": "tools/ember-restart-3b/project_text_lab_custody_paths.py",
            "sha256": _sha((repo / "tools" / "ember-restart-3b" / "project_text_lab_custody_paths.py").read_bytes()),
        },
    }


def validate_projection_custody(
    *, repo: Path, projection_receipt_path: Path, expected_receipt_sha256: str,
    source_custody: Path, source_receipt_name: str, source_receipt_sha256: str,
) -> dict[str, Any]:
    source_custody = source_custody.resolve(strict=True)
    receipt_path = projection_receipt_path.resolve(strict=True)
    projection_root = receipt_path.parent
    entries = list(projection_root.iterdir())
    expected_names = set(ARTIFACTS.values()) | {PROJECTION_RECEIPT, PROJECTION_LOG}
    if any(not path.is_file() or path.is_symlink() for path in entries) or {path.name for path in entries} != expected_names:
        raise ValueError("projection custody file set changed")
    receipt_raw = receipt_path.read_bytes()
    if _sha(receipt_raw) != expected_receipt_sha256:
        raise ValueError("projection receipt bytes changed")
    try:
        receipt = json.loads(receipt_raw)
    except json.JSONDecodeError as error:
        raise ValueError("projection receipt is not JSON") from error
    source_receipt = source_custody / source_receipt_name
    if not source_receipt.is_file() or _sha(source_receipt.read_bytes()) != source_receipt_sha256:
        raise ValueError("projection predecessor receipt changed")
    source_raw = _source_raw(source_custody)
    generated = {name: (projection_root / name).read_bytes() for name in ARTIFACTS.values()}
    try:
        receipt_custody_root = Path(receipt.get("receipt_custody_root", "")).resolve(strict=True)
    except (OSError, TypeError) as error:
        raise ValueError("projection receipt custody root changed") from error
    authority_validation = validate_authority_index(
        repo,
        index_relative=ARTIFACTS["index"],
        external_authority_root=projection_root,
        receipt_custody_root=receipt_custody_root,
    )
    if authority_validation.get("result") != "NOT_ADMITTED_SOURCE_EVIDENCE_MISSING":
        raise ValueError("projected authority did not remain fail-closed")
    expected_generated, locator_rewrite = packet_localize_projected_index(build_projected_packet(
        repo=repo, source_custody=source_custody,
        receipt_custody_root=receipt_custody_root,
        source_base_commit=receipt["source_base_commit"],
    ))
    expected = _projection_receipt(
        repo=repo, source_custody=source_custody,
        source_receipt_name=source_receipt_name,
        source_receipt_sha256=source_receipt_sha256,
        receipt_custody_root=receipt_custody_root,
        source_base_commit=receipt.get("source_base_commit"),
        source_raw=source_raw, generated=generated,
        validation_receipt=authority_validation,
        locator_rewrite=locator_rewrite,
    )
    if receipt != expected:
        raise ValueError("projection receipt bindings changed")
    if generated != expected_generated:
        raise ValueError("projected authority artifact bytes changed")
    log = json.loads((projection_root / PROJECTION_LOG).read_bytes())
    if log != {"schema_version": "ember-text-lab-custody-projection-log-v1", "receipt_sha256": expected_receipt_sha256}:
        raise ValueError("projection mint log binding changed")
    return {"generated": generated, "receipt": receipt}


def mint_projection_custody(
    *, repo: Path, source_custody: Path, source_receipt_name: str,
    source_receipt_sha256: str, receipt_custody_root: Path,
    source_base_commit: str, output: Path,
) -> dict[str, Any]:
    source_custody = source_custody.resolve(strict=True)
    receipt_custody_root = receipt_custody_root.resolve(strict=True)
    if output.exists():
        raise FileExistsError(f"output already exists: {output}")
    source_receipt = source_custody / source_receipt_name
    if not source_receipt.is_file() or _sha(source_receipt.read_bytes()) != source_receipt_sha256:
        raise ValueError("projection predecessor receipt changed")
    source_raw = _source_raw(source_custody)
    generated, locator_rewrite = packet_localize_projected_index(build_projected_packet(
        repo=repo, source_custody=source_custody,
        receipt_custody_root=receipt_custody_root,
        source_base_commit=source_base_commit,
    ))
    staging = output.with_name(f".{output.name}.staging-{uuid.uuid4().hex}")
    staging.mkdir(parents=True)
    published = False
    try:
        for name, raw in generated.items():
            (staging / name).write_bytes(raw)
        staging_validation = validate_authority_index(
            repo,
            index_relative=ARTIFACTS["index"],
            external_authority_root=staging,
            receipt_custody_root=receipt_custody_root,
        )
        if staging_validation.get("result") != "NOT_ADMITTED_SOURCE_EVIDENCE_MISSING":
            raise ValueError("projected authority did not remain fail-closed")
        receipt = _projection_receipt(
            repo=repo, source_custody=source_custody,
            source_receipt_name=source_receipt_name,
            source_receipt_sha256=source_receipt_sha256,
            receipt_custody_root=receipt_custody_root,
            source_base_commit=source_base_commit,
            source_raw=source_raw, generated=generated,
            validation_receipt=staging_validation,
            locator_rewrite=locator_rewrite,
        )
        receipt_raw = _canonical(receipt)
        (staging / PROJECTION_RECEIPT).write_bytes(receipt_raw)
        (staging / PROJECTION_LOG).write_bytes(_canonical({
            "schema_version": "ember-text-lab-custody-projection-log-v1",
            "receipt_sha256": _sha(receipt_raw),
        }))
        atomic_publish_no_replace(staging, output)
        published = True
        validate_projection_custody(
            repo=repo, projection_receipt_path=output / PROJECTION_RECEIPT,
            expected_receipt_sha256=_sha(receipt_raw), source_custody=source_custody,
            source_receipt_name=source_receipt_name,
            source_receipt_sha256=source_receipt_sha256,
        )
        return {"custody_path": str(output.resolve()), "receipt_sha256": _sha(receipt_raw)}
    except BaseException:
        shutil.rmtree(output if published else staging, ignore_errors=True)
        raise


def _git_is_ancestor(repo: Path, commit: str) -> bool:
    kwargs: dict[str, Any] = {"capture_output": True, "text": True, "check": False}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    result = subprocess.run(
        ["git", "-C", str(repo), "merge-base", "--is-ancestor", commit, "HEAD"],
        **kwargs,
    )
    return result.returncode == 0


def resolve_source_base_commit(
    *, repo: Path, write: bool, requested: str | None
) -> str:
    """Bind writes to an explicit reachable commit and checks to recorded bytes."""
    if write:
        value = requested
        if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{40}", value) is None:
            raise ValueError("--write requires a full lowercase --source-base-commit")
        if not _git_is_ancestor(repo, value):
            raise ValueError("--source-base-commit is not an ancestor of HEAD")
        return value
    if requested is not None:
        raise ValueError("--source-base-commit is valid only with --write")
    identity_path = (
        repo
        / "data"
        / "ember-restart-3b"
        / ARTIFACTS["identity"]
    )
    try:
        value = json.loads(identity_path.read_bytes()).get("source_base_commit")
    except (OSError, json.JSONDecodeError, AttributeError) as error:
        raise ValueError("recorded source_base_commit is unavailable") from error
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{40}", value) is None:
        raise ValueError("recorded source_base_commit is malformed")
    return value


def build_projected_packet(
    *,
    repo: Path,
    source_custody: Path,
    receipt_custody_root: Path,
    source_base_commit: str,
) -> dict[str, bytes]:
    """Build only the four checked-in authority artifacts from the frozen 28-row packet."""
    packet = _source_packet(source_custody)
    source_rows = packet["corpus"].get("sources")
    if not isinstance(source_rows, list) or packet["bundle"].get("candidates") != source_rows:
        raise ValueError("source authority row stores differ")
    selected = [row for row in source_rows if row.get("source_id") in PROJECTED_SOURCE_IDS]
    replacements = {
        row["source_id"]: row
        for row in project_rows(selected, receipt_custody_root=receipt_custody_root)
    }
    for source_id in PDF_SOURCE_IDS:
        row = replacements[source_id]
        row["l4_receipt"] = local_license_provenance_v1(
            content_sha256=row["content_sha256"],
            license_spdx=row["license_spdx"],
            evidence=row["license_evidence"],
            generator="pdf-text-extraction-v1",
        )
    rows = [replacements.get(row["source_id"], copy.deepcopy(row)) for row in source_rows]
    bundle = copy.deepcopy(packet["bundle"])
    bundle["candidates"] = rows
    bundle_raw = _canonical(bundle)
    corpus = copy.deepcopy(packet["corpus"])
    corpus["sources"] = rows
    corpus["receipt_bundle_sha256"] = _sha(bundle_raw)
    corpus["receipt_custody_root_binding"] = "runtime-supplied-corpus-root-v1"
    corpus["train_root_sha256"] = _authority_split_root(rows, "train")
    corpus["heldout_root_sha256"] = _authority_split_root(rows, "heldout")
    corpus_raw = _canonical(corpus)

    tools = repo / "tools" / "ember-restart-3b"
    identity = copy.deepcopy(packet["identity"])
    identity["corpus_sha256"] = _sha(corpus_raw)
    identity["source_base_commit"] = source_base_commit
    identity["code_files"] = {
        "text_lab_corpus": _sha((tools / "text_lab_corpus.py").read_bytes()),
        "train": _sha((tools / "train.py").read_bytes()),
        "run_vertical_slice": _sha((tools / "run_vertical_slice.py").read_bytes()),
    }
    identity_raw = _canonical(identity)

    index = copy.deepcopy(packet["index"])
    generated = {
        "bundle": bundle_raw,
        "corpus": corpus_raw,
        "identity": identity_raw,
    }
    for role in ("bundle", "corpus", "identity"):
        binding_name = {
            "bundle": "receipt_bundle",
            "corpus": "corpus",
            "identity": "input_identity",
        }[role]
        binding = index[binding_name]
        binding["path"] = f"data/ember-restart-3b/{ARTIFACTS[role]}"
        binding["sha256"] = _sha(generated[role])
        schema_path = Path(binding["schema"]["path"])
        binding["schema"]["sha256"] = _sha((repo / schema_path).read_bytes())
    index_raw = _canonical(index)
    return {
        ARTIFACTS["bundle"]: bundle_raw,
        ARTIFACTS["corpus"]: corpus_raw,
        ARTIFACTS["identity"]: identity_raw,
        ARTIFACTS["index"]: index_raw,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-custody", type=Path, required=True)
    parser.add_argument("--receipt-custody-root", type=Path, required=True)
    parser.add_argument("--source-base-commit")
    parser.add_argument("--source-receipt-name")
    parser.add_argument("--source-receipt-sha256")
    parser.add_argument("--output-custody", type=Path)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[2]
    source_base_commit = resolve_source_base_commit(
        repo=repo,
        write=args.write or args.output_custody is not None,
        requested=args.source_base_commit,
    )
    if args.output_custody is not None:
        if args.write or not args.source_receipt_name or not args.source_receipt_sha256:
            raise ValueError("derived custody requires receipt name/hash and forbids --write")
        result = mint_projection_custody(
            repo=repo, source_custody=args.source_custody.resolve(strict=True),
            source_receipt_name=args.source_receipt_name,
            source_receipt_sha256=args.source_receipt_sha256,
            receipt_custody_root=args.receipt_custody_root.resolve(strict=True),
            source_base_commit=source_base_commit, output=args.output_custody.absolute(),
        )
        print(json.dumps(result, sort_keys=True))
        return 0
    generated = build_projected_packet(
        repo=repo,
        source_custody=args.source_custody.resolve(strict=True),
        receipt_custody_root=args.receipt_custody_root.resolve(strict=True),
        source_base_commit=source_base_commit,
    )
    output = repo / "data" / "ember-restart-3b"
    mismatches = []
    for name, raw in generated.items():
        path = output / name
        if args.write:
            path.write_bytes(raw)
        elif not path.is_file() or path.read_bytes() != raw:
            mismatches.append(name)
    if mismatches:
        raise ValueError("generated authority artifacts are stale: " + ", ".join(mismatches))
    print(json.dumps({"result": "VERIFIED", "generated_sha256": {name: _sha(raw) for name, raw in generated.items()}}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
