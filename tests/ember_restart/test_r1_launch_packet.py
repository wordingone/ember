# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
from pathlib import Path
from unittest import mock

import pytest

from src.ember.governance.scripts.ember_restart.r1_launch_packet import (
    _build_run_spec,
    build_ready_for_compute_packet,
)


ROOT = Path(__file__).resolve().parents[2]
SOURCE_COMMIT = subprocess.check_output(
    ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True
).strip()


def _load_test_support(relative: str, name: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CERTIFIED_SUPPORT = _load_test_support(
    "tests/ember_restart_model/domain-governance/test_certified_train_launch.py",
    "r1_packet_certified_support",
)
TEXT_SUPPORT = _load_test_support(
    "tests/ember_restart_model/domain-governance/test_text_lab_corpus.py",
    "r1_packet_text_support",
)
TEXT_AUTHORITY = _load_test_support(
    "tools/ember-restart-3b/text_lab_corpus.py",
    "r1_packet_shared_text_authority",
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_run_spec_freezes_only_the_certificate_authorized_admitted_row_set(
    tmp_path: Path,
):
    pin = "d" * 64
    certificate = {
        "execution_scope": {
            "allowed_semantic_canary_modes": ["warm-100"],
            "allowed_admitted_row_set_sha256": pin,
            "max_optimizer_steps": 100,
            "max_records": 1,
            "max_active_expert_families": 1,
            "max_gpu_vram_gib": 24,
            "max_transient_checkpoint_gib": 20,
            "max_wall_minutes": 30,
            "max_b_write_gib": 16,
            "max_c_write_gib": 0,
            "max_write_budget_bytes": 16 * 1024**3,
        }
    }
    spec = _build_run_spec(
        certificate,
        certificate_sha256="c" * 64,
        custody_root=tmp_path,
        artifact_root=tmp_path / "run" / "artifacts",
        run_id="run",
        semantic_receipt=tmp_path / "receipt.json",
        semantic_shards_root=tmp_path / "shards",
        telemetry_path=tmp_path / "run" / "telemetry.jsonl",
        sequence_length=512,
        checkpoint_interval=50,
        admitted_row_set_sha256=pin,
    )
    assert spec["admitted_row_set_sha256"] == pin
    certificate["execution_scope"]["allowed_admitted_row_set_sha256"] = "e" * 64
    with pytest.raises(ValueError, match="does not authorize"):
        _build_run_spec(
            certificate,
            certificate_sha256="c" * 64,
            custody_root=tmp_path,
            artifact_root=tmp_path / "run" / "artifacts",
            run_id="run",
            semantic_receipt=tmp_path / "receipt.json",
            semantic_shards_root=tmp_path / "shards",
            telemetry_path=tmp_path / "run" / "telemetry.jsonl",
            sequence_length=512,
            checkpoint_interval=50,
            admitted_row_set_sha256=pin,
        )


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def _valid_entry() -> dict[str, object]:
    return {
        "schema": "ember-r1-warm100-entry-v2",
        "source_commit": SOURCE_COMMIT,
        "entry": "WARM-100",
        "steps": 100,
        "result": "PREP_ONLY",
        "claim_boundary": {
            "steps": 100,
            "execution": False,
            "sufficiency": False,
            "capability": False,
            "benchmark": False,
        },
        "dispatch": {
            "surface": "ember-cli",
            "authority": "ember-lab",
            "consumer": "certified_train_launch.py",
            "mode": "WARM-100",
        },
    }


def _write_verified_authority(
    repo: Path,
    *,
    admitted_count: int = 44,
    corrupt_admitted_evidence: bool = False,
    stale_code_identity: bool = False,
) -> Path:
    data = repo / "data" / "ember-restart-3b"
    data.mkdir(parents=True, exist_ok=True)
    tools = repo / "tools" / "ember-restart-3b"
    tools.mkdir(parents=True, exist_ok=True)
    for name in ("text_lab_corpus.py", "train.py", "run_vertical_slice.py"):
        shutil.copy2(ROOT / "tools" / "ember-restart-3b" / name, tools / name)
    schema_names = (
        "text-lab-registry-v2.schema.json",
        "text-lab-bundle-v3.schema.json",
        "text-lab-corpus-v3.schema.json",
        "text-lab-identity-v2.schema.json",
    )
    for name in schema_names:
        shutil.copy2(ROOT / "data" / "ember-restart-3b" / name, data / name)

    protected_hash = hashlib.sha256(b"heldout-only-protected-fixture").hexdigest()
    protected_manifest = {
        "benchmark_id": "fixture-heldout",
        "upstream_tree_git_sha1": "1" * 40,
        "license_sha256": "2" * 64,
        "split": {"answer_dictionary_sha256": None, "eligible_id_set_sha256": None},
        "evaluator": {"sha256": None},
    }
    protected_path = repo / "manifests" / "fixture-heldout.json"
    _write_json(protected_path, protected_manifest)
    registry = {
        "schema_version": "ember-protected-eval-registry-v2",
        "protected": [
            {
                "benchmark_id": "fixture-heldout",
                "custody_manifest_path": "manifests/fixture-heldout.json",
                "custody_manifest_sha256": _sha(protected_path),
                "custody_state": "FIXTURE_ONLY",
                "evidence": {
                    "upstream_tree_git_sha1": "1" * 40,
                    "license_sha256": "2" * 64,
                    "answer_dictionary_sha256": None,
                    "eligible_id_set_sha256": None,
                    "evaluator_sha256": None,
                },
                "protected_identifiers": [
                    {"kind": "content_sha256", "value": protected_hash}
                ],
            }
        ],
    }
    registry_path = data / "protected-eval-registry-v2.json"
    _write_json(registry_path, registry)

    rows = TEXT_SUPPORT._admitted_rows()
    for offset, row in enumerate(rows):
        if offset >= admitted_count:
            rows[offset] = {
                key: row[key]
                for key in (
                    "source_id",
                    "domain",
                    "split",
                    "required_evidence",
                    "allowed_license_spdx",
                )
            } | {"admission": "UNRESOLVED_CANDIDATE"}
    if corrupt_admitted_evidence:
        rows[0]["license_evidence"] = {
            **rows[0]["license_evidence"],
            "declared_spdx": "MIT",
        }
    text_module = _load_test_support(
        "tools/ember-restart-3b/text_lab_corpus.py", "r1_packet_authority_writer"
    )
    bundle = {
        "schema_version": "ember-text-source-receipt-bundle-v3",
        "result": "RESOLVED",
        "candidates": rows,
    }
    bundle_path = data / "text-lab-source-receipt-bundle-v3.json"
    _write_json(bundle_path, bundle)
    corpus = {
        "schema_version": "ember-text-lab-corpus-v3",
        "registry_sha256": _sha(registry_path),
        "receipt_bundle_sha256": _sha(bundle_path),
        "sources": rows,
        "train_root_sha256": text_module._authority_split_root(rows, "train"),
        "heldout_root_sha256": text_module._authority_split_root(rows, "heldout"),
    }
    corpus_path = data / "owned-text-lab-corpus-v3.json"
    _write_json(corpus_path, corpus)
    identity = {
        "schema_version": "ember-text-lab-input-identity-v2",
        "corpus_sha256": _sha(corpus_path),
        "code_files": {
            "text_lab_corpus": _sha(tools / "text_lab_corpus.py"),
            "train": _sha(tools / "train.py"),
            "run_vertical_slice": _sha(tools / "run_vertical_slice.py"),
        },
        "source_base_commit": "0" * 40,
    }
    identity_path = data / "owned-text-lab-input-identity-v3.json"
    _write_json(identity_path, identity)
    if stale_code_identity:
        with (tools / "train.py").open("ab") as handle:
            handle.write(b"# stale after identity binding\n")
    _write_json(
        data / "text-lab-frozen-eval-hashes-v1.json",
        {
            "schema_version": "ember-text-lab-frozen-eval-hashes-v1",
            "hashes": [protected_hash],
        },
    )

    def binding(path: Path, schema_name: str) -> dict[str, object]:
        return {
            "path": path.relative_to(repo).as_posix(),
            "sha256": _sha(path),
            "schema": {
                "path": f"data/ember-restart-3b/{schema_name}",
                "sha256": _sha(data / schema_name),
            },
        }

    index = {
        "schema_version": "ember-text-lab-authority-index-v2",
        "result": "PREFLIGHT_ONLY",
        "boundary": "NO_ACQUISITION_NO_TRAINING_NO_SUFFICIENT_PRETRAINING_CLAIM",
        "registry": binding(registry_path, "text-lab-registry-v2.schema.json"),
        "receipt_bundle": binding(bundle_path, "text-lab-bundle-v3.schema.json"),
        "corpus": binding(corpus_path, "text-lab-corpus-v3.schema.json"),
        "input_identity": binding(identity_path, "text-lab-identity-v2.schema.json"),
    }
    index_path = data / "text-lab-authority-index-v2.json"
    _write_json(index_path, index)
    return index_path


def _fixture(
    tmp_path: Path,
    *,
    admitted_count: int = 44,
    corrupt_admitted_evidence: bool = False,
    stale_code_identity: bool = False,
) -> dict[str, object]:
    paths = CERTIFIED_SUPPORT.write_valid_bundle(tmp_path / "bundle")
    CERTIFIED_SUPPORT.rewrite_certificate(
        paths,
        lambda certificate: certificate["execution_scope"].__setitem__(
            "allowed_semantic_canary_modes", ["warm-100"]
        ),
    )

    # The current authority validator is exercised against a fully admitted
    # fixture. Its one Git ancestry subprocess is hermetically supplied below;
    # every byte/schema/admission/code-file check remains the production code.
    authority_index = _write_verified_authority(
        paths["repo"],
        admitted_count=admitted_count,
        corrupt_admitted_evidence=corrupt_admitted_evidence,
        stale_code_identity=stale_code_identity,
    )
    index = json.loads(authority_index.read_bytes())
    corpus = json.loads(
        (paths["repo"] / index["corpus"]["path"]).read_bytes()
    )
    admitted_rows = sorted(
        (
            row
            for row in corpus["sources"]
            if row.get("admission") == "ADMITTED"
        ),
        key=lambda row: row["source_id"],
    )
    admitted_row_set_sha256 = hashlib.sha256(
        (
            json.dumps(
                {"rows": admitted_rows},
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode()
    ).hexdigest()
    CERTIFIED_SUPPORT.rewrite_certificate(
        paths,
        lambda certificate: certificate["execution_scope"].__setitem__(
            "allowed_admitted_row_set_sha256", admitted_row_set_sha256
        ),
    )

    CERTIFIED_SUPPORT.install_model_config(
        paths["repo"], CERTIFIED_SUPPORT.ARCHITECTURE_REVISION
    )
    tokenizer = paths["repo"] / "domains" / "model" / "tokenizer" / "tokenizer.json"
    _write_json(tokenizer, {"model": {"vocab": {"<pad>": 0, "x": 1}}})
    semantic_receipt = paths["repo"] / "manifests" / "token-shards-receipt.json"
    _write_json(
        semantic_receipt,
        {
            "ticket": "TOKEN-SHARDS-V0",
            "shards": [{"name": "shard-00000.bin", "sha256": "0" * 64, "n_tokens": 2}],
            "premises": {
                "tokenizer_json": {"path": "domains/model/tokenizer/tokenizer.json", "sha256": _sha(tokenizer)}
            },
            "total_stream_tokens": 2,
        },
    )
    shards_root = tmp_path / "shards"
    shards_root.mkdir()

    template = tmp_path / "authority-template"
    template.mkdir()
    for key in ("certificate", "ledger", "binding_map"):
        shutil.copy2(paths[key], template / paths[key].name)
    shutil.rmtree(paths["certificate"].parent.parent)

    entry_path = tmp_path / "r1-entry.json"
    rung_manifest = tmp_path / "r1-rung.json"
    _write_json(entry_path, _valid_entry())
    _write_json(rung_manifest, {"fixture": "governed-rung-manifest"})

    return {
        **paths,
        "authority_index": authority_index,
        "certificate_template": template / "certificate.json",
        "ledger_template": template / "declaration-ledger.jsonl",
        "binding_template": template / "sha-binding-map.json",
        "entry": entry_path,
        "rung_manifest": rung_manifest,
        "semantic_receipt": semantic_receipt,
        "shards_root": shards_root,
        "admitted_row_set_sha256": admitted_row_set_sha256,
    }


def _build(
    tmp_path: Path,
    *,
    telemetry_path: Path | None = None,
    entry=None,
    authority_mutation=None,
    admitted_count: int = 44,
    authority_manifest_rows=None,
    corrupt_admitted_evidence: bool = False,
    stale_code_identity: bool = False,
):
    fixture = _fixture(
        tmp_path,
        admitted_count=admitted_count,
        corrupt_admitted_evidence=corrupt_admitted_evidence,
        stale_code_identity=stale_code_identity,
    )
    text_module = _load_test_support(
        "tools/ember-restart-3b/text_lab_corpus.py",
        f"r1_packet_text_lab_{tmp_path.name}",
    )

    def validate_authority(repo_root: Path, **kwargs):
        with mock.patch.object(
            text_module.subprocess,
            "run",
            return_value=type("Result", (), {"returncode": 0})(),
        ):
            return text_module.validate_authority_index(repo_root, **kwargs)

    if entry is not None:
        _write_json(fixture["entry"], entry)
    if authority_mutation is not None:
        index = json.loads(fixture["authority_index"].read_text(encoding="utf-8"))
        authority_mutation(index)
        _write_json(fixture["authority_index"], index)

    result = build_ready_for_compute_packet(
        source_root=ROOT,
        launch_repo_root=fixture["repo"],
        r1_entry_path=fixture["entry"],
        r1_manifest_path=fixture["rung_manifest"],
        certificate_path=fixture["certificate_template"],
        declaration_ledger_path=fixture["ledger_template"],
        sha_binding_map_path=fixture["binding_template"],
        custody_root=fixture["custody_root"],
        artifact_root=fixture["artifact_root"],
        run_id="owned-3b-canary-test",
        semantic_receipt=fixture["semantic_receipt"],
        semantic_shards_root=fixture["shards_root"],
        telemetry_path=telemetry_path,
        authority_index_relative="data/ember-restart-3b/text-lab-authority-index-v2.json",
        authority_manifest_rows=authority_manifest_rows,
        entry_validator=lambda payload, **_: payload,
        authority_validator=validate_authority,
        current_master_reader=lambda _: CERTIFIED_SUPPORT.SHA,
    )
    return fixture, result


def test_builds_fixture_packet_reopened_by_real_certified_consumer(tmp_path: Path):
    fixture, result = _build(tmp_path)

    manifest_path = Path(result["manifest_path"])
    packet_dir = Path(result["packet_directory"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    run_spec_path = packet_dir / "run-spec.json"
    run_spec = json.loads(run_spec_path.read_text(encoding="utf-8"))

    assert manifest["status"] == "READY_FOR_COMPUTE"
    assert manifest["claim_boundary"] == {
        "execution": False,
        "result": False,
        "sufficiency": False,
        "capability": False,
        "benchmark": False,
    }
    assert run_spec["requested_scope"]["optimizer_steps"] == 100
    assert run_spec["semantic_canary_mode"] == "warm-100"
    assert not any(key.startswith("resume_") for key in run_spec)
    assert Path(run_spec["semantic_canary_telemetry_path"]).is_relative_to(
        fixture["custody_root"]
    )
    assert manifest["text_authority"]["result"] == "VERIFIED_ADMITTED_SUBSET"
    assert set(manifest["exit_source_bindings"]) == {f"E{i}" for i in range(1, 9)}
    assert manifest["dispatch"]["surface_argv"][:2] == ["/train", "--execute"]
    unsigned = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    assert manifest["manifest_sha256"] == hashlib.sha256(
        (json.dumps(unsigned, sort_keys=True, separators=(",", ":")) + "\n").encode()
    ).hexdigest()

    certified = CERTIFIED_SUPPORT.load_module()
    with mock.patch.object(
        certified, "read_current_master", return_value=CERTIFIED_SUPPORT.SHA
    ):
        launch = certified.validate_certified_request(
            fixture["repo"],
            packet_dir / "certificate.json",
            packet_dir / "declaration-ledger.jsonl",
            run_spec_path,
            _sha(packet_dir / "launch-authority-custody.json"),
        )
    assert certified.build_runner_argv(fixture["repo"], launch) == manifest["runner_argv"]


@pytest.mark.parametrize(
    ("entry_mutation", "error"),
    [
        (lambda payload: payload.update(result="COMPLETED"), "PREP_ONLY"),
        (
            lambda payload: payload["claim_boundary"].update(execution=True),
            "claim boundary",
        ),
    ],
)
def test_refuses_widened_r1_entry(tmp_path: Path, entry_mutation, error: str):
    entry = _valid_entry()
    entry_mutation(entry)
    with pytest.raises(ValueError, match=error):
        _build(tmp_path, entry=entry)


def test_refuses_telemetry_outside_custody(tmp_path: Path):
    with pytest.raises(ValueError, match="telemetry.*custody"):
        _build(tmp_path, telemetry_path=tmp_path.parent / "escaped-telemetry.jsonl")


def test_refuses_tampered_current_text_authority(tmp_path: Path):
    with pytest.raises(ValueError, match="authority bytes do not match"):
        _build(
            tmp_path,
            authority_mutation=lambda index: index["input_identity"].update(
                sha256="f" * 64
            ),
        )


def test_builds_over_verified_admitted_subset_and_freezes_both_hashes(tmp_path: Path):
    fixture, result = _build(tmp_path, admitted_count=23)

    manifest = json.loads(Path(result["manifest_path"]).read_bytes())
    authority = manifest["text_authority"]
    assert authority["result"] == "VERIFIED_ADMITTED_SUBSET"
    assert authority["admitted_row_count"] == 23
    assert len(authority["run_manifest_rows"]) == 23
    assert all(row["source_id"].startswith("candidate-") for row in authority["run_manifest_rows"])
    assert authority["authority_index_sha256"] == _sha(fixture["authority_index"])
    expected_rows_sha256 = hashlib.sha256(
        (
            json.dumps(
                {"rows": authority["run_manifest_rows"]},
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode()
    ).hexdigest()
    assert authority["admitted_row_set_sha256"] == expected_rows_sha256
    run_spec = json.loads(
        (Path(result["packet_directory"]) / "run-spec.json").read_bytes()
    )
    certificate = json.loads(
        (Path(result["packet_directory"]) / "certificate.json").read_bytes()
    )
    assert run_spec["admitted_row_set_sha256"] == expected_rows_sha256
    assert (
        certificate["execution_scope"]["allowed_admitted_row_set_sha256"]
        == expected_rows_sha256
    )


def test_refuses_run_manifest_claim_for_unadmitted_source(tmp_path: Path):
    fixture = _fixture(tmp_path, admitted_count=23)
    corpus = json.loads(
        (
            fixture["repo"]
            / "data"
            / "ember-restart-3b"
            / "owned-text-lab-corpus-v3.json"
        ).read_bytes()
    )
    unresolved = next(row for row in corpus["sources"] if row["admission"] != "ADMITTED")
    claimed = {
        "source_id": unresolved["source_id"],
        "domain": unresolved["domain"],
        "split": unresolved["split"],
        "license_spdx": "CC-BY-4.0",
        "content_sha256": "a" * 64,
        "l4_receipt": {},
    }
    with pytest.raises(ValueError, match="claims unadmitted source"):
        _build(
            tmp_path / "build",
            admitted_count=23,
            authority_manifest_rows=[claimed],
        )


def test_refuses_run_manifest_row_outside_admitted_set(tmp_path: Path):
    outside = {
        **TEXT_SUPPORT._admitted_rows()[0],
        "source_id": "candidate-unknown-train-0",
    }
    with pytest.raises(ValueError, match="outside admitted set"):
        _build(
            tmp_path,
            admitted_count=23,
            authority_manifest_rows=[outside],
        )


def test_refuses_admitted_subset_when_an_admitted_row_fails_verification(tmp_path: Path):
    with pytest.raises(ValueError, match="license evidence"):
        _build(tmp_path, admitted_count=23, corrupt_admitted_evidence=True)


def test_refuses_admitted_subset_with_stale_code_identity(tmp_path: Path):
    with pytest.raises(ValueError, match="code bytes changed"):
        _build(tmp_path, admitted_count=23, stale_code_identity=True)


class _ClosedRowAuthority:
    _AUTHORITY_INDEX_SCHEMA_V2 = "ember-text-lab-authority-index-v2"
    _UNRESOLVED_FIELDS = {
        "source_id",
        "domain",
        "split",
        "admission",
        "required_evidence",
        "allowed_license_spdx",
    }
    _ADMITTED_FIELDS = _UNRESOLVED_FIELDS | {
        "content_sha256",
        "license_spdx",
        "l4_receipt",
        "license_evidence",
    }
    _PARTITION_ADMITTED_FIELDS = _UNRESOLVED_FIELDS | {
        "content_sha256",
        "license_partition_receipt",
        "license_partition_sha256",
        "l4_receipt",
    }

    @staticmethod
    def _external_path(root: Path, relative: str) -> Path:
        return root / relative

    @staticmethod
    def _sha_bytes(value: bytes) -> str:
        return hashlib.sha256(value).hexdigest()

    @staticmethod
    def _bound_json(
        _repo_root: Path,
        binding: dict[str, object],
        *,
        external_root: Path | None = None,
    ) -> tuple[bytes, dict[str, object]]:
        assert external_root is not None
        payload = (external_root / str(binding["path"])).read_bytes()
        assert hashlib.sha256(payload).hexdigest() == binding["sha256"]
        return payload, json.loads(payload)


def _partition_admitted_row() -> dict[str, object]:
    ordinary = TEXT_SUPPORT._admitted_rows()[0]
    return {
        key: value
        for key, value in ordinary.items()
        if key not in {"license_spdx", "license_evidence"}
    } | {
        "source_id": "candidate-software_engineering-train-1",
        "license_partition_receipt": "receipts/software-engineering-train-1.json",
        "license_partition_sha256": "b" * 64,
    }


def _validate_closed_rows(
    tmp_path: Path,
    rows: list[dict[str, object]],
    *,
    manifest_rows: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    corpus_path = tmp_path / "corpus.json"
    _write_json(corpus_path, {"sources": rows})
    index_path = tmp_path / "index.json"
    _write_json(
        index_path,
        {
            "schema_version": "ember-text-lab-authority-index-v2",
            "corpus": {
                "path": corpus_path.name,
                "sha256": _sha(corpus_path),
            },
        },
    )
    with mock.patch.object(
        TEXT_AUTHORITY,
        "_bound_json",
        return_value=(corpus_path.read_bytes(), {"sources": rows}),
    ):
        return TEXT_AUTHORITY.validate_admitted_authority_subset(
            tmp_path,
            {
                "result": "NOT_ADMITTED_SOURCE_EVIDENCE_MISSING",
                "authority_index_sha256": _sha(index_path),
                "corpus_sha256": _sha(corpus_path),
            },
            index_relative=index_path.name,
            external_authority_root=tmp_path,
            manifest_rows=manifest_rows,
        )


def test_admitted_subset_hashes_both_closed_row_schemas_deterministically(
    tmp_path: Path,
):
    rows = [TEXT_SUPPORT._admitted_rows()[0], _partition_admitted_row()]

    forward = _validate_closed_rows(tmp_path / "forward", rows)
    reverse = _validate_closed_rows(tmp_path / "reverse", list(reversed(rows)))

    assert forward["run_manifest_rows"] == reverse["run_manifest_rows"]
    assert forward["admitted_row_set_sha256"] == reverse["admitted_row_set_sha256"]
    assert {
        frozenset(row) for row in forward["run_manifest_rows"]
    } == {
        frozenset(_ClosedRowAuthority._ADMITTED_FIELDS),
        frozenset(_ClosedRowAuthority._PARTITION_ADMITTED_FIELDS),
    }


def test_admitted_subset_refuses_duplicate_source_id(tmp_path: Path):
    row = TEXT_SUPPORT._admitted_rows()[0]
    with pytest.raises(ValueError, match="duplicated"):
        _validate_closed_rows(tmp_path, [row, dict(row)])


@pytest.mark.parametrize("mutation", ["extra", "missing"])
def test_admitted_subset_refuses_unknown_closed_row_schema(
    tmp_path: Path,
    mutation: str,
):
    row = dict(TEXT_SUPPORT._admitted_rows()[0])
    if mutation == "extra":
        row["unexpected"] = True
    else:
        row.pop("license_evidence")
    with pytest.raises(ValueError, match="schema"):
        _validate_closed_rows(tmp_path, [row])


def test_admitted_subset_refuses_claimed_but_unadmitted_row(tmp_path: Path):
    unresolved = {
        key: TEXT_SUPPORT._admitted_rows()[1][key]
        for key in _ClosedRowAuthority._UNRESOLVED_FIELDS
    }
    unresolved["admission"] = "UNRESOLVED_CANDIDATE"
    claim = {**TEXT_SUPPORT._admitted_rows()[0], "source_id": unresolved["source_id"]}
    with pytest.raises(ValueError, match="claims unadmitted source"):
        _validate_closed_rows(
            tmp_path,
            [TEXT_SUPPORT._admitted_rows()[0], unresolved],
            manifest_rows=[claim],
        )


def test_admitted_subset_refuses_valid_row_outside_admitted_set(tmp_path: Path):
    outside = {
        **TEXT_SUPPORT._admitted_rows()[0],
        "source_id": "candidate-unknown-train-0",
    }
    with pytest.raises(ValueError, match="outside admitted set"):
        _validate_closed_rows(
            tmp_path,
            [TEXT_SUPPORT._admitted_rows()[0]],
            manifest_rows=[outside],
        )
