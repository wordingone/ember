#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Ingest a pinned EvalPlus result only when it binds an owned sample sidecar."""
import argparse
import hashlib
import json
import math
import os
import re
import tempfile
from pathlib import Path

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SUITES = {"humanevalplus_v0.1.10", "mbppplus_v0.2.0"}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def ids_sha256(ids: set[str]) -> str:
    return sha256(("\n".join(sorted(ids)) + "\n").encode("utf-8"))


def finite(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def evalplus_protocol_sha256(manifest: dict[str, object], suite: str, adapters: list[dict[str, object]]) -> str:
    asset = manifest.get("frozen_task_assets")
    asset_entry = asset.get(suite) if isinstance(asset, dict) else None
    asset_sha = asset_entry.get("sha256") if isinstance(asset_entry, dict) else None
    license_sha = manifest.get("license_sha256")
    if not isinstance(asset_sha, str) or not SHA256_RE.fullmatch(asset_sha) or not isinstance(license_sha, str) or not SHA256_RE.fullmatch(license_sha):
        raise ValueError("EvalPlus custody lacks task/license identity for protocol")
    source_commit = manifest.get("source_commit")
    source_tree = manifest.get("source_tree")
    if not isinstance(source_commit, str) or not re.fullmatch(r"[0-9a-f]{40}", source_commit) or not isinstance(source_tree, str) or not re.fullmatch(r"[0-9a-f]{40}", source_tree):
        raise ValueError("EvalPlus custody lacks upstream source commit/tree identity")
    adapter_identity = "|".join(f"{entry['path']}:{entry['sha256']}" for entry in sorted(adapters, key=lambda item: item["path"]))
    material = f"evalplus:{manifest.get('benchmark_id')}:{suite}:{asset_sha}:{license_sha}:{source_commit}:{source_tree}:{adapter_identity}"
    return sha256(material.encode("utf-8"))


def _load_frozen_code_manifest(path: Path, binding: dict[str, object], suite: str) -> tuple[bytes, dict[str, object]]:
    manifest_bytes = path.read_bytes()
    if sha256(manifest_bytes) != binding.get("frozen_code_manifest_sha256"):
        raise ValueError("EvalPlus frozen code manifest hash mismatch")
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    if not isinstance(manifest, dict) or manifest.get("schema_version") != "ember-restart-benchmark-custody-v1" or manifest.get("benchmark_id") != "evalplus":
        raise ValueError("invalid EvalPlus frozen code manifest")
    expected_version = suite.rsplit("_", 1)[-1]
    if binding.get("benchmark_id") != manifest.get("benchmark_id") or binding.get("benchmark_version") != expected_version:
        raise ValueError("EvalPlus benchmark version/identity is not bound by frozen custody")
    assets = manifest.get("frozen_task_assets")
    asset = assets.get(suite) if isinstance(assets, dict) else None
    if not isinstance(asset, dict) or asset.get("sha256") != binding.get("task_asset_sha256"):
        raise ValueError("EvalPlus frozen code manifest does not bind task asset")
    protocol = manifest.get("protocol_sha256")
    adapters = manifest.get("scoring_adapters")
    if not isinstance(adapters, list) or not adapters:
        raise ValueError("EvalPlus frozen code manifest lacks scoring adapter custody")
    root = (path.parent.parent if path.parent.name == "manifests" else path.parent).resolve()
    required_paths = {"scripts/ember_restart_eval_evalplus_adapter.py", "scripts/ember_restart_eval_evalplus_result.py"}
    seen: set[str] = set()
    for entry in adapters:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str) or not isinstance(entry.get("sha256"), str) or not SHA256_RE.fullmatch(entry["sha256"]):
            raise ValueError("EvalPlus scoring adapter custody is malformed")
        relative = Path(entry["path"])
        if relative.is_absolute() or relative.drive:
            raise ValueError("EvalPlus scoring adapter path escapes custody root")
        source = (root / relative).resolve()
        if not source.is_file() or not source.is_relative_to(root) or sha256(source.read_bytes()) != entry["sha256"]:
            raise ValueError("EvalPlus scoring adapter bytes do not match frozen custody")
        seen.add(relative.as_posix())
    if not required_paths.issubset(seen):
        raise ValueError("EvalPlus frozen code manifest lacks required adapter identities")
    if not isinstance(protocol, str) or not SHA256_RE.fullmatch(protocol) or protocol != evalplus_protocol_sha256(manifest, suite, adapters) or binding.get("protocol_sha256") != protocol:
        raise ValueError("EvalPlus protocol is not derived from frozen code custody")
    for identity in ("checkpoint_manifest_sha256", "model_config_sha256"):
        expected = manifest.get(identity)
        if expected is not None:
            if not isinstance(expected, str) or not SHA256_RE.fullmatch(expected) or binding.get(identity) != expected:
                raise ValueError(f"EvalPlus {identity} is not bound by frozen custody")
    return manifest_bytes, manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples-binding", required=True, type=Path)
    parser.add_argument("--eval-result", required=True, type=Path)
    parser.add_argument("--frozen-code-manifest", required=True, type=Path)
    parser.add_argument("--score-output", required=True, type=Path)
    arguments = parser.parse_args()
    if arguments.score_output.exists():
        parser.error("score output must not pre-exist")
    try:
        binding_bytes = arguments.samples_binding.read_bytes()
        result_bytes = arguments.eval_result.read_bytes()
        binding = json.loads(binding_bytes.decode("utf-8"))
        result = json.loads(result_bytes.decode("utf-8"))
        required = {"schema_version", "result", "suite", "benchmark_id", "benchmark_version", "split_sha256", "protocol_sha256", "checkpoint_manifest_sha256", "model_config_sha256", "task_asset_sha256", "evalplus_dataset_md5", "predictions_sha256", "samples_sha256", "task_ids_sha256", "sample_count", "frozen_code_manifest_sha256"}
        if not isinstance(binding, dict) or set(binding) != required or binding["schema_version"] != "ember-restart-evalplus-samples-binding-v1" or binding["result"] != "PREFLIGHT_ONLY" or binding["suite"] not in SUITES or binding.get("benchmark_id") != "evalplus" or binding.get("benchmark_version") != binding["suite"].rsplit("_", 1)[-1] or not isinstance(binding["sample_count"], int) or isinstance(binding["sample_count"], bool) or binding["sample_count"] <= 0:
            raise ValueError("invalid EvalPlus samples sidecar")
        _load_frozen_code_manifest(arguments.frozen_code_manifest, binding, binding["suite"])
        if not isinstance(result, dict) or not isinstance(result.get("hash"), str) or not isinstance(result.get("eval"), dict) or not isinstance(result.get("pass_at_k"), dict):
            raise ValueError("invalid EvalPlus result artifact")
        evaluations = result["eval"]
        if result["hash"] != binding["evalplus_dataset_md5"] or len(evaluations) != binding["sample_count"] or ids_sha256(set(evaluations)) != binding["task_ids_sha256"]:
            raise ValueError("EvalPlus result does not bind samples sidecar")
        base_pass = 0
        plus_pass = 0
        for task_id, outcomes in evaluations.items():
            if not isinstance(task_id, str) or not task_id or not isinstance(outcomes, list) or len(outcomes) != 1 or not isinstance(outcomes[0], dict):
                raise ValueError("EvalPlus result does not bind samples sidecar")
            outcome = outcomes[0]
            if outcome.get("base_status") not in {"pass", "fail", "timeout"} or outcome.get("plus_status") not in {"pass", "fail", "timeout"}:
                raise ValueError("EvalPlus result has unsupported task status")
            base_pass += outcome["base_status"] == "pass"
            plus_pass += outcome["base_status"] == outcome["plus_status"] == "pass"
        metrics = {"base_pass_at_1": base_pass / len(evaluations), "plus_pass_at_1": plus_pass / len(evaluations)}
        supplied = result["pass_at_k"]
        if supplied.get("base", {}).get("pass@1") != metrics["base_pass_at_1"] or supplied.get("plus", {}).get("pass@1") != metrics["plus_pass_at_1"] or not all(finite(value) for value in metrics.values()):
            raise ValueError("EvalPlus result pass@1 does not reproduce task outcomes")
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as error:
        parser.error(f"invalid EvalPlus result inputs: {error}")
    payload = {"result": "SELFTEST", "claim_status": "SELFTEST_ONLY_RESULT_ARTIFACT_VALIDATOR", "criterion_id": "ember-3b-text-capability-v1", "criterion_result": "FAILED", "metrics": metrics, "sample_count": binding["sample_count"], "benchmark_id": binding["benchmark_id"], "benchmark_version": binding["benchmark_version"], "split_sha256": binding["split_sha256"], "protocol_sha256": binding["protocol_sha256"], "checkpoint_manifest_sha256": binding["checkpoint_manifest_sha256"], "model_config_sha256": binding["model_config_sha256"], "predictions_sha256": binding["predictions_sha256"], "samples_binding_sha256": sha256(binding_bytes), "evalplus_result_sha256": sha256(result_bytes), "upstream": "EvalPlus result artifact bound to canonical owned samples and frozen scorer custody"}
    arguments.score_output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=arguments.score_output.parent, prefix=arguments.score_output.name + ".", suffix=".tmp", delete=False) as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")
        temporary = Path(handle.name)
    try:
        os.replace(temporary, arguments.score_output)
    finally:
        temporary.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
