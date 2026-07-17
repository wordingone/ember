#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Render only a receipt that central admission has independently admitted."""
import argparse, hashlib, json, math, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path

EXECUTION_AUTHORITIES = Path(__file__).resolve().parents[1] / "manifests" / "ember-restart-execution-authorities-v1.json"
IDENTITY_FIELDS = ("checkpoint_manifest_sha256", "model_config_sha256", "benchmark_id", "benchmark_version", "split_sha256", "harness_sha256", "protocol_sha256", "predictions_sha256", "score_artifact_sha256", "criterion_id", "criterion_result", "metrics", "verifier_sha256")
IDENTITY_SHA_FIELDS = ("checkpoint_manifest_sha256", "model_config_sha256", "split_sha256", "harness_sha256", "protocol_sha256", "predictions_sha256", "score_artifact_sha256", "verifier_sha256")


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def _registry_is_pinned_bytes(registry_bytes):
    try:
        authority = json.loads(EXECUTION_AUTHORITIES.read_bytes().decode("utf-8"))
        authorities = authority.get("authorities") if isinstance(authority, dict) else None
        if not isinstance(authorities, list):
            return False
        expected = {entry.get("trusted_verifier_registry_sha256") for entry in authorities if isinstance(entry, dict) and isinstance(entry.get("trusted_verifier_registry_sha256"), str)}
        return _sha256(registry_bytes) in expected
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, AttributeError):
        return False


def _registry_is_pinned(registry):
    try:
        return _registry_is_pinned_bytes(registry.read_bytes())
    except OSError:
        return False


def _reject_symlink_components(candidate, root):
    root = Path(root)
    relative = Path(candidate).relative_to(root)
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("unsafe symlink")


def _python_imports(source):
    try:
        text = source.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return []
    modules = []
    for match in re.finditer(r"^\s*(?:from\s+([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)|import\s+([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*))", text, re.MULTILINE):
        module = match.group(1) or match.group(2)
        if module:
            modules.append(module.replace(".", "/") + ".py")
    return modules


def _registry_path(value, root, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field}: path required")
    relative = Path(value)
    if relative.is_absolute() or relative.drive:
        raise ValueError(f"{field}: path escapes registry root")
    root = Path(root)
    candidate = root / relative
    _reject_symlink_components(candidate, root)
    source = candidate.resolve()
    try:
        source.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"{field}: path escapes registry root") from exc
    if not source.is_file():
        raise ValueError(f"{field}: verifier file missing")
    return relative, source


def _pinned_registry_snapshot(registry, *, registry_bytes=None):
    registry_root = None
    try:
        if registry_bytes is None:
            registry_bytes = registry.read_bytes()
        authority = json.loads(EXECUTION_AUTHORITIES.read_bytes().decode("utf-8"))
        if not _registry_is_pinned_bytes(registry_bytes):
            return None
        payload = json.loads(registry_bytes.decode("utf-8"))
        entries = payload.get("verifiers") if isinstance(payload, dict) else None
        if not isinstance(entries, list):
            entries = []
        registry_root = Path(tempfile.mkdtemp(prefix=".trusted-registry-", dir=registry.parent))
        snapshot = registry_root / registry.name
        snapshot.write_bytes(registry_bytes)
        copied = set()

        def copy_source(relative, source):
            normalized = relative.as_posix()
            if normalized in copied:
                return
            copied.add(normalized)
            destination = registry_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(source.read_bytes())
            for imported in _python_imports(source):
                helper = source.parent / Path(imported)
                if helper.is_file():
                    copy_source(helper.relative_to(registry.parent), helper)

        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                raise ValueError(f"verifiers[{index}]: malformed entry")
            relative, source = _registry_path(entry.get("path"), registry.parent, f"verifiers[{index}]")
            copy_source(relative, source)
            declared = entry.get("files", [])
            if not isinstance(declared, list):
                raise ValueError(f"verifiers[{index}].files: expected list")
            declared_paths = set()
            for file_index, asset in enumerate(declared):
                if not isinstance(asset, dict) or set(asset) != {"path", "sha256"}:
                    raise ValueError(f"verifiers[{index}].files[{file_index}]: malformed declared asset")
                asset_relative, asset_source = _registry_path(asset.get("path"), registry.parent, f"verifiers[{index}].files[{file_index}]")
                normalized_asset = asset_relative.as_posix()
                if normalized_asset in declared_paths:
                    raise ValueError(f"verifiers[{index}].files: duplicate path")
                declared_paths.add(normalized_asset)
                expected_sha = asset.get("sha256")
                if not isinstance(expected_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_sha) or _sha256(asset_source.read_bytes()) != expected_sha:
                    raise ValueError(f"verifiers[{index}].files[{file_index}]: content hash mismatch")
                copy_source(asset_relative, asset_source)
        return snapshot, registry_root
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        if registry_root is not None:
            try:
                shutil.rmtree(registry_root)
            except OSError as cleanup:
                raise RuntimeError(f"trusted registry cleanup failed: {cleanup}")
        return None


