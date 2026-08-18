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

from scripts.ember_restart.r1_launch_packet import build_ready_for_compute_packet


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
    "tests/ember_restart_model/test_certified_train_launch.py",
    "r1_packet_certified_support",
)
TEXT_SUPPORT = _load_test_support(
    "tests/ember_restart_model/test_text_lab_corpus.py",
    "r1_packet_text_support",
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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


def _write_verified_authority(repo: Path) -> Path:
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


def _fixture(tmp_path: Path) -> dict[str, object]:
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
    authority_index = _write_verified_authority(paths["repo"])

    CERTIFIED_SUPPORT.install_model_config(
        paths["repo"], CERTIFIED_SUPPORT.ARCHITECTURE_REVISION
    )
    tokenizer = paths["repo"] / "tokenizer" / "tokenizer.json"
    _write_json(tokenizer, {"model": {"vocab": {"<pad>": 0, "x": 1}}})
    semantic_receipt = paths["repo"] / "manifests" / "token-shards-receipt.json"
    _write_json(
        semantic_receipt,
        {
            "ticket": "TOKEN-SHARDS-V0",
            "shards": [{"name": "shard-00000.bin", "sha256": "0" * 64, "n_tokens": 2}],
            "premises": {
                "tokenizer_json": {"path": "tokenizer/tokenizer.json", "sha256": _sha(tokenizer)}
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
    }


def _build(
    tmp_path: Path,
    *,
    telemetry_path: Path | None = None,
    entry=None,
    authority_mutation=None,
):
    fixture = _fixture(tmp_path)
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
    assert manifest["text_authority"]["result"] == "VERIFIED"
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
