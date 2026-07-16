#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Score frozen MMMU multiple-choice predictions without making an admission claim."""
import argparse
import ast
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from ember_restart.prediction_contract import ContractError, validate_predictions


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_predictions(data: bytes) -> tuple[dict, dict[str, object]]:
    try:
        envelope = validate_predictions(json.loads(data.decode("utf-8")))
    except (ContractError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("canonical checkpoint predictions are required") from error
    benchmark = envelope["benchmark"]
    if benchmark.get("id") != "MMMU" or benchmark.get("capability") != "image":
        raise ValueError("canonical predictions must declare MMMU image capability")
    converted: dict[str, object] = {}
    for row in envelope["rows"]:
        output = row.get("output")
        if not isinstance(output, dict) or output.get("kind") != "text" or not isinstance(output.get("text"), str) or not output["text"] or row["id"] in converted:
            raise ValueError("canonical MMMU prediction rows require unique text outputs")
        converted[row["id"]] = output["text"]
    if not converted:
        raise ValueError("canonical MMMU predictions must be non-empty")
    return envelope, converted


def verify_frozen_scorer(manifest: dict[str, object], mmmu_root: Path) -> tuple[str, Path]:
    strict = manifest.get("schema_version") == "ember-restart-benchmark-custody-v1" or "scorer" in manifest
    if not strict:
        split = manifest.get("split")
        answer_sha = split.get("answer_dictionary_sha256") if isinstance(split, dict) else None
        version = manifest.get("benchmark_version")
        if not isinstance(answer_sha, str) or not isinstance(version, str):
            raise ValueError("MMMU frozen custody requires benchmark split identity")
        return sha256(f"MMMU:{version}:{answer_sha}".encode()), (mmmu_root / "mmmu" / "main_eval_only.py").resolve()
    if manifest.get("schema_version") != "ember-restart-benchmark-custody-v1":
        raise ValueError("MMMU canonical scoring requires the strict custody schema")
    scorer = manifest.get("scorer")
    if not isinstance(scorer, dict) or not isinstance(scorer.get("path"), str) or not isinstance(scorer.get("sha256"), str) or len(scorer["sha256"]) != 64 or scorer["sha256"].lower() != scorer["sha256"]:
        raise ValueError("MMMU frozen custody requires scorer path and sha256")
    relative = Path(scorer["path"])
    if relative.is_absolute() or relative.drive:
        raise ValueError("MMMU scorer path escapes frozen root")
    source = (mmmu_root / relative).resolve()
    if not source.is_file() or not source.is_relative_to(mmmu_root.resolve()) or sha256(source.read_bytes()) != scorer["sha256"]:
        raise ValueError("MMMU scorer bytes do not match frozen custody")
    upstream_tree = manifest.get("upstream_tree_git_sha1")
    if not isinstance(upstream_tree, str) or len(upstream_tree) != 40 or upstream_tree.lower() != upstream_tree or any(character not in "0123456789abcdef" for character in upstream_tree):
        raise ValueError("MMMU frozen custody requires upstream tree identity")
    adapter = manifest.get("scoring_adapter")
    if not isinstance(adapter, dict) or adapter.get("path") != "scripts/ember_restart_eval_mmmu.py" or not isinstance(adapter.get("sha256"), str) or len(adapter["sha256"]) != 64 or adapter["sha256"].lower() != adapter["sha256"]:
        raise ValueError("MMMU frozen custody requires scoring adapter identity")
    adapter_source = (Path(__file__).resolve().parents[1] / adapter["path"]).resolve()
    if not adapter_source.is_file() or sha256(adapter_source.read_bytes()) != adapter["sha256"]:
        raise ValueError("MMMU scoring adapter bytes do not match frozen custody")
    license_sha256 = manifest.get("license_sha256")
    protocol = manifest.get("protocol_sha256")
    if not isinstance(license_sha256, str) or len(license_sha256) != 64 or license_sha256.lower() != license_sha256 or any(character not in "0123456789abcdef" for character in license_sha256):
        raise ValueError("MMMU frozen custody requires license_sha256")
    if not isinstance(protocol, str) or len(protocol) != 64 or protocol.lower() != protocol or any(character not in "0123456789abcdef" for character in protocol):
        raise ValueError("MMMU frozen custody requires protocol_sha256")
    version = manifest.get("benchmark_version")
    split = manifest.get("split")
    answer_sha = split.get("answer_dictionary_sha256") if isinstance(split, dict) else None
    image_materialization = manifest.get("image_input_materialization")
    image_sha = image_materialization.get("artifact_sha256") if isinstance(image_materialization, dict) else ""
    if image_materialization is not None and (not isinstance(image_sha, str) or len(image_sha) != 64 or image_sha.lower() != image_sha):
        raise ValueError("MMMU image custody requires artifact identity")
    expected = sha256(f"MMMU:{version}:{answer_sha}:{scorer['sha256']}:{license_sha256}:{upstream_tree}:{adapter['sha256']}:{image_sha}".encode())
    if protocol != expected:
        raise ValueError("MMMU protocol is not derived from complete scorer/source custody")
    return protocol, source


def validate_manifest_identity(manifest: dict[str, object], envelope: dict[str, object]) -> None:
    """Reject canonical predictions whose checkpoint/config identity is not custody-bound."""
    for identity in ("checkpoint_manifest_sha256", "model_config_sha256"):
        expected = manifest.get(identity)
        if expected is not None and envelope.get(identity) != expected:
            raise ValueError(f"MMMU {identity} is not bound by frozen custody")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mmmu-root", required=True, type=Path)
    parser.add_argument("--answers", required=True, type=Path)
    parser.add_argument("--canonical-predictions", required=True, type=Path)
    parser.add_argument("--frozen-mmmu-manifest", required=True, type=Path)
    parser.add_argument("--frozen-image-inputs", type=Path)
    parser.add_argument("--score-output", required=True, type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=120)
    arguments = parser.parse_args()
    if arguments.score_output.exists():
        parser.error("score output must not pre-exist")
    if not 1 <= arguments.timeout_seconds <= 120:
        parser.error("timeout seconds must be between 1 and 120")
    try:
        answer_bytes = arguments.answers.read_bytes()
        prediction_bytes = arguments.canonical_predictions.read_bytes()
        manifest_bytes = arguments.frozen_mmmu_manifest.read_bytes()
        answers = json.loads(answer_bytes.decode("utf-8"))
        manifest = json.loads(manifest_bytes.decode("utf-8"))
        envelope, converted = canonical_predictions(prediction_bytes)
        validate_manifest_identity(manifest, envelope)
        benchmark = envelope["benchmark"]
        if not isinstance(answers, dict) or not answers or any(not isinstance(value, dict) or value.get("question_type") != "multiple-choice" for value in answers.values()):
            raise ValueError("MMMU adapter permits multiple-choice answers only")
        split = manifest.get("split") if isinstance(manifest, dict) else None
        strict_custody = manifest.get("schema_version") == "ember-restart-benchmark-custody-v1" or "scorer" in manifest
        frozen_protocol_sha256, scorer = verify_frozen_scorer(manifest, arguments.mmmu_root)
        if not isinstance(split, dict) or manifest.get("benchmark_id") != "MMMU" or manifest.get("benchmark_version") != benchmark.get("version") or split.get("name") != "validation" or split.get("answer_dictionary_sha256") != sha256(answer_bytes) or benchmark.get("split_sha256") != sha256(answer_bytes) or benchmark.get("protocol_sha256") != frozen_protocol_sha256:
            raise ValueError("frozen MMMU custody does not bind canonical predictions")
        image_materialization = manifest.get("image_input_materialization")
        if image_materialization is not None:
            if not isinstance(image_materialization, dict) or arguments.frozen_image_inputs is None:
                raise ValueError("frozen MMMU image input receipt is required")
            image_bytes = arguments.frozen_image_inputs.read_bytes()
            image_receipt = json.loads(image_bytes.decode("utf-8"))
            image_rows = image_receipt.get("rows") if isinstance(image_receipt, dict) else None
            if image_materialization.get("artifact_sha256") != sha256(image_bytes) or image_receipt.get("schema_version") != "ember-restart-mmmu-image-input-freeze-v1" or image_receipt.get("result") != "PREFLIGHT_ONLY" or image_receipt.get("benchmark_id") != "MMMU" or not isinstance(image_rows, list) or image_receipt.get("row_count") != len(image_rows):
                raise ValueError("invalid frozen MMMU image input receipt")
            expected_inputs = {}
            for row in image_rows:
                if not isinstance(row, dict) or set(row) != {"id", "image_sha256s", "input_sha256"} or not isinstance(row.get("id"), str) or not row["id"] or not isinstance(row.get("image_sha256s"), list) or not row["image_sha256s"] or not all(isinstance(value, str) and len(value) == 64 for value in row["image_sha256s"]) or not isinstance(row.get("input_sha256"), str) or len(row["input_sha256"]) != 64 or row["id"] in expected_inputs:
                    raise ValueError("invalid frozen MMMU image input receipt")
                expected_inputs[row["id"]] = row["input_sha256"]
            observed_inputs = {row["id"]: row["input_sha256"] for row in envelope["rows"]}
            if observed_inputs != expected_inputs:
                raise ValueError("canonical MMMU predictions do not bind frozen image inputs")
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as error:
        parser.error(f"invalid MMMU evaluator inputs: {error}")
    if answers.keys() != converted.keys():
        parser.error("MMMU predictions must exactly cover frozen answer ids")
    if not scorer.is_file():
        parser.error("cached MMMU scorer selected by custody is required")
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=arguments.canonical_predictions.parent, prefix=arguments.canonical_predictions.name + ".", suffix=".mmmu.tmp", delete=False) as handle:
        json.dump(converted, handle, sort_keys=True)
        temporary = Path(handle.name)
    with tempfile.NamedTemporaryFile("wb", dir=arguments.answers.parent, prefix=arguments.answers.name + ".", suffix=".mmmu.answers.tmp", delete=False) as handle:
        handle.write(answer_bytes)
        answer_snapshot = Path(handle.name)
    scorer_stage = None
    try:
        scorer_stage = Path(tempfile.mkdtemp(dir=arguments.answers.parent, prefix=".mmmu-scorer-"))
        scorer_snapshot = scorer_stage / scorer.name
        scorer_bytes = scorer.read_bytes()
        scorer_snapshot.write_bytes(scorer_bytes)
        expected_scorer_sha = manifest.get("scorer", {}).get("sha256") if isinstance(manifest.get("scorer"), dict) else sha256(scorer_bytes)
        if sha256(scorer_bytes) != expected_scorer_sha:
            parser.error("MMMU scorer changed after custody verification")
        run = subprocess.run([sys.executable, str(scorer_snapshot), "--output_path", str(temporary), "--answer_path", str(answer_snapshot)], cwd=scorer_stage, text=True, capture_output=True, timeout=arguments.timeout_seconds, check=False)
    except subprocess.TimeoutExpired:
        parser.error("MMMU scorer timed out")
    finally:
        temporary.unlink(missing_ok=True)
        answer_snapshot.unlink(missing_ok=True)
        if scorer_stage is not None:
            import shutil
            shutil.rmtree(scorer_stage, ignore_errors=True)
    if run.returncode != 0:
        parser.error(f"MMMU scorer failed: {run.stderr.strip()}")
    try:
        aggregate = ast.literal_eval(run.stdout.strip().splitlines()[-1])
        overall = aggregate["Overall"]
        sample_count = int(overall["num"])
        accuracy = float(overall["acc"])
    except (ValueError, SyntaxError, KeyError, IndexError, TypeError):
        parser.error("MMMU scorer returned an invalid aggregate")
    if sample_count <= 0 or sample_count != len(converted):
        parser.error("MMMU scorer did not cover the frozen prediction set")
    payload = {"result": "PREFLIGHT_ONLY" if strict_custody else "SELFTEST", "claim_status": "NON_ADMISSIBLE_FROZEN_MMMU_SCORER" if strict_custody else "SELFTEST_ONLY_LEGACY_MMMU_CUSTODY", "metrics": {"accuracy": accuracy}, "sample_count": sample_count, "criterion_id": "ember-3b-image-capability-v1", "criterion_result": "FAILED", "benchmark_id": envelope["benchmark"]["id"], "benchmark_version": envelope["benchmark"]["version"], "split_sha256": envelope["benchmark"]["split_sha256"], "protocol_sha256": envelope["benchmark"]["protocol_sha256"], "checkpoint_manifest_sha256": envelope["checkpoint_manifest_sha256"], "model_config_sha256": envelope["model_config_sha256"], "predictions_sha256": sha256(prediction_bytes), "answers_sha256": sha256(answer_bytes), "frozen_mmmu_manifest_sha256": sha256(manifest_bytes), "upstream": "MMMU exact multiple-choice local scorer bound to canonical predictions"}
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