def _admitted(manifest, registry, input_bytes):
    if manifest is None or registry is None:
        return False
    registry_snapshot = None
    registry_snapshot_root = None
    closure_root = None
    try:
        # Caller-selected registry bytes must first match the external
        # execution-authority anchor; an internally consistent substitute is
        # not admission authority.
        registry_bytes = registry.read_bytes()
        if not _registry_is_pinned_bytes(registry_bytes):
            return False
        pinned = _pinned_registry_snapshot(registry, registry_bytes=registry_bytes)
        if pinned is None:
            return False
        registry_snapshot, registry_snapshot_root = pinned
        manifest_bytes = manifest.read_bytes()
        payload = json.loads(manifest_bytes.decode("utf-8"))
        if not isinstance(payload, dict) or payload.get("stage") != "OWNED_ADMITTED":
            return False
        root = manifest.resolve().parent
        root_real = root.resolve()
        closure_root = Path(tempfile.mkdtemp(prefix=".admission-closure-", dir=root))
        wanted = _sha256(input_bytes)
        matched = False
        staged = set()

        def scan_json(data, field, document_base):
            try:
                value = json.loads(data.decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError):
                return
            walk(value, field, document_base)

        def stage_path(value, field, document_base, key):
            nonlocal matched
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field}: path required")
            relative = Path(value)
            if relative.is_absolute() or relative.drive:
                raise ValueError(f"{field}: path escapes artifact root")
            root_relative = key in {"manifest_path", "checkpoint_manifest_path", "main_index_path"} or re.search(r"(?:^|\.)(?:checkpoint_manifest|main_index)\.path$", field) is not None
            base = Path(".") if root_relative else document_base
            candidate = root / base / relative
            _reject_symlink_components(candidate, root)
            source = candidate.resolve()
            try:
                source.relative_to(root_real)
            except ValueError as exc:
                raise ValueError(f"{field}: path escapes artifact root") from exc
            if not source.exists():
                raise ValueError(f"{field}: unsafe or missing path")
            normalized = source.relative_to(root_real).as_posix()
            if normalized in staged:
                return normalized
            destination = closure_root / Path(normalized)
            destination.parent.mkdir(parents=True, exist_ok=True)
            staged.add(normalized)
            if source.is_file():
                source_bytes = source.read_bytes()
                destination.write_bytes(source_bytes)
                if field.endswith("receipt_path") and _sha256(source_bytes) == wanted:
                    matched = True
                if source.suffix.lower() == ".json":
                    scan_json(source_bytes, field, source.parent.relative_to(root_real))
            elif source.is_dir():
                for child in source.rglob("*"):
                    _reject_symlink_components(child, root)
                    child_relative = child.relative_to(source)
                    child_destination = destination / child_relative
                    if child.is_dir():
                        child_destination.mkdir(parents=True, exist_ok=True)
                    elif child.is_file():
                        child_destination.parent.mkdir(parents=True, exist_ok=True)
                        child_bytes = child.read_bytes()
                        child_destination.write_bytes(child_bytes)
                        if child.suffix.lower() == ".json":
                            scan_json(child_bytes, f"{field}/{child_relative.as_posix()}", child.parent.relative_to(root_real))
            else:
                raise ValueError(f"{field}: unsupported path")
            return normalized

        def walk(value, field="manifest", document_base=Path(".")):
            if isinstance(value, dict):
                for key, child in value.items():
                    child_field = f"{field}.{key}"
                    if isinstance(child, str) and key != "identity_path" and (key == "path" or key.endswith("_path") or key.endswith("_dir")):
                        stage_path(child, child_field, document_base, key)
                    else:
                        walk(child, child_field, document_base)
            elif isinstance(value, list):
                for index, child in enumerate(value):
                    walk(child, f"{field}[{index}]", document_base)

        walk(payload)
        if not matched:
            return False
        manifest_snapshot = closure_root / "admission.json"
        manifest_snapshot.write_bytes(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n")
        contract = Path(__file__).parent / "ember_restart" / "contract.py"
        checked = subprocess.run([sys.executable, str(contract), "validate", str(manifest_snapshot), "--trusted-verifier-registry", str(registry_snapshot)], capture_output=True, text=True, timeout=120, check=False)
        return checked.returncode == 0
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, subprocess.SubprocessError):
        return False
    finally:
        cleanup_errors = []
        for path, label in ((closure_root, "admission closure"), (registry_snapshot_root, "trusted registry closure")):
            if path is None:
                continue
            try:
                shutil.rmtree(path)
            except OSError as exc:
                cleanup_errors.append(f"{label} cleanup failed: {exc}")
        if cleanup_errors:
            raise RuntimeError("; ".join(cleanup_errors))


