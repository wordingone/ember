# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Packet B2 tests for the certified dense A1 execution family."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import struct
import sys
import tempfile
from unittest import mock

import pytest

from . import test_certified_train_launch as launch_fixtures


ROOT = Path(__file__).resolve().parents[2]
A1_FAMILY = "dense-tier1-full-state-adamw-cpu-offload-v1"
TIER2_FAMILY = "dense-tier2-owned-q-galore-v1"


def _load_a1_execution():
    tools = ROOT / "tools" / "ember-restart-3b"
    inserted = str(tools) not in sys.path
    if inserted:
        sys.path.insert(0, str(tools))
    try:
        spec = importlib.util.spec_from_file_location(
            "a1_execution_under_test", tools / "a1_execution.py"
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        if inserted:
            sys.path.remove(str(tools))


def _canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _canonical_sha(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _matched_a3_self_digest_sha(value: dict[str, object]) -> str:
    # Dedicated to the matched-A3 run receipt fixture: matches the module's
    # `_matched_a3_self_digest_sha256` (fix(training): align matched-A3
    # self-digest convention, #1464) -- compact JSON, no trailing newline,
    # ensure_ascii False -- NOT `_canonical_sha` above, which stays
    # WITH-newline for shard_sequence_sha256/schedule_sha256 (self-consistent
    # internal comparisons the module's own unchanged `_canonical_sha256`
    # still expects).
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _with_self_digest(value: dict[str, object]) -> dict[str, object]:
    value = dict(value)
    value["receipt_sha256"] = _matched_a3_self_digest_sha(value)
    return value


def _resource_preflight_receipt(parameter_count: int = 3_839_344_640) -> dict[str, object]:
    model = parameter_count * 2
    optimizer = parameter_count * 12
    checkpoint = model + optimizer
    gib = 1024**3
    return {
        "schema_version": "ember-a1-resource-preflight-v1",
        "status": "PASS",
        "parameter_count": parameter_count,
        "model_bytes": model,
        "gradient_bytes": model,
        "cpu_fp32_optimizer_bytes": optimizer,
        "checkpoint_payload_floor_bytes": checkpoint,
        "transient_checkpoint_bytes": 4 * gib,
        "host_commit_reserve_bytes": 8 * gib,
        "gpu_free_margin_bytes": 4 * gib,
        "b_custody_floor_bytes": 8 * gib,
        "available_commit_bytes": optimizer + 12 * gib,
        "device_free_bytes": 24 * gib,
        "custody_free_bytes": checkpoint + 16 * gib,
        "required_commit_bytes": optimizer + 12 * gib,
        "required_device_bytes": 2 * model + 4 * gib,
        "required_custody_bytes": checkpoint + 8 * gib,
        "governor": {"vram_fraction": 0.85, "free_gb": 24.0, "total_gb": 24.0, "margin_gb": 4.0},
        # #1464: the a1-dense-tier1 route now attaches the canonical disk
        # budget runner authority alongside the governor receipt; this
        # fixture pins a closed, schema-valid shape (not the real
        # canonical_disk_budget_runner_authority() output) since these
        # finalize_tier1_run/run_dense_a1 tests never exercise the CLI's
        # env-bound startup assertion.
        "canonical_runner": {
            "schema_version": "ember-canonical-disk-budget-startup-v1",
            "assertion_sha256": "a" * 64,
            "cache_bindings_sha256": "b" * 64,
        },
    }


def _checkpoint_identity(
    authority: dict[str, object], *, source_commit: str, certified_launch_sha256: str
) -> dict[str, object]:
    comparison = authority["comparison"]
    matched_path = authority["comparison_path"].parent / comparison["matched_a3_run"]["path"]
    matched = json.loads(matched_path.read_text(encoding="utf-8"))
    return {
        "comparison_id": comparison["comparison_id"],
        "matched_identity": matched["identity"],
        "config_sha256": "563331b746619788f01900f4d951df29e4c6549c937a4662bac76234f5d71edc",
        "source_commit": source_commit,
        "certified_launch_sha256": certified_launch_sha256,
        "tier": "TIER_1",
        "mechanism": "FULL_STATE_ADAMW_CPU_OFFLOAD",
        "predecessor": None,
    }


def _declare_a1_route(paths: dict[str, Path]) -> None:
    run_spec = json.loads(paths["run_spec"].read_text(encoding="utf-8"))
    run_spec.update(
        {
            "a1_family": "dense-tier1-full-state-adamw-cpu-offload-v1",
            "a1_tier": "TIER_1",
            "a1_mechanism": "FULL_STATE_ADAMW_CPU_OFFLOAD",
            "a1_token_shards_receipt": "missing-token-shards-receipt.json",
            "a1_shards_root": "missing-shards-root",
            "a1_comparison_authority": "missing-comparison-authority.json",
            "a1_comparison_authority_sha256": "a" * 64,
            "a1_sequence_length": 8,
            "a1_checkpoint_interval": 1,
            "a1_telemetry_path": str(paths["custody_root"] / "a1-telemetry.jsonl"),
        }
    )
    launch_fixtures.write_json(paths["run_spec"], run_spec)
    launch_fixtures._write_custody_sidecars(paths)


def _install_valid_a1_authority(paths: dict[str, Path]) -> dict[str, object]:
    repo = paths["repo"]
    tools = repo / "tools" / "ember-restart-3b"
    thresholds = repo / "docs" / "spec"
    tokenizer_dir = repo / "tokenizer"
    receipt_dir = repo / "receipts" / "ember-restart-3b"
    for directory in (tools, thresholds, tokenizer_dir, receipt_dir):
        directory.mkdir(parents=True, exist_ok=True)
    config_path = tools / "ember-restart-3b-a1.json"
    shutil.copyfile(ROOT / "tools" / "ember-restart-3b" / "ember-restart-3b-a1.json", config_path)
    shutil.copyfile(
        ROOT / "docs" / "spec" / "ember02-preregistration-thresholds-v1.json",
        thresholds / "ember02-preregistration-thresholds-v1.json",
    )
    tokenizer_path = tokenizer_dir / "tokenizer.json"
    launch_fixtures.write_json(
        tokenizer_path,
        {"model": {"vocab": [f"token-{index}" for index in range(64)]}},
    )
    tokenizer_sha = hashlib.sha256(tokenizer_path.read_bytes()).hexdigest()
    shards_root = paths["custody_root"] / "a1-shards"
    shards_root.mkdir()
    shard_path = shards_root / "train-00000.bin"
    shard_path.write_bytes(struct.pack("<17H", *range(17)))
    shards = [
        {
            "name": shard_path.name,
            "sha256": hashlib.sha256(shard_path.read_bytes()).hexdigest(),
            "n_tokens": 17,
        }
    ]
    token_receipt_path = receipt_dir / "token-shards-v0.json"
    launch_fixtures.write_json(
        token_receipt_path,
        {
            "ticket": "TOKEN-SHARDS-V0",
            "premises": {
                "tokenizer_json": {
                    "path": "tokenizer/tokenizer.json",
                    "sha256": tokenizer_sha,
                }
            },
            "shards": shards,
            "total_stream_tokens": 17,
        },
    )
    token_receipt_sha = hashlib.sha256(token_receipt_path.read_bytes()).hexdigest()
    schedule = {
        "schema_version": "ember-a1-schedule-v1",
        "optimizer_steps": 1,
        "sequence_length": 8,
        "checkpoint_interval": 1,
        "config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
    }
    identity = {
        "comparison_id": "r1-e8-a1-vs-a3",
        "corpus_authority_sha256": token_receipt_sha,
        "shard_sequence_sha256": _canonical_sha(shards),
        "tokenizer_sha256": tokenizer_sha,
        "seed": 83,
        "cursor_start": {"global_step": 0, "record_index": 0, "tokens_seen": 0},
        "schedule_sha256": _canonical_sha(schedule),
        "genesis_sha256": "5" * 64,
    }
    a3_run = _with_self_digest(
        {
            "schema_version": "ember02-r1-e8-run-v1",
            "arm_id": "A3",
            "tier": "A3",
            "mechanism": "role-prior-sparse",
            "status": "TERMINAL",
            "certified_launch_sha256": "6" * 64,
            "source_commit": launch_fixtures.SHA,
            "architecture_revision": "ember-sparse-3b-v2",
            "parameter_count": 3_839_161_856,
            "active_parameter_count": 1_020_589_568,
            "contains_router_or_experts": True,
            "optimizer": {
                "kind": "AdamW",
                "full_state": True,
                "cpu_offload": False,
                "covered_parameter_count": 3_839_161_856,
            },
            "identity": identity,
            "energy_sample_coverage": "1.000000000000",
            "checkpoint_sha256": "7" * 64,
        }
    )
    a3_path = paths["custody_root"] / "matched-a3-run.json"
    launch_fixtures.write_json(a3_path, a3_run)
    comparison = {
        "schema_version": "ember-a1-comparison-authority-v1",
        "comparison_id": "r1-e8-a1-vs-a3",
        "matched_a3_run": {
            "path": a3_path.name,
            "sha256": hashlib.sha256(a3_path.read_bytes()).hexdigest(),
        },
        "token_shards_receipt_sha256": token_receipt_sha,
        "shard_sequence_sha256": _canonical_sha(shards),
        "tokenizer_sha256": tokenizer_sha,
        "seed": 83,
        "cursor_start": {"global_step": 0, "record_index": 0, "tokens_seen": 0},
        "schedule_sha256": _canonical_sha(schedule),
        "genesis_authority_sha256": "5" * 64,
    }
    comparison_path = paths["custody_root"] / "a1-comparison-authority.json"
    launch_fixtures.write_json(comparison_path, comparison)

    launch_fixtures.rewrite_certificate(
        paths,
        lambda certificate: (
            certificate["execution_scope"].update(
                {
                    "allowed_a1_families": [A1_FAMILY],
                    "a1_host_commit_reserve_gib": 8,
                    "a1_gpu_free_margin_gib": 4,
                    "a1_b_custody_floor_gib": 8,
                }
            ),
            certificate.__setitem__(
                "config_sha256", hashlib.sha256(config_path.read_bytes()).hexdigest()
            ),
            certificate.__setitem__("tokenizer_sha256", tokenizer_sha),
            certificate.__setitem__("input_authority_sha256", token_receipt_sha),
        ),
    )
    run_spec = json.loads(paths["run_spec"].read_text(encoding="utf-8"))
    run_spec.update(
        {
            "a1_family": A1_FAMILY,
            "a1_tier": "TIER_1",
            "a1_mechanism": "FULL_STATE_ADAMW_CPU_OFFLOAD",
            "a1_token_shards_receipt": str(token_receipt_path.relative_to(repo)),
            "a1_shards_root": str(shards_root),
            "a1_comparison_authority": str(comparison_path),
            "a1_comparison_authority_sha256": hashlib.sha256(
                comparison_path.read_bytes()
            ).hexdigest(),
            "a1_sequence_length": 8,
            "a1_checkpoint_interval": 1,
            "a1_telemetry_path": str(paths["custody_root"] / "a1-telemetry.jsonl"),
        }
    )
    launch_fixtures.write_json(paths["run_spec"], run_spec)
    launch_fixtures._write_custody_sidecars(paths)
    return {
        "comparison": comparison,
        "comparison_path": comparison_path,
        "token_receipt_path": token_receipt_path,
        "shards_root": shards_root,
        "tokenizer_path": tokenizer_path,
    }


def _install_valid_tier2_authority(paths: dict[str, Path]) -> dict[str, Path]:
    _install_valid_a1_authority(paths)
    contract = paths["repo"] / "tools" / "ember-restart-3b" / "ember-restart-3b-a1-tier2.json"
    shutil.copyfile(ROOT / "tools" / "ember-restart-3b" / "ember-restart-3b-a1-tier2.json", contract)
    liveness = {
        "schema_version": "ember02-r1-e8-liveness-v1",
        "thresholds_sha256": "12c83ca9ac90f85d5e8c0ce2c8156ac0c2cf9695929b211971ee277582a5eeb5",
        "verdict": "FALLBACK_REQUIRED",
        "a1_series": {"path": "a1-live-series.json", "sha256": "1" * 64},
        "a3_series": {"path": "a3-live-series.json", "sha256": "2" * 64},
        "tier1_run": {"path": "tier1-run.json", "sha256": "3" * 64},
        "a3_run": {"path": "a3-run.json", "sha256": "4" * 64},
        "charged_budget_contract": {"path": "charged-budget-contract.json", "sha256": "5" * 64},
        "measurements": {
            "a1_joules_per_token": "1", "a1_tokens_per_second": "1",
            "a3_joules_per_token": "1", "a3_tokens_per_second": "1",
            "equal_budget_ratio": "0.02",
        },
    }
    liveness["receipt_sha256"] = hashlib.sha256(
        json.dumps(liveness, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    liveness_path = paths["custody_root"] / "a1-e8-liveness.json"
    launch_fixtures.write_json(liveness_path, liveness)
    launch_fixtures.rewrite_certificate(
        paths,
        lambda certificate: certificate["execution_scope"].update(
            {"allowed_a1_families": [TIER2_FAMILY]}
        ),
    )
    run_spec = json.loads(paths["run_spec"].read_text(encoding="utf-8"))
    run_spec.update({
        "a1_family": TIER2_FAMILY,
        "a1_tier": "TIER_2",
        "a1_mechanism": "OWNED_Q_GALORE_PROJECTED_GRADIENT",
        "a1_tier2_contract": str(contract),
        "a1_tier2_contract_sha256": hashlib.sha256(contract.read_bytes()).hexdigest(),
        "a1_liveness_receipt": str(liveness_path),
        "a1_liveness_receipt_sha256": hashlib.sha256(liveness_path.read_bytes()).hexdigest(),
    })
    launch_fixtures.write_json(paths["run_spec"], run_spec)
    launch_fixtures._write_custody_sidecars(paths)
    return {"contract": contract, "liveness": liveness_path}


def test_certificate_without_a1_family_refuses_before_opening_route_inputs() -> None:
    """Removing certificate family authority must fail before route input I/O."""

    module = launch_fixtures.load_module()
    with tempfile.TemporaryDirectory(dir="B:/tmp") as directory:
        paths = launch_fixtures.write_valid_bundle(Path(directory))
        _declare_a1_route(paths)
        with mock.patch.object(module, "read_current_master", return_value=launch_fixtures.SHA):
            with pytest.raises(ValueError, match="declares no allowed_a1_families"):
                module.validate_certified_request(
                    paths["repo"],
                    paths["certificate"],
                    paths["ledger"],
                    paths["run_spec"],
                )


def test_duplicate_certificate_a1_family_is_refused() -> None:
    """A duplicate serialized family must not collapse silently through set()."""

    module = launch_fixtures.load_module()
    family = "dense-tier1-full-state-adamw-cpu-offload-v1"
    with pytest.raises(ValueError, match="globally unique"):
        module._authorized_a1_families(
            {"allowed_a1_families": [family, family]}
        )


def test_valid_a1_route_projects_a_typed_discriminating_request() -> None:
    """The certified consumer, not argv construction, owns the typed A1 join."""

    module = launch_fixtures.load_module()
    with tempfile.TemporaryDirectory(dir="B:/tmp") as directory:
        paths = launch_fixtures.write_valid_bundle(Path(directory))
        _install_valid_a1_authority(paths)
        with mock.patch.object(module, "read_current_master", return_value=launch_fixtures.SHA):
            launch = module.validate_certified_request(
                paths["repo"], paths["certificate"], paths["ledger"], paths["run_spec"]
            )
    assert launch.a1_family == A1_FAMILY
    assert launch.a1_tier.value == "TIER_1"
    assert launch.a1_mechanism.value == "FULL_STATE_ADAMW_CPU_OFFLOAD"
    assert launch.a1_steps == 1
    assert launch.a1_sequence_length == 8
    assert launch.a1_checkpoint_interval == 1


def test_tier1_host_setup_contract_refuses_before_argv_or_spawn() -> None:
    """Deliberate red: insufficient live commit cannot reach argv or a child."""

    module = launch_fixtures.load_module()
    launch = module.ValidatedLaunch(
        certificate_sha256="1" * 64,
        run_spec_sha256="2" * 64,
        public_master_sha=launch_fixtures.SHA,
        closure_sha256=None,
        artifact_root=Path("artifacts"),
        custody_root=Path("custody"),
        runner_receipt=Path("custody/runner.json"),
        seed=83,
        write_budget_bytes=16 * 1024**3,
        max_records=1,
        max_c_write_gib=0.0,
        max_b_write_gib=16.0,
        a1_family=A1_FAMILY,
        a1_tier=module.A1Tier.TIER_1,
        a1_mechanism=module.A1Mechanism.FULL_STATE_ADAMW_CPU_OFFLOAD,
    )
    with (
        mock.patch.object(
            module,
            "_validate_tier1_host_setup_contract",
            side_effect=RuntimeError("host setup contract refused"),
            create=True,
        ) as contract,
        mock.patch.object(module, "build_runner_argv") as build_argv,
    ):
        with pytest.raises(RuntimeError, match="host setup contract refused"):
            module.execute_validated_launch(Path("repo"), launch)
    contract.assert_called_once_with(launch)
    build_argv.assert_not_called()


def test_tier1_host_setup_contract_executes_real_validator_with_measured_commit() -> None:
    """The live wiring consumes the real profile and validator deterministically."""

    import checkpoint_artifacts

    module = launch_fixtures.load_module()
    launch = module.ValidatedLaunch(
        certificate_sha256="1" * 64,
        run_spec_sha256="2" * 64,
        public_master_sha=launch_fixtures.SHA,
        closure_sha256=None,
        artifact_root=Path("artifacts"),
        custody_root=Path("custody"),
        runner_receipt=Path("custody/runner.json"),
        seed=83,
        write_budget_bytes=16 * 1024**3,
        max_records=1,
        max_c_write_gib=0.0,
        max_b_write_gib=16.0,
        a1_family=A1_FAMILY,
        a1_tier=module.A1Tier.TIER_1,
        a1_mechanism=module.A1Mechanism.FULL_STATE_ADAMW_CPU_OFFLOAD,
    )

    admitted_bytes = 64 * 1024**3
    with mock.patch.object(
        checkpoint_artifacts,
        "available_host_commit_bytes",
        return_value=admitted_bytes,
    ):
        disclosure = module._validate_tier1_host_setup_contract(launch)
    assert disclosure is not None
    assert set(disclosure) == {
        "status",
        "mechanism",
        "required_headroom_bytes",
        "available_commit_bytes",
    }
    assert disclosure["status"] == "PASS"
    assert disclosure["mechanism"] == "dense-a1-full-state-cpu-offload"
    assert disclosure["available_commit_bytes"] == admitted_bytes
    assert disclosure["required_headroom_bytes"] < admitted_bytes

    refused_bytes = 12 * 1024**3
    with (
        mock.patch.object(
            checkpoint_artifacts,
            "available_host_commit_bytes",
            return_value=refused_bytes,
        ),
        pytest.raises(RuntimeError, match=r"only 12\.00 GiB is available") as refusal,
    ):
        module._validate_tier1_host_setup_contract(launch)
    assert refusal.value.available_commit_bytes == refused_bytes


def test_tier2_does_not_inherit_tier1_host_setup_contract() -> None:
    """The elevated host profile belongs only to full-state CPU offload."""

    module = launch_fixtures.load_module()
    launch = module.ValidatedLaunch(
        certificate_sha256="1" * 64,
        run_spec_sha256="2" * 64,
        public_master_sha=launch_fixtures.SHA,
        closure_sha256=None,
        artifact_root=Path("artifacts"),
        custody_root=Path("custody"),
        runner_receipt=Path("custody/runner.json"),
        seed=83,
        write_budget_bytes=16 * 1024**3,
        max_records=1,
        max_c_write_gib=0.0,
        max_b_write_gib=16.0,
        a1_family=TIER2_FAMILY,
        a1_tier=module.A1Tier.TIER_2,
        a1_mechanism=module.A1Mechanism.OWNED_Q_GALORE_PROJECTED_GRADIENT,
    )
    assert module._validate_tier1_host_setup_contract(launch) is None


def test_valid_a1_route_emits_the_distinct_runner_subcommand() -> None:
    module = launch_fixtures.load_module()
    with tempfile.TemporaryDirectory(dir="B:/tmp") as directory:
        paths = launch_fixtures.write_valid_bundle(Path(directory))
        _install_valid_a1_authority(paths)
        with mock.patch.object(module, "read_current_master", return_value=launch_fixtures.SHA):
            launch = module.validate_certified_request(
                paths["repo"], paths["certificate"], paths["ledger"], paths["run_spec"]
            )
        argv = module.build_runner_argv(paths["repo"], launch)
    a1 = argv[argv.index("a1-dense-tier1") :]
    assert a1 == [
        "a1-dense-tier1",
        "--seed", "83",
        "--artifact-root", str(paths["artifact_root"]),
        "--token-shards-receipt", str(launch.a1_token_shards_receipt),
        "--shards-root", str(launch.a1_shards_root),
        "--comparison-authority", str(launch.a1_comparison_authority),
        "--steps", "1",
        "--sequence-length", "8",
        "--checkpoint-interval", "1",
        "--write-budget-gib", "16",
        "--transient-checkpoint-gib", "4",
        "--host-commit-reserve-gib", "8",
        "--gpu-free-margin-gib", "4",
        "--b-custody-floor-gib", "8",
        "--telemetry-path", str(launch.a1_telemetry_path),
        "--telemetry-run-id", launch.run_id,
    ]


def test_valid_tier2_route_requires_ruled_contract_and_liveness_and_is_distinct() -> None:
    module = launch_fixtures.load_module()
    temp_root = Path("B:/tmp/issue1464-tier2-tests")
    temp_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=temp_root) as directory:
        paths = launch_fixtures.write_valid_bundle(Path(directory))
        authority = _install_valid_tier2_authority(paths)
        with mock.patch.object(module, "read_current_master", return_value=launch_fixtures.SHA):
            launch = module.validate_certified_request(
                paths["repo"], paths["certificate"], paths["ledger"], paths["run_spec"]
            )
        argv = module.build_runner_argv(paths["repo"], launch)
    assert launch.a1_tier.value == "TIER_2"
    assert launch.a1_mechanism.value == "OWNED_Q_GALORE_PROJECTED_GRADIENT"
    assert "a1-dense-tier2" in argv
    assert "a1-dense-tier1" not in argv
    assert argv[argv.index("--tier2-contract") + 1] == str(authority["contract"])
    assert argv[argv.index("--tier2-contract-sha256") + 1] == launch.a1_tier2_contract_sha256
    assert argv[argv.index("--liveness-receipt") + 1] == str(authority["liveness"])
    assert argv[argv.index("--liveness-receipt-sha256") + 1] == launch.a1_liveness_receipt_sha256
    with mock.patch.dict(os.environ, {"CUBLAS_WORKSPACE_CONFIG": ":ambient-drift"}):
        child_env = module._certified_child_environment(launch)
    assert child_env["CUBLAS_WORKSPACE_CONFIG"] == ":4096:8"
    assert child_env["EMBER_A1_SOURCE_COMMIT"] == launch.public_master_sha
    assert child_env["EMBER_A1_CERTIFIED_LAUNCH_SHA256"] == launch.run_spec_sha256


def test_tier2_route_refuses_nonfallback_liveness_before_argv() -> None:
    module = launch_fixtures.load_module()
    temp_root = Path("B:/tmp/issue1464-tier2-tests")
    temp_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=temp_root) as directory:
        paths = launch_fixtures.write_valid_bundle(Path(directory))
        authority = _install_valid_tier2_authority(paths)
        liveness = json.loads(authority["liveness"].read_text(encoding="utf-8"))
        liveness["verdict"] = "TIER1_LIVE"
        liveness["receipt_sha256"] = hashlib.sha256(
            json.dumps({k: v for k, v in liveness.items() if k != "receipt_sha256"}, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        launch_fixtures.write_json(authority["liveness"], liveness)
        run_spec = json.loads(paths["run_spec"].read_text(encoding="utf-8"))
        run_spec["a1_liveness_receipt_sha256"] = hashlib.sha256(authority["liveness"].read_bytes()).hexdigest()
        launch_fixtures.write_json(paths["run_spec"], run_spec)
        launch_fixtures._write_custody_sidecars(paths)
        with mock.patch.object(module, "read_current_master", return_value=launch_fixtures.SHA):
            with pytest.raises(ValueError, match="FALLBACK_REQUIRED"):
                module.validate_certified_request(
                    paths["repo"], paths["certificate"], paths["ledger"], paths["run_spec"]
                )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("a1_host_commit_reserve_gib", None),
        ("a1_host_commit_reserve_gib", True),
        ("a1_gpu_free_margin_gib", 0),
        ("a1_b_custody_floor_gib", "8"),
    ],
)
def test_a1_resource_authority_is_closed_typed_and_required(
    field: str, value: object
) -> None:
    module = launch_fixtures.load_module()
    authority = {
        "a1_host_commit_reserve_gib": 8,
        "a1_gpu_free_margin_gib": 4,
        "a1_b_custody_floor_gib": 8,
    }
    if value is None:
        authority.pop(field)
    else:
        authority[field] = value
    with pytest.raises(ValueError, match="A1 resource authority"):
        module._a1_resource_authority(authority)


def test_dense_a1_resource_preflight_refuses_before_output_residue() -> None:
    tools = ROOT / "tools" / "ember-restart-3b"
    inserted = str(tools) not in sys.path
    if inserted:
        sys.path.insert(0, str(tools))
    try:
        import run_vertical_slice

        parameters = 3_839_344_640
        with pytest.raises(MemoryError, match="host commit"):
            run_vertical_slice.dense_a1_resource_preflight(
                parameter_count=parameters,
                write_budget_bytes=64 * 1024**3,
                transient_checkpoint_bytes=4 * 1024**3,
                host_commit_reserve_bytes=8 * 1024**3,
                gpu_free_margin_bytes=4 * 1024**3,
                b_custody_floor_bytes=8 * 1024**3,
                available_commit_bytes=1,
                device_free_bytes=64 * 1024**3,
                custody_free_bytes=128 * 1024**3,
            )
    finally:
        if inserted:
            sys.path.remove(str(tools))


@pytest.mark.parametrize(
    ("coverage", "captured", "meets"),
    [(0.94, 94, False), (0.96, 95, True)],
)
def test_energy_undercoverage_or_inconsistency_mints_no_tier1_run(
    coverage: float, captured: int, meets: bool
) -> None:
    module = _load_a1_execution()
    with tempfile.TemporaryDirectory(dir="B:/tmp") as directory:
        root = Path(directory)
        launch_paths = launch_fixtures.write_valid_bundle(root)
        authority = _install_valid_a1_authority(launch_paths)
        core = {
            "schema_version": module.CORE_SCHEMA,
            "status": "TERMINAL",
            "source_commit": launch_fixtures.SHA,
            "certified_launch_sha256": "8" * 64,
            "parameter_count": 3_839_344_640,
            "optimizer_inventory": {"complete": True},
            "checkpoint_sha256": "9" * 64,
            "checkpoint_identity": _checkpoint_identity(
                authority,
                source_commit=launch_fixtures.SHA,
                certified_launch_sha256="8" * 64,
            ),
            "resource_preflight": _resource_preflight_receipt(),
            "comparison_authority": {
                "path": str(authority["comparison_path"]),
                "sha256": hashlib.sha256(
                    authority["comparison_path"].read_bytes()
                ).hexdigest(),
            },
        }
        artifact_root = root / "a1-artifacts"
        launch_fixtures.write_json(artifact_root / "a1-run-core.json", core)
        energy = artifact_root / "energy-proxy-receipt.json"
        launch_fixtures.write_json(
            energy,
            {
                "schema_version": "ember-energy-proxy-run-v1",
                "result": "MEASURED",
                "executed": True,
                "training_launched": True,
                "intended_samples": 100,
                "captured_samples": captured,
                "t06_coverage_floor": 0.95,
                "coverage_meets_t06": meets,
                "energy": {"sample_coverage_fraction": coverage},
            },
        )
        with pytest.raises(ValueError, match="coverage"):
            module.finalize_tier1_run(
                artifact_root=artifact_root,
                energy_receipt=energy,
                thresholds_path=(
                    launch_paths["repo"] / "docs" / "spec"
                    / "ember02-preregistration-thresholds-v1.json"
                ),
                expected_source_commit=launch_fixtures.SHA,
                expected_certified_launch_sha256="8" * 64,
                expected_comparison_authority=authority["comparison_path"],
            )
        assert not (artifact_root / "tier1-run.json").exists()


def test_complete_energy_window_mints_packet_a_tier1_run() -> None:
    module = _load_a1_execution()
    with tempfile.TemporaryDirectory(dir="B:/tmp") as directory:
        root = Path(directory)
        launch_paths = launch_fixtures.write_valid_bundle(root)
        authority = _install_valid_a1_authority(launch_paths)
        artifact_root = root / "a1-artifacts"
        launch_fixtures.write_json(
            artifact_root / "a1-run-core.json",
            {
                "schema_version": module.CORE_SCHEMA,
                "status": "TERMINAL",
                "source_commit": launch_fixtures.SHA,
                "certified_launch_sha256": "8" * 64,
                "parameter_count": 3_839_344_640,
                "optimizer_inventory": {
                    "schema_version": "ember-a1-adamw-state-inventory-v1",
                    "state_format": "ember-a1-full-state-adamw-cpu-offload-v1",
                    "registered_parameters": 42,
                    "complete": True,
                    "initialized_parameters": 42,
                    "registered_numel": 3_839_344_640,
                    "cpu_fp32_master_numel": 3_839_344_640,
                    "cpu_fp32_first_moment_numel": 3_839_344_640,
                    "cpu_fp32_second_moment_numel": 3_839_344_640,
                },
                "checkpoint_sha256": "9" * 64,
                "checkpoint_identity": _checkpoint_identity(
                    authority,
                    source_commit=launch_fixtures.SHA,
                    certified_launch_sha256="8" * 64,
                ),
                "resource_preflight": _resource_preflight_receipt(),
                "comparison_authority": {
                    "path": str(authority["comparison_path"]),
                    "sha256": hashlib.sha256(
                        authority["comparison_path"].read_bytes()
                    ).hexdigest(),
                },
            },
        )
        energy = artifact_root / "energy-proxy-receipt.json"
        launch_fixtures.write_json(
            energy,
            {
                "schema_version": "ember-energy-proxy-run-v1",
                "result": "MEASURED",
                "executed": True,
                "training_launched": True,
                "intended_samples": 100,
                "captured_samples": 100,
                "t06_coverage_floor": 0.95,
                "coverage_meets_t06": True,
                "energy": {"sample_coverage_fraction": 1.0},
            },
        )
        with pytest.raises(ValueError, match="substituted"):
            module.finalize_tier1_run(
                artifact_root=artifact_root,
                energy_receipt=energy,
                thresholds_path=(
                    launch_paths["repo"] / "docs" / "spec"
                    / "ember02-preregistration-thresholds-v1.json"
                ),
                expected_source_commit=launch_fixtures.SHA,
                expected_certified_launch_sha256="8" * 64,
                expected_comparison_authority=root / "foreign-comparison.json",
            )
        assert not (artifact_root / "tier1-run.json").exists()
        output = module.finalize_tier1_run(
            artifact_root=artifact_root,
            energy_receipt=energy,
            thresholds_path=(
                launch_paths["repo"] / "docs" / "spec"
                / "ember02-preregistration-thresholds-v1.json"
            ),
            expected_source_commit=launch_fixtures.SHA,
            expected_certified_launch_sha256="8" * 64,
            expected_comparison_authority=authority["comparison_path"],
        )
        original = output.read_bytes()
        with pytest.raises(FileExistsError):
            module.finalize_tier1_run(
                artifact_root=artifact_root,
                energy_receipt=energy,
                thresholds_path=(
                    launch_paths["repo"] / "docs" / "spec"
                    / "ember02-preregistration-thresholds-v1.json"
                ),
                expected_source_commit=launch_fixtures.SHA,
                expected_certified_launch_sha256="8" * 64,
                expected_comparison_authority=authority["comparison_path"],
            )
        assert output.read_bytes() == original
        receipt = json.loads(output.read_text(encoding="utf-8"))
    assert receipt["arm_id"] == "A1"
    assert receipt["tier"] == "TIER1"
    assert receipt["optimizer"]["cpu_offload"] is True
    assert receipt["identity"]["comparison_id"] == "r1-e8-a1-vs-a3"
    assert receipt["receipt_sha256"] == hashlib.sha256(
        json.dumps(
            {key: value for key, value in receipt.items() if key != "receipt_sha256"},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def test_energy_finalizer_refusal_makes_certified_launch_nonzero() -> None:
    module = launch_fixtures.load_module()
    with tempfile.TemporaryDirectory(dir="B:/tmp") as directory:
        root = Path(directory)
        launch = module.ValidatedLaunch(
            certificate_sha256="1" * 64,
            run_spec_sha256="2" * 64,
            public_master_sha=launch_fixtures.SHA,
            closure_sha256=None,
            artifact_root=root / "artifacts",
            custody_root=root,
            runner_receipt=root / "runner.json",
            seed=83,
            write_budget_bytes=1024**3,
            max_records=1,
            max_c_write_gib=1.0,
            max_b_write_gib=1.0,
            run_id="a1-finalizer-refusal",
            a1_family=A1_FAMILY,
        )
        with (
            mock.patch.object(module, "_record_run_attempt", return_value={}),
            mock.patch.object(module, "_write_execution_receipt"),
            mock.patch.object(
                module, "_finalize_a1_packet_a", side_effect=ValueError("coverage")
            ),
        ):
            result = module.execute_validated_launch(
                root,
                launch,
                run_process=lambda *args, **kwargs: type("Result", (), {"returncode": 0})(),
            )
        assert result == 78
        assert not (launch.artifact_root / "tier1-run.json").exists()


def test_real_launcher_finalizer_join_mints_tier1_run_on_complete_energy() -> None:
    """Exercise execute_validated_launch -> real finalizer with no seam mock."""

    module = launch_fixtures.load_module()
    with tempfile.TemporaryDirectory(dir="B:/tmp") as directory:
        root = Path(directory)
        paths = launch_fixtures.write_valid_bundle(root)
        authority = _install_valid_a1_authority(paths)
        with mock.patch.object(module, "read_current_master", return_value=launch_fixtures.SHA):
            launch = module.validate_certified_request(
                paths["repo"], paths["certificate"], paths["ledger"], paths["run_spec"]
            )
        launch_fixtures.write_json(
            launch.artifact_root / "a1-run-core.json",
            {
                "schema_version": "ember-a1-dense-run-core-v1",
                "status": "TERMINAL",
                "source_commit": launch.public_master_sha,
                "certified_launch_sha256": launch.run_spec_sha256,
                "parameter_count": 3_839_344_640,
                "optimizer_inventory": {
                    "schema_version": "ember-a1-adamw-state-inventory-v1",
                    "state_format": "ember-a1-full-state-adamw-cpu-offload-v1",
                    "registered_parameters": 42,
                    "registered_numel": 3_839_344_640,
                    "initialized_parameters": 42,
                    "cpu_fp32_master_numel": 3_839_344_640,
                    "cpu_fp32_first_moment_numel": 3_839_344_640,
                    "cpu_fp32_second_moment_numel": 3_839_344_640,
                    "complete": True,
                },
                "checkpoint_sha256": "9" * 64,
                "checkpoint_identity": _checkpoint_identity(
                    authority,
                    source_commit=launch.public_master_sha,
                    certified_launch_sha256=launch.run_spec_sha256,
                ),
                "resource_preflight": _resource_preflight_receipt(),
                "comparison_authority": {
                    "path": str(authority["comparison_path"]),
                    "sha256": hashlib.sha256(
                        authority["comparison_path"].read_bytes()
                    ).hexdigest(),
                },
            },
        )
        launch_fixtures.write_json(
            launch.artifact_root / "energy-proxy-receipt.json",
            {
                "schema_version": "ember-energy-proxy-run-v1",
                "result": "MEASURED",
                "executed": True,
                "training_launched": True,
                "intended_samples": 100,
                "captured_samples": 100,
                "t06_coverage_floor": 0.95,
                "coverage_meets_t06": True,
                "energy": {"sample_coverage_fraction": 1.0},
            },
        )
        with mock.patch.object(module, "_record_run_attempt", return_value={}):
            exit_code = module.execute_validated_launch(
                ROOT,
                launch,
                run_process=lambda *args, **kwargs: type(
                    "Result", (), {"returncode": 0}
                )(),
            )
        receipt = json.loads(
            (launch.artifact_root / "tier1-run.json").read_text(encoding="utf-8")
        )
    assert exit_code == 0
    assert receipt["status"] == "TERMINAL"
    assert receipt["certified_launch_sha256"] == launch.run_spec_sha256


def test_dense_counter_uses_all_parameters_and_no_expert_route() -> None:
    tools = ROOT / "tools" / "ember-restart-3b"
    inserted = str(tools) not in sys.path
    if inserted:
        sys.path.insert(0, str(tools))
    try:
        from a1_dense import DenseA1Config, DenseA1Decoder
        from parameter_counter import measure_dense_a1_parameter_counts

        model = DenseA1Decoder(DenseA1Config.small_for_tests())
        counts = measure_dense_a1_parameter_counts(model)
    finally:
        if inserted:
            sys.path.remove(str(tools))
    assert counts["unique_parameters"] == model.config.structural_parameter_count()
    assert counts["active_parameters"] == counts["unique_parameters"]
    assert counts["contains_router_or_experts"] is False


def test_dense_checkpoint_carries_complete_model_and_optimizer_inventory() -> None:
    tools = ROOT / "tools" / "ember-restart-3b"
    inserted = str(tools) not in sys.path
    if inserted:
        sys.path.insert(0, str(tools))
    try:
        import a1_checkpoint
        from a1_checkpoint import verify_dense_checkpoint, write_dense_checkpoint
        from a1_dense import DenseA1Config, DenseA1Decoder
        from a1_optimizer import A1OptimizerContract, FullStateAdamWCPUOffload

        model = DenseA1Decoder(DenseA1Config.small_for_tests())
        optimizer = FullStateAdamWCPUOffload(
            model.parameters(),
            contract=A1OptimizerContract(
                learning_rate=1e-4,
                beta1=0.9,
                beta2=0.95,
                epsilon=1e-8,
                weight_decay=0.1,
                state_format="ember-a1-full-state-adamw-cpu-offload-v1",
            ),
        )
        optimizer.initialize_state()
        with tempfile.TemporaryDirectory(dir="B:/tmp") as directory:
            checkpoint_root = Path(directory) / "checkpoint-a1-step-1"
            identity = {
                "comparison_id": "r1-e8-a1-vs-a3",
                "matched_identity": {
                    "comparison_id": "r1-e8-a1-vs-a3",
                    "corpus_authority_sha256": "1" * 64,
                    "shard_sequence_sha256": "2" * 64,
                    "tokenizer_sha256": "3" * 64,
                    "seed": 83,
                    "cursor_start": {"global_step": 0, "record_index": 0, "tokens_seen": 0},
                    "schedule_sha256": "4" * 64,
                    "genesis_sha256": "5" * 64,
                },
                "config_sha256": "6" * 64,
                "source_commit": "7" * 40,
                "certified_launch_sha256": "8" * 64,
                "tier": "TIER_1",
                "mechanism": "FULL_STATE_ADAMW_CPU_OFFLOAD",
                "predecessor": None,
            }
            original_cap = a1_checkpoint.MAX_SHARD_BYTES
            # Above the largest single parameter bundle in this config (the
            # fixed 48x48x3 raw-pixel image_input_shape's image_projector
            # weight is not shrunk by small_for_tests' hidden_size, and its
            # model+3-optimizer-moment bundle alone is ~3.4 MiB) so no single
            # parameter is refused, and below the ~4.2 MiB total across all
            # parameters so the write still splits across more than one shard.
            a1_checkpoint.MAX_SHARD_BYTES = 4 * 1024 * 1024
            manifest_path, digest = write_dense_checkpoint(
                checkpoint_root,
                model=model,
                optimizer=optimizer,
                global_step=1,
                tokens_seen=8,
                identity=identity,
            )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            actual_digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
            verified = verify_dense_checkpoint(manifest_path, expected_identity=identity)
            a1_checkpoint.MAX_SHARD_BYTES = original_cap
    finally:
        if inserted:
            sys.path.remove(str(tools))
    assert actual_digest == digest
    assert manifest["schema_version"] == "ember-a1-dense-checkpoint-v2"
    assert not (checkpoint_root / "a1-full-state.pt").exists()
    assert len(manifest["payload_shards"]) > 1
    assert verified["identity"] == identity
    assert manifest["dense_inventory"]["contains_router_or_experts"] is False
    assert manifest["optimizer_inventory"]["complete"] is True
    assert manifest["optimizer_inventory"]["registered_numel"] == manifest[
        "dense_inventory"
    ]["unique_trainable_parameters"]


@pytest.mark.parametrize(
    ("case", "message"),
    [
        ("bool-sequence", "positive integer"),
        ("tier-mechanism-swap", "tier/mechanism binding"),
        ("config-stale", "canonical A1 config"),
        ("token-receipt-stale", "token shards receipt"),
        ("comparison-stale", "comparison authority raw"),
        ("matched-a3-swap", "matched A3 run raw"),
        ("telemetry-escape", "a1_telemetry_path"),
    ],
)
def test_a1_route_refuses_typed_stale_and_swap_cases(
    case: str, message: str
) -> None:
    module = launch_fixtures.load_module()
    with tempfile.TemporaryDirectory(dir="B:/tmp") as directory:
        paths = launch_fixtures.write_valid_bundle(Path(directory))
        authority = _install_valid_a1_authority(paths)
        if case in {"bool-sequence", "tier-mechanism-swap", "telemetry-escape"}:
            run_spec = json.loads(paths["run_spec"].read_text(encoding="utf-8"))
            if case == "bool-sequence":
                run_spec["a1_sequence_length"] = True
            elif case == "tier-mechanism-swap":
                run_spec["a1_tier"] = "TIER_2"
            else:
                run_spec["a1_telemetry_path"] = str(paths["repo"] / "escaped.jsonl")
            launch_fixtures.write_json(paths["run_spec"], run_spec)
            launch_fixtures._write_custody_sidecars(paths)
        elif case == "config-stale":
            config = paths["repo"] / "tools" / "ember-restart-3b" / "ember-restart-3b-a1.json"
            config.write_bytes(config.read_bytes() + b" ")
        elif case == "token-receipt-stale":
            authority["token_receipt_path"].write_bytes(
                authority["token_receipt_path"].read_bytes() + b" "
            )
        elif case == "comparison-stale":
            authority["comparison_path"].write_bytes(
                authority["comparison_path"].read_bytes() + b" "
            )
        else:
            matched = authority["comparison_path"].parent / "matched-a3-run.json"
            matched.write_bytes(matched.read_bytes() + b" ")
        with mock.patch.object(module, "read_current_master", return_value=launch_fixtures.SHA):
            with pytest.raises(ValueError, match=message):
                module.validate_certified_request(
                    paths["repo"], paths["certificate"], paths["ledger"], paths["run_spec"]
                )
