#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Render only a receipt that central admission has independently admitted."""
import argparse, hashlib, json, os, shutil, subprocess, sys, tempfile
from pathlib import Path

EXECUTION_AUTHORITIES = Path(__file__).resolve().parents[1] / "manifests" / "ember-restart-execution-authorities-v1.json"
IDENTITY_FIELDS = ("checkpoint_manifest_sha256", "model_config_sha256", "benchmark_id", "benchmark_version", "split_sha256", "harness_sha256", "protocol_sha256", "predictions_sha256", "score_artifact_sha256", "criterion_id", "criterion_result", "metrics", "verifier_sha256")


def _sha256(data):
 return hashlib.sha256(data).hexdigest()


def _registry_is_pinned(registry):
 try:
  authority = json.loads(EXECUTION_AUTHORITIES.read_bytes().decode("utf-8"))
  expected = {entry.get("trusted_verifier_registry_sha256") for entry in authority.get("authorities", []) if isinstance(entry, dict)}
  return _sha256(registry.read_bytes()) in expected
 except (OSError, UnicodeError, json.JSONDecodeError):
  return False


def _pinned_registry_snapshot(registry):
 try:
  registry_bytes = registry.read_bytes()
  authority = json.loads(EXECUTION_AUTHORITIES.read_bytes().decode("utf-8"))
  expected = {entry.get("trusted_verifier_registry_sha256") for entry in authority.get("authorities", []) if isinstance(entry, dict)}
  if _sha256(registry_bytes) not in expected:
   return None
  with tempfile.NamedTemporaryFile("wb", dir=registry.parent, suffix=".json", delete=False) as handle:
   handle.write(registry_bytes)
   return Path(handle.name)
 except (OSError, UnicodeError, json.JSONDecodeError):
  return None


def _admitted(manifest, registry, input_bytes):
 if manifest is None or registry is None:
  return False
 registry_snapshot = None
 closure_root = None
 try:
  registry_snapshot = _pinned_registry_snapshot(registry)
  if registry_snapshot is None:
   return False
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

  def stage_path(value, field):
   nonlocal matched
   if not isinstance(value, str) or not value.strip():
    raise ValueError(f"{field}: path required")
   relative = Path(value)
   if relative.is_absolute() or relative.drive:
    raise ValueError(f"{field}: path escapes artifact root")
   source = (root / relative).resolve()
   try:
    source.relative_to(root_real)
   except ValueError as exc:
    raise ValueError(f"{field}: path escapes artifact root") from exc
   if source.is_symlink() or not source.exists():
    raise ValueError(f"{field}: unsafe or missing path")
   normalized = relative.as_posix()
   if normalized in staged:
    return normalized
   destination = closure_root / Path(normalized)
   destination.parent.mkdir(parents=True, exist_ok=True)
   if destination.exists():
    raise ValueError(f"{field}: duplicate staged path")
   if source.is_file():
    source_bytes = source.read_bytes()
    destination.write_bytes(source_bytes)
    if field.endswith("receipt_path") and _sha256(source_bytes) == wanted:
     matched = True
   elif source.is_dir():
    for child in source.rglob("*"):
     if child.is_symlink():
      raise ValueError(f"{field}: unsafe symlink")
     child_relative = child.relative_to(source)
     child_destination = destination / child_relative
     if child.is_dir():
      child_destination.mkdir(parents=True, exist_ok=True)
     elif child.is_file():
      child_destination.parent.mkdir(parents=True, exist_ok=True)
      child_destination.write_bytes(child.read_bytes())
   else:
    raise ValueError(f"{field}: unsupported path")
   staged.add(normalized)
   return normalized

  def walk(value, field="manifest"):
   if isinstance(value, dict):
    for key, child in value.items():
     child_field = f"{field}.{key}"
     if isinstance(child, str) and (key == "path" or key.endswith("_path") or key.endswith("_dir")):
      value[key] = stage_path(child, child_field)
     else:
      walk(child, child_field)
   elif isinstance(value, list):
    for index, child in enumerate(value):
     walk(child, f"{field}[{index}]")

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
  if closure_root is not None:
   shutil.rmtree(closure_root, ignore_errors=True)
  if registry_snapshot is not None:
   registry_snapshot.unlink(missing_ok=True)
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
 measured = result.get("result") == "MEASURED" and _admitted(args.admission_manifest, args.trusted_verifier_registry, input_bytes)
 measured = measured and all(key in result for key in IDENTITY_FIELDS)
 label = "MEASURED CAPABILITY" if measured else "NOT CLAIM-BEARING"
 args.output.parent.mkdir(parents=True, exist_ok=True)
 with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=args.output.parent, delete=False) as handle:
  handle.write(f"# Ember evaluation result\n\nStatus: {label}\n\nCapability: {result.get('capability', 'unknown')}\n")
  if measured:
   handle.write(f"\nreceipt_sha256: {_sha256(input_bytes)}\n")
   for key in IDENTITY_FIELDS:
    handle.write(f"{key}: {json.dumps(result[key], sort_keys=True, separators=(',', ':'))}\n")
  temporary = Path(handle.name)
 try:
  os.replace(temporary, args.output)
 finally:
  temporary.unlink(missing_ok=True)


if __name__ == "__main__":
 main()
