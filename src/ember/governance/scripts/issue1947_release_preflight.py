#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Fail-closed identity preflight for the three E-RELEASE execution tiers."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


TIER_ROLES = {
    "pr": "mechanics_only",
    "scheduled": "family_smoke",
    "release": "full_matrix",
}
TIER_POLICIES = {
    "pr": {
        "triggers": ["pull_request_paths_filtered", "workflow_dispatch"],
        "runner_label": "ubuntu-latest",
        "timeout_minutes": 20,
        "artifact_retention_days": 30,
    },
    "scheduled": {
        "triggers": ["schedule:23 10 * * *", "workflow_dispatch"],
        "runner_label": "ubuntu-latest",
        "timeout_minutes": 45,
        "artifact_retention_days": 30,
    },
    "release": {
        "triggers": ["workflow_dispatch"],
        "runner_label": "ubuntu-latest",
        "windows_loader_smoke_runner": "windows-latest",
        "windows_loader_smoke_timeout_minutes": 25,
        "timeout_minutes": 60,
        "artifact_retention_days": 90,
    },
}
ALLOWED_HOSTED_RUNNERS = {"ubuntu-latest", "windows-latest"}
PROTECTED_MATRIX_ROW_IDS = (
    "E-MATRIX-TEXT-LANGUAGE",
    "E-MATRIX-IMAGE",
    "E-MATRIX-AUDIO",
    "E-MATRIX-IMAGE-TEXT",
    "E-MATRIX-AUDIO-TEXT",
    "E-MATRIX-IMAGE-AUDIO-TEXT",
    "E-MATRIX-REASONING",
    "E-MATRIX-TOOL-USE",
    "E-MATRIX-ROUTING-PATHWAY",
)


class ReleasePreflightRefusal(ValueError):
    """A named E-RELEASE preflight invariant was not satisfied."""


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _require_sha(label: str, value: object) -> str:
    if not isinstance(value, str) or len(value) != 64 or value != value.lower():
        raise ReleasePreflightRefusal(f"INVALID_SHA256:{label}")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ReleasePreflightRefusal(f"INVALID_SHA256:{label}") from exc
    return value


def _verify_binding(label: str, binding: object) -> dict[str, Any]:
    if not isinstance(binding, dict):
        raise ReleasePreflightRefusal(f"INVALID_BINDING:{label}")
    raw_path = binding.get("path")
    if not isinstance(raw_path, str) or not raw_path:
        raise ReleasePreflightRefusal(f"MISSING_PATH:{label}")
    path = Path(raw_path)
    if not path.is_file():
        raise ReleasePreflightRefusal(f"MISSING_INPUT:{label}")
    expected = _require_sha(f"{label}.raw_sha256", binding.get("raw_sha256"))
    raw = path.read_bytes()
    actual = _sha(raw)
    if actual != expected:
        raise ReleasePreflightRefusal(f"RAW_HASH_DRIFT:{label}")
    return {"path": str(path), "bytes": len(raw), "raw_sha256": actual}