def _claim_identity_complete(result):
    if any(not isinstance(result.get(field), str) or not re.fullmatch(r"[0-9a-f]{64}", result[field]) for field in IDENTITY_SHA_FIELDS):
        return False
    if not isinstance(result.get("benchmark_id"), str) or not result["benchmark_id"].strip() or not isinstance(result.get("benchmark_version"), str) or not result["benchmark_version"].strip():
        return False
    if not isinstance(result.get("criterion_id"), str) or not result["criterion_id"].strip() or result.get("criterion_result") != "PASSED":
        return False
    metrics = result.get("metrics")
    return isinstance(metrics, dict) and bool(metrics) and all(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) for value in metrics.values())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--admission-manifest", type=Path)
    parser.add_argument("--trusted-verifier-registry", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output must not pre-exist")
    try:
        input_bytes = args.input.read_bytes()
        result = json.loads(input_bytes.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        parser.error("input must be JSON")
    if not isinstance(result, dict):
        parser.error("input must be an object")
    measured = result.get("result") == "MEASURED" and _claim_identity_complete(result) and _admitted(args.admission_manifest, args.trusted_verifier_registry, input_bytes)
    label = "MEASURED CAPABILITY" if measured else "NOT CLAIM-BEARING"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=args.output.parent, delete=False) as handle:
        handle.write(f"# Ember evaluation result\n\nStatus: {label}\n\nCapability: {result.get('capability', 'unknown')}\n")
        if measured:
            handle.write(f"\nreceipt_sha256: {_sha256(input_bytes)}\n")
            handle.write(f"receipt_json: {json.dumps(result, sort_keys=True, separators=(',', ':'))}\n")
            for key in IDENTITY_FIELDS:
                handle.write(f"{key}: {json.dumps(result[key], sort_keys=True, separators=(',', ':'))}\n")
        temporary = Path(handle.name)
    try:
        os.replace(temporary, args.output)
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