def _verify_self_hashed_json(
    label: str,
    binding: object,
    *,
    schema_version: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    normalized = _verify_binding(label, binding)
    try:
        payload = json.loads(Path(normalized["path"]).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReleasePreflightRefusal(f"INVALID_JSON:{label}") from exc
    if not isinstance(payload, dict):
        raise ReleasePreflightRefusal(f"INVALID_JSON_OBJECT:{label}")
    if payload.get("schema_version") != schema_version:
        raise ReleasePreflightRefusal(f"SCHEMA_DRIFT:{label}")
    claimed_self = _require_sha(f"{label}.self_sha256", payload.get("self_sha256"))
    self_payload = dict(payload)
    self_payload.pop("self_sha256")
    if _sha(_canonical(self_payload)) != claimed_self:
        raise ReleasePreflightRefusal(f"SELF_HASH_DRIFT:{label}")
    normalized["self_sha256"] = claimed_self
    normalized["schema_version"] = schema_version
    return normalized, payload


def _verify_designation(
    designation: object,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    if not isinstance(designation, dict) or designation.get("result") != "DESIGNATED":
        raise ReleasePreflightRefusal("CHECKPOINT_NOT_DESIGNATED")
    if designation.get("schema_version") != "ember-issue1947-release-candidate-checkpoint-designation-v1":
        raise ReleasePreflightRefusal("DESIGNATION_SCHEMA_DRIFT")
    claimed_self = _require_sha("designation.self_sha256", designation.get("self_sha256"))
    self_payload = dict(designation)
    self_payload.pop("self_sha256")
    if _sha(_canonical(self_payload)) != claimed_self:
        raise ReleasePreflightRefusal("SELF_HASH_DRIFT:designation")

    authority = designation.get("designation_authority")
    if not isinstance(authority, dict):
        raise ReleasePreflightRefusal("DESIGNATION_AUTHORITY_NOT_GRANTED")
    mail_id = authority.get("integrator_mail_id")
    if (
        authority.get("verdict") != "DESIGNATED"
        or not isinstance(mail_id, int)
        or isinstance(mail_id, bool)
        or mail_id <= 0
    ):
        raise ReleasePreflightRefusal("DESIGNATION_AUTHORITY_NOT_GRANTED")

    raw_custody = designation.get("candidate_custody")
    if not isinstance(raw_custody, str) or not raw_custody:
        raise ReleasePreflightRefusal("MISSING_CHECKPOINT_CUSTODY")
    custody = Path(raw_custody)
    if not custody.is_dir():
        raise ReleasePreflightRefusal("MISSING_CHECKPOINT_CUSTODY")
    resolved_custody = custody.resolve()

    def governed_path(label: str, relative: object) -> Path:
        if not isinstance(relative, str) or not relative:
            raise ReleasePreflightRefusal(f"MISSING_PATH:{label}")
        rel = Path(relative)
        if rel.is_absolute():
            raise ReleasePreflightRefusal(f"CHECKPOINT_PATH_ESCAPE:{label}")
        candidate = (resolved_custody / rel).resolve()
        try:
            candidate.relative_to(resolved_custody)
        except ValueError as exc:
            raise ReleasePreflightRefusal(f"CHECKPOINT_PATH_ESCAPE:{label}") from exc
        return candidate

    def checkpoint_binding(label: str, binding: object) -> dict[str, Any]:
        if not isinstance(binding, dict):
            raise ReleasePreflightRefusal(f"INVALID_BINDING:{label}")
        path = governed_path(label, binding.get("path"))
        normalized = _verify_binding(
            label,
            {"path": str(path), "raw_sha256": binding.get("raw_sha256")},
        )
        expected_bytes = binding.get("bytes")
        if (
            not isinstance(expected_bytes, int)
            or isinstance(expected_bytes, bool)
            or expected_bytes < 0
            or normalized["bytes"] != expected_bytes
        ):
            raise ReleasePreflightRefusal(f"BYTE_COUNT_DRIFT:{label}")
        normalized["relative_path"] = str(binding["path"])
        return normalized

    checkpoint = checkpoint_binding("checkpoint_manifest", designation.get("manifest"))
    shard_specs = designation.get("shards")
    if not isinstance(shard_specs, list) or not shard_specs:
        raise ReleasePreflightRefusal("MISSING_CHECKPOINT_SHARDS")
    shards = [
        checkpoint_binding(f"checkpoint_shards[{index}]", binding)
        for index, binding in enumerate(shard_specs)
    ]
    relative_paths = [row["relative_path"] for row in shards]
    if len(relative_paths) != len(set(relative_paths)):
        raise ReleasePreflightRefusal("DUPLICATE_CHECKPOINT_SHARD")

    verification = designation.get("byte_verification")
    if not isinstance(verification, dict) or any(
        (
            verification.get("manifest_match") is not True,
            verification.get("shards_verified") != len(shards),
            verification.get("shards_matching_manifest") != len(shards),
            verification.get("missing_shards") != 0,
            verification.get("mismatched_shards") != 0,
        )
    ):
        raise ReleasePreflightRefusal("DESIGNATION_BYTE_VERIFICATION_DRIFT")
    normalized_authority = {"integrator_mail_id": mail_id, "verdict": "DESIGNATED"}
    checkpoint["designation_self_sha256"] = claimed_self
    return checkpoint, shards, normalized_authority


def build_release_preflight(
    designation: object,
    composition_terminal_binding: object,
    matrix_binding: object,
    analysis_binding: object,
    tiers: object,
) -> dict[str, Any]:
    checkpoint, checkpoint_shards, designation_authority = _verify_designation(designation)
    composition, composition_payload = _verify_self_hashed_json(
        "composition_terminal",
        composition_terminal_binding,
        schema_version="c2-e-composition-statistics-v1",
    )
    if composition_payload.get("result") != "PASS" or composition_payload.get("issue") != 2055:
        raise ReleasePreflightRefusal("COMPOSITION_TERMINAL_NOT_PASS")
    recompute = composition_payload.get("independent_recomputation")
    if not isinstance(recompute, dict) or recompute.get("result") != "PASS":
        raise ReleasePreflightRefusal("COMPOSITION_RECOMPUTE_NOT_PASS")
    _require_sha("composition.recompute.raw", recompute.get("receipt_raw_sha256"))
    _require_sha("composition.recompute.self", recompute.get("receipt_self_sha256"))
    assert isinstance(composition_terminal_binding, dict)
    recompute_receipt, recompute_payload = _verify_self_hashed_json(
        "composition_recompute",
        composition_terminal_binding.get("independent_recompute"),
        schema_version="ember-issue2055-independent-recompute-v1",
    )
    if recompute_payload.get("result") != "PASS":
        raise ReleasePreflightRefusal("COMPOSITION_RECOMPUTE_NOT_PASS")
    if (
        recompute_receipt["raw_sha256"] != recompute.get("receipt_raw_sha256")
        or recompute_receipt["self_sha256"] != recompute.get("receipt_self_sha256")
    ):
        raise ReleasePreflightRefusal("COMPOSITION_RECOMPUTE_BINDING_DRIFT")
    controls = composition_payload.get("control_summary")
    if not isinstance(controls, dict) or any(
        controls.get(key) != 8
        for key in (
            "positive_passed",
            "positive_total",
            "planted_refused_as_named",
            "planted_total",
        )
    ):
        raise ReleasePreflightRefusal("COMPOSITION_CONTROLS_NOT_PASS")
    matrix, matrix_payload = _verify_self_hashed_json(
        "matrix",
        matrix_binding,
        schema_version="ember-issue1964-current-protected-row-census-v1",
    )
    if matrix_payload.get("result") != "PASS":
        raise ReleasePreflightRefusal("MATRIX_NOT_PASS")
    matrix_rows = matrix_payload.get("rows")
    row_ids = (
        tuple(row.get("row_id") for row in matrix_rows)
        if isinstance(matrix_rows, list) and all(isinstance(row, dict) for row in matrix_rows)
        else ()
    )
    totality = matrix_payload.get("totality")
    if (
        row_ids != PROTECTED_MATRIX_ROW_IDS
        or not isinstance(totality, dict)
        or totality.get("census_family_count") != len(PROTECTED_MATRIX_ROW_IDS)
        or totality.get("required_family_count") != len(PROTECTED_MATRIX_ROW_IDS)
        or totality.get("duplicate_contract_count") != 0
        or totality.get("duplicate_family_count") != 0
        or totality.get("omitted_contract_ids") != []
    ):
        raise ReleasePreflightRefusal("MATRIX_TOTALITY_DRIFT")
    matrix["ordered_row_ids"] = list(row_ids)
    analysis, analysis_payload = _verify_self_hashed_json(
        "analysis",
        analysis_binding,
        schema_version="ember-issue2055-prospective-analysis-manifest-v2",
    )
    if analysis_payload.get("status") != "FROZEN_BEFORE_TREATMENT_OUTPUTS":
        raise ReleasePreflightRefusal("ANALYSIS_NOT_FROZEN")
    analysis_authority = analysis_payload.get("authority")
    frozen_population = analysis_payload.get("frozen_population")
    if (
        not isinstance(analysis_authority, dict)
        or not isinstance(frozen_population, dict)
        or analysis_authority.get("protected_row_census_raw_sha256") != matrix["raw_sha256"]
        or analysis_authority.get("protected_row_census_self_sha256") != matrix["self_sha256"]
        or frozen_population.get("checkpoint_manifest_sha256") != checkpoint["raw_sha256"]
    ):
        raise ReleasePreflightRefusal("ANALYSIS_BINDING_DRIFT")
    if not isinstance(tiers, dict):
        raise ReleasePreflightRefusal("INVALID_TIERS")
    unexpected = sorted(set(tiers) - set(TIER_ROLES))
    if unexpected:
        raise ReleasePreflightRefusal(f"UNEXPECTED_TIER:{unexpected[0]}")

    tier_rows: list[dict[str, Any]] = []
    for tier, role in TIER_ROLES.items():
        if tier not in tiers:
            raise ReleasePreflightRefusal(f"MISSING_TIER:{tier}")
        spec = tiers[tier]
        if not isinstance(spec, dict):
            raise ReleasePreflightRefusal(f"INVALID_TIER:{tier}")
        if spec.get("role") != role:
            raise ReleasePreflightRefusal(f"TIER_ROLE_DRIFT:{tier}")
        if spec.get("fail_closed_missing_input") is not True:
            raise ReleasePreflightRefusal(f"FAIL_OPEN_TIER:{tier}")
        if spec.get("checkpoint_manifest_raw_sha256") != checkpoint["raw_sha256"]:
            raise ReleasePreflightRefusal(f"CHECKPOINT_IDENTITY_DRIFT:{tier}")
        timeout = spec.get("timeout_minutes")
        retention = spec.get("artifact_retention_days")
        policy = TIER_POLICIES[tier]
        if spec.get("triggers") != policy["triggers"]:
            raise ReleasePreflightRefusal(f"TRIGGER_DRIFT:{tier}")
        runner_label = spec.get("runner_label")
        if runner_label not in ALLOWED_HOSTED_RUNNERS or runner_label != policy["runner_label"]:
            raise ReleasePreflightRefusal(f"NON_HOSTED_RUNNER_LABEL:{tier}")
        if timeout != policy["timeout_minutes"] or retention != policy["artifact_retention_days"]:
            raise ReleasePreflightRefusal(f"INVALID_TIMEOUT_OR_ARTIFACT_RETENTION:{tier}")
        if tier == "release" and (
            spec.get("windows_loader_smoke_runner") != policy["windows_loader_smoke_runner"]
            or spec.get("windows_loader_smoke_timeout_minutes")
            != policy["windows_loader_smoke_timeout_minutes"]
        ):
            raise ReleasePreflightRefusal("NON_HOSTED_RUNNER_LABEL:release.windows_loader_smoke")
        workflow = _verify_binding(f"{tier}.workflow", spec.get("workflow"))
        runner = _verify_binding(f"{tier}.runner", spec.get("runner"))
        protected = spec.get("protected_inputs")
        if not isinstance(protected, list) or not protected:
            raise ReleasePreflightRefusal(f"MISSING_PROTECTED_INPUT:{tier}")
        protected_rows = [
            _verify_binding(f"{tier}.protected_inputs[{index}]", binding)
            for index, binding in enumerate(protected)
        ]
        tier_rows.append(
            {
                "tier": tier,
                "role": role,
                "workflow": workflow,
                "runner": runner,
                "protected_inputs": protected_rows,
                "checkpoint_manifest_raw_sha256": checkpoint["raw_sha256"],
                "fail_closed_missing_input": True,
                "timeout_minutes": timeout,
                "artifact_retention_days": retention,
                "triggers": list(policy["triggers"]),
                "runner_label": runner_label,
            }
        )

    receipt: dict[str, Any] = {
        "schema_version": "ember-issue1947-release-tier-preflight-v1",
        "result": "PASS",
        "checkpoint_manifest": checkpoint,
        "checkpoint_shards": checkpoint_shards,
        "designation_authority": designation_authority,
        "composition_terminal": composition,
        "composition_recompute": recompute_receipt,
        "matrix": matrix,
        "analysis": analysis,
        "tiers": tier_rows,
        "claim_boundary": "IDENTITY_AND_INPUT_PREFLIGHT_ONLY; NO_WORKFLOW_EXECUTION EVALUATION CERT ISSUE_OR_GOAL_CREDIT",
    }
    receipt["self_sha256"] = _sha(_canonical(receipt))
    return receipt


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--designation", type=Path, required=True)
    parser.add_argument("--composition-terminal-binding", type=Path, required=True)
    parser.add_argument("--matrix-binding", type=Path, required=True)
    parser.add_argument("--analysis-binding", type=Path, required=True)
    parser.add_argument("--tiers", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    if args.receipt.exists():
        raise SystemExit("REFUSED_RECEIPT_EXISTS")
    receipt = build_release_preflight(
        _load(args.designation),
        _load(args.composition_terminal_binding),
        _load(args.matrix_binding),
        _load(args.analysis_binding),
        _load(args.tiers),
    )
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": receipt["result"], "self_sha256": receipt["self_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
