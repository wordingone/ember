# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools" / "ember-restart-3b"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import text_lab_corpus  # noqa: E402


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _write(path: Path, value: object) -> bytes:
    raw = _canonical(value)
    path.write_bytes(raw)
    return raw


def _load_producer():
    path = ROOT / "tools" / "ember-restart-3b" / "mint_issue1719_tranche_admission.py"
    spec = importlib.util.spec_from_file_location("mint_issue1719_tranche_admission", path)
    if spec is None or spec.loader is None:
        pytest.fail("canonical #1719 tranche admission producer is unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except FileNotFoundError:
        pytest.fail("canonical #1719 tranche admission producer is unavailable")
    return module


def _historical_source_fixture(tmp_path: Path):
    historical = tmp_path / "historical"
    tools = historical / "tools" / "ember-restart-3b"
    tools.mkdir(parents=True)
    for name in ("text_lab_corpus.py", "train.py", "run_vertical_slice.py"):
        (tools / name).write_bytes((TOOLS / name).read_bytes() + b"\n# historical fixture\n")
    common = tmp_path / "common.git"
    common.mkdir()
    pinned = "1" * 40
    key = str(historical.resolve()).lower()
    state = {
        "version": 1,
        "target": 12,
        "ceiling": 12,
        "main_path": str(tmp_path / "main"),
        "legacy_paths": [],
        "managed": {
            key: {
                "path": str(historical.resolve()),
                "branch": None,
                "detached": True,
                "head": pinned,
                "owner": "fixture",
                "purpose": "historical predecessor fixture",
                "created_at": "2026-08-18T00:00:00+00:00",
                "expires": "2026-08-20",
                "c_drive_override": False,
            }
        },
        "retired": {},
        "pending_removals": {},
    }
    state_raw = _write(common / "ember-worktree-lifecycle.json", state)
    identity = {
        "schema_version": "ember-text-lab-input-identity-v2",
        "corpus_sha256": "2" * 64,
        "source_base_commit": pinned,
        "code_files": {
            "text_lab_corpus": _sha((tools / "text_lab_corpus.py").read_bytes()),
            "train": _sha((tools / "train.py").read_bytes()),
            "run_vertical_slice": _sha((tools / "run_vertical_slice.py").read_bytes()),
        },
    }
    return historical, common, state, state_raw, identity


def test_historical_predecessor_reopen_requires_governed_detached_ancestor(tmp_path: Path, monkeypatch):
    producer = _load_producer()
    historical, common, _, state_raw, identity = _historical_source_fixture(tmp_path)
    stored_validation = {"result": "NOT_ADMITTED_SOURCE_EVIDENCE_MISSING", "code_files": identity["code_files"]}

    def fake_git(repo: Path, *args: str):
        command = tuple(args)
        if command == ("merge-base", "--is-ancestor", identity["source_base_commit"], "3" * 40):
            return subprocess.CompletedProcess(command, 0, "", "")
        if command == ("rev-parse", "--show-toplevel"):
            return subprocess.CompletedProcess(command, 0, str(historical.resolve()) + "\n", "")
        if command == ("status", "--porcelain=v1", "--untracked-files=all"):
            return subprocess.CompletedProcess(command, 0, "", "")
        if command == ("symbolic-ref", "--quiet", "HEAD"):
            return subprocess.CompletedProcess(command, 1, "", "")
        if command == ("rev-parse", "HEAD"):
            return subprocess.CompletedProcess(command, 0, identity["source_base_commit"] + "\n", "")
        if command == ("rev-parse", "--git-common-dir"):
            return subprocess.CompletedProcess(command, 0, str(common.resolve()) + "\n", "")
        raise AssertionError(command)

    monkeypatch.setattr(producer, "_git", fake_git)
    module = text_lab_corpus
    monkeypatch.setattr(module, "validate_authority_index", lambda *args, **kwargs: stored_validation)

    validation, evidence = producer._validate_predecessor_authority(
        module=module,
        current_repo=ROOT,
        current_source_commit="3" * 40,
        source_custody=tmp_path,
        source_identity=identity,
        stored_validation=stored_validation,
        predecessor_source_repo=historical,
    )

    assert validation == stored_validation
    assert evidence == {
        "result": "HISTORICAL_PREDECESSOR_REOPENED",
        "source_base_commit": identity["source_base_commit"],
        "source_code_files": identity["code_files"],
        "lifecycle_state_sha256": _sha(state_raw),
        "lifecycle_managed_key": str(historical.resolve()).lower(),
        "ancestry": "ANCESTOR_OF_CURRENT_SOURCE",
    }
    current_identity = {**identity, "code_files": producer._code_files(ROOT)}
    with pytest.raises(ValueError, match="historical predecessor source repo is forbidden"):
        producer._validate_predecessor_authority(
            module=module,
            current_repo=ROOT,
            current_source_commit="3" * 40,
            source_custody=tmp_path,
            source_identity=current_identity,
            stored_validation=stored_validation,
            predecessor_source_repo=historical,
        )


@pytest.mark.parametrize("payload_changed", [False, True])
def test_historical_predecessor_reopen_binds_reviewed_identity_cure_without_weakening_payload_checks(
    tmp_path: Path,
    monkeypatch,
    payload_changed: bool,
):
    producer = _load_producer()
    historical, common, _, state_raw, identity = _historical_source_fixture(tmp_path)
    recorded_commit = identity["source_base_commit"]
    resolved_commit = "2" * 40
    current_commit = "3" * 40
    resolved_blobs = {
        "tools/ember-restart-3b/text_lab_corpus.py": b"resolved text lab\n",
        "tools/ember-restart-3b/train.py": b"resolved train\n",
        "tools/ember-restart-3b/run_vertical_slice.py": b"resolved vertical\n",
    }
    identity["code_files"] = {
        "text_lab_corpus": _sha(resolved_blobs["tools/ember-restart-3b/text_lab_corpus.py"]),
        "train": _sha(resolved_blobs["tools/ember-restart-3b/train.py"]),
        "run_vertical_slice": _sha(resolved_blobs["tools/ember-restart-3b/run_vertical_slice.py"]),
    }
    predecessor_receipt_sha256 = "4" * 64
    generated_files = {"authority.json": {"bytes": 17, "sha256": "5" * 64}}
    cure = {
        "schema_version": "ember-issue1719-source-identity-cure-v1",
        "result": "VERIFIED_SOURCE_IDENTITY_SUPERSESSION",
        "predecessor_receipt_sha256": predecessor_receipt_sha256,
        "predecessor_generated_files_sha256": _sha(_canonical(generated_files)),
        "recorded_source_base_commit": recorded_commit,
        "executed_code_files": identity["code_files"],
        "resolved_source_commit": resolved_commit,
        "resolved_code_files": identity["code_files"],
        "reviewer_reference": "mailbox:review:24111",
        "supersedes_sha256": "3b66e73afcb864769b218a581fc9525eee8af84c30006a65725c24da50d20b60",
        "replacement_authority": "mailbox:review:24148",
        "misbinding_kind": "BASE_HEAD_LABEL_WITH_REVIEWED_BRANCH_BYTES",
        "data_bytes_status": "UNCHANGED_AND_BOUND_BY_PREDECESSOR_RECEIPT",
    }
    cure_raw = _write(tmp_path / "tranche-admission-source-identity-cure.json", cure)
    stored_validation = {"result": "NOT_ADMITTED_SOURCE_EVIDENCE_MISSING"}
    payload_path = tmp_path / "payload.json"
    expected_payload = b'{"authority":"bound"}\n'
    payload_path.write_bytes(
        b'{"authority":"changed"}\n' if payload_changed else expected_payload
    )

    def fake_git(repo: Path, *args: str):
        command = tuple(args)
        if command in {
            ("merge-base", "--is-ancestor", recorded_commit, current_commit),
            ("merge-base", "--is-ancestor", resolved_commit, current_commit),
        }:
            return subprocess.CompletedProcess(command, 0, "", "")
        if command == ("rev-parse", "--show-toplevel"):
            return subprocess.CompletedProcess(command, 0, str(historical.resolve()) + "\n", "")
        if command == ("status", "--porcelain=v1", "--untracked-files=all"):
            return subprocess.CompletedProcess(command, 0, "", "")
        if command == ("symbolic-ref", "--quiet", "HEAD"):
            return subprocess.CompletedProcess(command, 1, "", "")
        if command == ("rev-parse", "HEAD"):
            return subprocess.CompletedProcess(command, 0, recorded_commit + "\n", "")
        if command == ("rev-parse", "--git-common-dir"):
            return subprocess.CompletedProcess(command, 0, str(common.resolve()) + "\n", "")
        raise AssertionError(command)

    monkeypatch.setattr(producer, "_git", fake_git)
    monkeypatch.setattr(
        producer,
        "_git_blob",
        lambda repo, commit, path: resolved_blobs[path],
        raising=False,
    )

    def validate_authority_index(repo_root: Path, **kwargs):
        code_paths = {
            "text_lab_corpus": "tools/ember-restart-3b/text_lab_corpus.py",
            "train": "tools/ember-restart-3b/train.py",
            "run_vertical_slice": "tools/ember-restart-3b/run_vertical_slice.py",
        }
        observed_code = {
            name: _sha(text_lab_corpus._path(repo_root, relative).read_bytes())
            for name, relative in code_paths.items()
        }
        if observed_code != identity["code_files"]:
            raise ValueError("predecessor code bytes changed")
        if (kwargs["external_authority_root"] / "payload.json").read_bytes() != expected_payload:
            raise ValueError("predecessor payload bytes changed")
        return stored_validation

    monkeypatch.setattr(text_lab_corpus, "validate_authority_index", validate_authority_index)

    if payload_changed:
        with pytest.raises(ValueError, match="payload bytes changed"):
            producer._validate_predecessor_authority(
                module=text_lab_corpus,
                current_repo=ROOT,
                current_source_commit=current_commit,
                source_custody=tmp_path,
                source_identity=identity,
                stored_validation=stored_validation,
                predecessor_source_repo=historical,
                predecessor_receipt_sha256=predecessor_receipt_sha256,
                predecessor_generated_files=generated_files,
            )
        return

    validation, evidence = producer._validate_predecessor_authority(
        module=text_lab_corpus,
        current_repo=ROOT,
        current_source_commit=current_commit,
        source_custody=tmp_path,
        source_identity=identity,
        stored_validation=stored_validation,
        predecessor_source_repo=historical,
        predecessor_receipt_sha256=predecessor_receipt_sha256,
        predecessor_generated_files=generated_files,
    )

    assert validation == stored_validation
    assert evidence["result"] == "HISTORICAL_PREDECESSOR_REOPENED_WITH_IDENTITY_CURE"
    assert evidence["resolved_source_commit"] == resolved_commit
    assert evidence["source_identity_cure_sha256"] == _sha(cure_raw)
    assert evidence["lifecycle_state_sha256"] == _sha(state_raw)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("absent", "historical predecessor code bytes changed"),
        ("reviewer", "source identity cure receipt is invalid"),
        ("receipt", "source identity cure receipt is invalid"),
        ("generated-files", "source identity cure receipt is invalid"),
        ("supersedes", "source identity cure receipt is invalid"),
        ("replacement-authority", "source identity cure receipt is invalid"),
        ("extra-field", "source identity cure receipt is invalid"),
        ("nonancestor", "source identity cure commit is not an ancestor"),
        ("swapped-blob", "source identity cure git objects do not match executed code"),
    ],
)
def test_source_identity_cure_refuses_absent_forged_or_swapped_evidence(
    tmp_path: Path, monkeypatch, mutation: str, message: str
):
    producer = _load_producer()
    resolved_commit = "2" * 40
    current_commit = "3" * 40
    predecessor_receipt_sha256 = "4" * 64
    generated_files = {"authority.json": {"bytes": 17, "sha256": "5" * 64}}
    resolved_blobs = {
        "tools/ember-restart-3b/text_lab_corpus.py": b"resolved text lab\n",
        "tools/ember-restart-3b/train.py": b"resolved train\n",
        "tools/ember-restart-3b/run_vertical_slice.py": b"resolved vertical\n",
    }
    code_files = {
        "text_lab_corpus": _sha(resolved_blobs["tools/ember-restart-3b/text_lab_corpus.py"]),
        "train": _sha(resolved_blobs["tools/ember-restart-3b/train.py"]),
        "run_vertical_slice": _sha(resolved_blobs["tools/ember-restart-3b/run_vertical_slice.py"]),
    }
    identity = {
        "schema_version": "ember-text-lab-input-identity-v2",
        "corpus_sha256": "6" * 64,
        "source_base_commit": "1" * 40,
        "code_files": code_files,
    }
    cure = {
        "schema_version": "ember-issue1719-source-identity-cure-v1",
        "result": "VERIFIED_SOURCE_IDENTITY_SUPERSESSION",
        "predecessor_receipt_sha256": predecessor_receipt_sha256,
        "predecessor_generated_files_sha256": _sha(_canonical(generated_files)),
        "recorded_source_base_commit": identity["source_base_commit"],
        "executed_code_files": code_files,
        "resolved_source_commit": resolved_commit,
        "resolved_code_files": code_files,
        "reviewer_reference": "mailbox:review:24111",
        "supersedes_sha256": "3b66e73afcb864769b218a581fc9525eee8af84c30006a65725c24da50d20b60",
        "replacement_authority": "mailbox:review:24148",
        "misbinding_kind": "BASE_HEAD_LABEL_WITH_REVIEWED_BRANCH_BYTES",
        "data_bytes_status": "UNCHANGED_AND_BOUND_BY_PREDECESSOR_RECEIPT",
    }
    if mutation == "reviewer":
        cure["reviewer_reference"] = "mailbox:review:99999"
    elif mutation == "receipt":
        cure["predecessor_receipt_sha256"] = "7" * 64
    elif mutation == "generated-files":
        cure["predecessor_generated_files_sha256"] = "8" * 64
    elif mutation == "supersedes":
        cure["supersedes_sha256"] = "9" * 64
    elif mutation == "replacement-authority":
        cure["replacement_authority"] = "mailbox:review:99999"
    elif mutation == "extra-field":
        cure["unreviewed"] = True
    if mutation != "absent":
        _write(tmp_path / "tranche-admission-source-identity-cure.json", cure)

    monkeypatch.setattr(
        producer,
        "_git",
        lambda repo, *args: subprocess.CompletedProcess(
            args, 1 if mutation == "nonancestor" else 0, "", ""
        ),
    )
    if mutation == "swapped-blob":
        resolved_blobs["tools/ember-restart-3b/train.py"] = b"swapped train\n"
    monkeypatch.setattr(producer, "_git_blob", lambda repo, commit, path: resolved_blobs[path])

    with pytest.raises(ValueError, match=message):
        producer._validate_identity_cure(
            module=text_lab_corpus,
            current_repo=ROOT,
            current_source_commit=current_commit,
            source_custody=tmp_path,
            source_identity=identity,
            predecessor_receipt_sha256=predecessor_receipt_sha256,
            predecessor_generated_files=generated_files,
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("missing", "historical predecessor source repo is required"),
        ("attached", "historical predecessor checkout must be detached"),
        ("dirty", "historical predecessor checkout must be clean"),
        ("wrong-head", "historical predecessor checkout HEAD changed"),
        ("unregistered", "historical predecessor checkout is not governed"),
        ("nonancestor", "historical predecessor commit is not an ancestor"),
    ],
)
def test_historical_predecessor_reopen_refusal_matrix(tmp_path: Path, monkeypatch, mutation: str, message: str):
    producer = _load_producer()
    historical, common, state, _, identity = _historical_source_fixture(tmp_path)
    if mutation == "unregistered":
        state["managed"] = {}
        _write(common / "ember-worktree-lifecycle.json", state)
    stored_validation = {"result": "NOT_ADMITTED_SOURCE_EVIDENCE_MISSING"}

    def fake_git(repo: Path, *args: str):
        command = tuple(args)
        if command[0] == "merge-base":
            return subprocess.CompletedProcess(command, 1 if mutation == "nonancestor" else 0, "", "")
        if command == ("rev-parse", "--show-toplevel"):
            return subprocess.CompletedProcess(command, 0, str(historical.resolve()) + "\n", "")
        if command == ("status", "--porcelain=v1", "--untracked-files=all"):
            return subprocess.CompletedProcess(command, 0, " M file\n" if mutation == "dirty" else "", "")
        if command == ("symbolic-ref", "--quiet", "HEAD"):
            return subprocess.CompletedProcess(command, 0 if mutation == "attached" else 1, "refs/heads/main\n", "")
        if command == ("rev-parse", "HEAD"):
            head = "4" * 40 if mutation == "wrong-head" else identity["source_base_commit"]
            return subprocess.CompletedProcess(command, 0, head + "\n", "")
        if command == ("rev-parse", "--git-common-dir"):
            return subprocess.CompletedProcess(command, 0, str(common.resolve()) + "\n", "")
        raise AssertionError(command)

    monkeypatch.setattr(producer, "_git", fake_git)
    module = text_lab_corpus
    monkeypatch.setattr(module, "validate_authority_index", lambda *args, **kwargs: stored_validation)
    with pytest.raises(ValueError, match=message):
        producer._validate_predecessor_authority(
            module=module,
            current_repo=ROOT,
            current_source_commit="3" * 40,
            source_custody=tmp_path,
            source_identity=identity,
            stored_validation=stored_validation,
            predecessor_source_repo=None if mutation == "missing" else historical,
        )


def _source_custody(tmp_path: Path) -> tuple[Path, str, str]:
    custody = tmp_path / "predecessor"
    custody.mkdir()
    data = ROOT / "data" / "ember-restart-3b"
    rows = json.loads((data / "owned-text-lab-corpus-v2.json").read_bytes())["sources"]
    registry_raw = (data / "protected-eval-registry-v2.json").read_bytes()
    bundle = {
        "schema_version": "ember-text-source-receipt-bundle-v3",
        "result": "UNRESOLVED_CANDIDATE",
        "candidates": rows,
    }
    bundle_raw = _write(custody / "text-lab-source-receipt-bundle-v3.json", bundle)
    corpus = {
        "schema_version": "ember-text-lab-corpus-v3",
        "registry_sha256": _sha(registry_raw),
        "receipt_bundle_sha256": _sha(bundle_raw),
        "sources": rows,
        "train_root_sha256": text_lab_corpus._authority_split_root(rows, "train"),
        "heldout_root_sha256": text_lab_corpus._authority_split_root(rows, "heldout"),
    }
    corpus_raw = _write(custody / "owned-text-lab-corpus-v3.json", corpus)
    code_files = {
        # The predecessor was minted before the external-root validator existed. Its
        # exact identity must remain source evidence while the successor rebinds current code.
        "text_lab_corpus": "f" * 64,
        "train": _sha((TOOLS / "train.py").read_bytes()),
        "run_vertical_slice": _sha((TOOLS / "run_vertical_slice.py").read_bytes()),
    }
    identity = {
        "schema_version": "ember-text-lab-input-identity-v2",
        "corpus_sha256": _sha(corpus_raw),
        "code_files": code_files,
        "source_base_commit": "4a9b874d8a7418265f0f727ccecae59cf1de70f4",
    }
    identity_raw = _write(custody / "owned-text-lab-input-identity-v3.json", identity)
    scratch_prefix = ".issue1719-deleted-mint-fixture"
    index = {
        "schema_version": "ember-text-lab-authority-index-v2",
        "result": "PREFLIGHT_ONLY",
        "boundary": "NO_ACQUISITION_NO_TRAINING_NO_SUFFICIENT_PRETRAINING_CLAIM",
        "registry": {
            "path": "data/ember-restart-3b/protected-eval-registry-v2.json",
            "sha256": _sha(registry_raw),
            "schema": {
                "path": "data/ember-restart-3b/text-lab-registry-v2.schema.json",
                "sha256": _sha((data / "text-lab-registry-v2.schema.json").read_bytes()),
            },
        },
        "receipt_bundle": {
            "path": f"{scratch_prefix}/text-lab-source-receipt-bundle-v3.json",
            "sha256": _sha(bundle_raw),
            "schema": {
                "path": "data/ember-restart-3b/text-lab-bundle-v3.schema.json",
                "sha256": _sha((data / "text-lab-bundle-v3.schema.json").read_bytes()),
            },
        },
        "corpus": {
            "path": f"{scratch_prefix}/owned-text-lab-corpus-v3.json",
            "sha256": _sha(corpus_raw),
            "schema": {
                "path": "data/ember-restart-3b/text-lab-corpus-v3.schema.json",
                "sha256": _sha((data / "text-lab-corpus-v3.schema.json").read_bytes()),
            },
        },
        "input_identity": {
            "path": f"{scratch_prefix}/owned-text-lab-input-identity-v3.json",
            "sha256": _sha(identity_raw),
            "schema": {
                "path": "data/ember-restart-3b/text-lab-identity-v2.schema.json",
                "sha256": _sha((data / "text-lab-identity-v2.schema.json").read_bytes()),
            },
        },
    }
    index_raw = _write(custody / "text-lab-authority-index-v2.json", index)
    generated = {
        "owned-text-lab-corpus-v3.json": {"bytes": len(corpus_raw), "sha256": _sha(corpus_raw)},
        "owned-text-lab-input-identity-v3.json": {"bytes": len(identity_raw), "sha256": _sha(identity_raw)},
        "text-lab-authority-index-v2.json": {"bytes": len(index_raw), "sha256": _sha(index_raw)},
        "text-lab-source-receipt-bundle-v3.json": {"bytes": len(bundle_raw), "sha256": _sha(bundle_raw)},
    }
    receipt = {
        "admitted_row_count": 0,
        "boundary": "NO_CORPUS_BYTE_MOVEMENT_NO_TRAINING_NO_SUFFICIENT_PRETRAINING_CLAIM",
        "generated_files": generated,
        "minted_at": "2026-08-17T00:00:00+00:00",
        "negative_receipts": {},
        "overall_authority_result": "NOT_ADMITTED_SOURCE_EVIDENCE_MISSING",
        "reopened_connector_file_count": 0,
        "reopened_connector_total_bytes": 0,
        "result": "PARTIAL_AUTHORITY_SUCCESSOR",
        "row_receipts": [],
        "schema_version": "ember-issue1719-tranche3-admission-v1",
        "source_authority": {"fixture": "0" * 64},
        "source_code_files": code_files,
        "source_commit": "4a9b874d8a7418265f0f727ccecae59cf1de70f4",
        "unresolved_row_count": 44,
        "validation_receipt": {"result": "NOT_ADMITTED_SOURCE_EVIDENCE_MISSING"},
    }
    receipt_raw = _write(custody / "tranche3-admission-receipt.json", receipt)
    _write(
        custody / "mint-log.json",
        {
            "schema_version": "ember-issue1719-tranche3-mint-log-v1",
            "source_commit": receipt["source_commit"],
            "adapter_path": "tools/ember-restart-3b/text_lab_corpus.py",
            "adapter_sha256": code_files["text_lab_corpus"],
            "receipt_sha256": _sha(receipt_raw),
            "event": "FIXTURE_PREDECESSOR",
            "overall_authority_result": receipt["overall_authority_result"],
        },
    )
    return custody, _sha(receipt_raw), _sha(index_raw)


def test_generic_successor_republishes_packet_local_authority_and_reopens_it(tmp_path: Path):
    producer = _load_producer()
    custody, predecessor_sha, predecessor_index_sha = _source_custody(tmp_path)
    plan_path = tmp_path / "plan.json"
    plan_raw = _write(
        plan_path,
        {
            "schema_version": "ember-issue1719-tranche-admission-plan-v1",
            "successor_id": "tranche3r",
            "cases": [],
        },
    )
    source_hashes = {path.name: _sha(path.read_bytes()) for path in custody.iterdir() if path.is_file()}
    output = tmp_path / "published"

    result = producer.mint_successor(
        repo=ROOT,
        source_commit="4a9b874d8a7418265f0f727ccecae59cf1de70f4",
        source_custody=custody,
        predecessor_receipt_name="tranche3-admission-receipt.json",
        predecessor_receipt_sha256=predecessor_sha,
        plan_path=plan_path,
        plan_sha256=_sha(plan_raw),
        output=output,
    )

    assert {path.name: _sha(path.read_bytes()) for path in custody.iterdir() if path.is_file()} == source_hashes
    index = json.loads((output / "text-lab-authority-index-v2.json").read_bytes())
    assert index["receipt_bundle"]["path"] == "text-lab-source-receipt-bundle-v3.json"
    assert index["corpus"]["path"] == "owned-text-lab-corpus-v3.json"
    assert index["input_identity"]["path"] == "owned-text-lab-input-identity-v3.json"
    reopened = text_lab_corpus.validate_authority_index(
        ROOT,
        index_relative="text-lab-authority-index-v2.json",
        external_authority_root=output,
    )
    assert reopened == result["validation_receipt"]
    receipt = json.loads((output / "tranche-admission-receipt.json").read_bytes())
    assert receipt["predecessor"]["receipt_sha256"] == predecessor_sha
    assert receipt["index_transition"] == {
        "predecessor_sha256": predecessor_index_sha,
        "successor_sha256": _sha((output / "text-lab-authority-index-v2.json").read_bytes()),
        "rewrite": "scratch-relative artifact paths replaced by packet-local basenames",
    }
    assert receipt["identity_transition"]["predecessor_sha256"] != receipt["identity_transition"]["successor_sha256"]
    assert (output / "tranche-admission-plan.json").read_bytes() == plan_raw
    assert receipt["plan"] == {
        "file_name": "tranche-admission-plan.json",
        "sha256": _sha(plan_raw),
        "successor_id": "tranche3r",
    }
    assert result["result"] == "PARTIAL_AUTHORITY_SUCCESSOR"


def test_generic_successor_consumes_only_validated_projected_predecessor(tmp_path: Path, monkeypatch):
    producer = _load_producer()
    custody, predecessor_sha, _ = _source_custody(tmp_path)
    projection_receipt = tmp_path / "projection" / "custody-projection-receipt.json"
    projection_receipt.parent.mkdir()
    projection_receipt.write_bytes(b"projection receipt")
    projection_sha = _sha(projection_receipt.read_bytes())
    calls = []

    class ProjectionModule:
        @staticmethod
        def validate_projection_custody(**kwargs):
            calls.append(kwargs)
            return {
                "generated": {
                    name: (custody / name).read_bytes()
                    for name in producer.ARTIFACT_NAMES.values()
                },
                "receipt": {"schema_version": "ember-text-lab-custody-projection-v1"},
            }

    monkeypatch.setattr(producer, "load_projection_module", lambda repo: ProjectionModule)
    plan_path = tmp_path / "plan.json"
    plan_raw = _write(plan_path, {
        "schema_version": "ember-issue1719-tranche-admission-plan-v1",
        "successor_id": "tranche3r",
        "cases": [],
    })
    output = tmp_path / "published"
    producer.mint_successor(
        repo=ROOT, source_commit="4a9b874d8a7418265f0f727ccecae59cf1de70f4",
        source_custody=custody,
        predecessor_receipt_name="tranche3-admission-receipt.json",
        predecessor_receipt_sha256=predecessor_sha,
        predecessor_projection_receipt=projection_receipt,
        predecessor_projection_receipt_sha256=projection_sha,
        plan_path=plan_path, plan_sha256=_sha(plan_raw), output=output,
    )
    receipt = json.loads((output / "tranche-admission-receipt.json").read_bytes())
    assert receipt["predecessor"]["custody_projection"] == {
        "receipt_path": str(projection_receipt.resolve()),
        "receipt_sha256": projection_sha,
    }
    assert len(calls) == 1


def test_generic_successor_admits_one_closed_connector_case(tmp_path: Path):
    producer = _load_producer()
    custody, predecessor_sha, _ = _source_custody(tmp_path)
    connector_root = tmp_path / "connector"
    connector_root.mkdir()
    source_raw = b"human-authored licensed mathematics source\n"
    (connector_root / "source.txt").write_bytes(source_raw)
    source_sha = _sha(source_raw)
    connector = {
        "schema": "corpus-connector-receipt-v1",
        "connector": {"name": "fixture_fetch", "version": "v1"},
        "source": "fixture",
        "source_id": "fixture/math",
        "canonical_url": "https://example.invalid/math",
        "revision": "fixture-v1",
        "dest_root": str(connector_root),
        "fetched_at": "2026-08-17T00:00:00Z",
        "files": [{"path": "source.txt", "bytes": len(source_raw), "sha256": source_sha}],
        "total_bytes": len(source_raw),
        "sha256_manifest": _sha(source_sha.encode("utf-8")),
        "license": "CC-BY-4.0",
        "license_evidence": "publisher terms",
        "l3_statement": "fetch-only; no model mediation",
        "notes": "fixture",
    }
    connector_path = tmp_path / "connector-receipt.json"
    connector_raw = _write(connector_path, connector)
    plan_path = tmp_path / "plan.json"
    plan_raw = _write(
        plan_path,
        {
            "schema_version": "ember-issue1719-tranche-admission-plan-v1",
            "successor_id": "tranche4",
            "cases": [
                {
                    "source_id": "candidate-mathematics-train-0",
                    "connector_slot": "fixture-math",
                    "connector_receipt_path": str(connector_path),
                    "connector_receipt_sha256": _sha(connector_raw),
                    "expected_license_spdx": "CC-BY-4.0",
                    "evidence": {
                        "kind": "publisher_terms",
                        "terms_url": "https://example.invalid/license",
                        "declared_spdx": "CC-BY-4.0",
                    },
                }
            ],
        },
    )
    output = tmp_path / "published"

    producer.mint_successor(
        repo=ROOT,
        source_commit="4a9b874d8a7418265f0f727ccecae59cf1de70f4",
        source_custody=custody,
        predecessor_receipt_name="tranche3-admission-receipt.json",
        predecessor_receipt_sha256=predecessor_sha,
        plan_path=plan_path,
        plan_sha256=_sha(plan_raw),
        output=output,
    )

    corpus = json.loads((output / "owned-text-lab-corpus-v3.json").read_bytes())
    admitted = [row for row in corpus["sources"] if row["admission"] == "ADMITTED"]
    assert len(admitted) == 1
    assert admitted[0]["source_id"] == "candidate-mathematics-train-0"
    assert admitted[0]["content_sha256"] == source_sha
    receipt = json.loads((output / "tranche-admission-receipt.json").read_bytes())
    assert receipt["admitted_row_count"] == 1
    assert receipt["unresolved_row_count"] == 43
    assert receipt["row_receipts"][0]["connector_receipt_sha256"] == _sha(connector_raw)


def test_generic_successor_chains_from_its_own_published_receipt(tmp_path: Path):
    producer = _load_producer()
    custody, predecessor_sha, _ = _source_custody(tmp_path)
    first_plan = tmp_path / "first-plan.json"
    first_plan_raw = _write(
        first_plan,
        {"schema_version": "ember-issue1719-tranche-admission-plan-v1", "successor_id": "tranche3r", "cases": []},
    )
    first_output = tmp_path / "first-published"
    first = producer.mint_successor(
        repo=ROOT,
        source_commit="4a9b874d8a7418265f0f727ccecae59cf1de70f4",
        source_custody=custody,
        predecessor_receipt_name="tranche3-admission-receipt.json",
        predecessor_receipt_sha256=predecessor_sha,
        plan_path=first_plan,
        plan_sha256=_sha(first_plan_raw),
        output=first_output,
    )
    second_plan = tmp_path / "second-plan.json"
    second_plan_raw = _write(
        second_plan,
        {"schema_version": "ember-issue1719-tranche-admission-plan-v1", "successor_id": "tranche4", "cases": []},
    )
    second_output = tmp_path / "second-published"

    second = producer.mint_successor(
        repo=ROOT,
        source_commit="4a9b874d8a7418265f0f727ccecae59cf1de70f4",
        source_custody=first_output,
        predecessor_receipt_name="tranche-admission-receipt.json",
        predecessor_receipt_sha256=first["receipt_sha256"],
        plan_path=second_plan,
        plan_sha256=_sha(second_plan_raw),
        output=second_output,
    )

    receipt = json.loads((second_output / "tranche-admission-receipt.json").read_bytes())
    assert receipt["predecessor"]["receipt_sha256"] == first["receipt_sha256"]
    assert second["validation_receipt"] == text_lab_corpus.validate_authority_index(
        ROOT,
        index_relative="text-lab-authority-index-v2.json",
        external_authority_root=second_output,
    )


def test_historical_reopen_evidence_is_frozen_and_successor_does_not_reopen_old_lifecycle(
    tmp_path: Path, monkeypatch
):
    producer = _load_producer()
    legacy, legacy_sha, _ = _source_custody(tmp_path)
    predecessor_plan = tmp_path / "predecessor-plan.json"
    predecessor_plan_raw = _write(
        predecessor_plan,
        {"schema_version": "ember-issue1719-tranche-admission-plan-v1", "successor_id": "tranche4c", "cases": []},
    )
    predecessor_output = tmp_path / "historical-predecessor"
    producer.mint_successor(
        repo=ROOT,
        source_commit="4a9b874d8a7418265f0f727ccecae59cf1de70f4",
        source_custody=legacy,
        predecessor_receipt_name="tranche3-admission-receipt.json",
        predecessor_receipt_sha256=legacy_sha,
        plan_path=predecessor_plan,
        plan_sha256=_sha(predecessor_plan_raw),
        output=predecessor_output,
    )

    identity_path = predecessor_output / "owned-text-lab-input-identity-v3.json"
    identity = json.loads(identity_path.read_bytes())
    identity["source_base_commit"] = "1" * 40
    identity["code_files"] = {
        "text_lab_corpus": "a" * 64,
        "train": "b" * 64,
        "run_vertical_slice": "c" * 64,
    }
    identity_raw = _write(identity_path, identity)
    index_path = predecessor_output / "text-lab-authority-index-v2.json"
    index = json.loads(index_path.read_bytes())
    index["input_identity"]["sha256"] = _sha(identity_raw)
    index_raw = _write(index_path, index)
    receipt_path = predecessor_output / "tranche-admission-receipt.json"
    receipt = json.loads(receipt_path.read_bytes())
    receipt["source_code_files"] = identity["code_files"]
    receipt["generated_files"][identity_path.name] = {"bytes": len(identity_raw), "sha256": _sha(identity_raw)}
    receipt["generated_files"][index_path.name] = {"bytes": len(index_raw), "sha256": _sha(index_raw)}
    stored_validation = {"result": "NOT_ADMITTED_SOURCE_EVIDENCE_MISSING", "historical": True}
    receipt["validation_receipt"] = stored_validation
    predecessor_raw = _write(receipt_path, receipt)
    log_path = predecessor_output / "mint-log.json"
    log = json.loads(log_path.read_bytes())
    log["receipt_sha256"] = _sha(predecessor_raw)
    _write(log_path, log)
    _write(predecessor_output / "tranche-admission-source-identity-cure.json", {
        "fixture": "the validator double below owns semantic cure validation",
    })

    frozen_evidence = {
        "result": "HISTORICAL_PREDECESSOR_REOPENED",
        "source_base_commit": identity["source_base_commit"],
        "source_code_files": identity["code_files"],
        "lifecycle_state_sha256": "d" * 64,
        "lifecycle_managed_key": "fixture-historical-checkout",
        "ancestry": "ANCESTOR_OF_CURRENT_SOURCE",
    }
    calls = []
    real_validate_predecessor = producer._validate_predecessor_authority

    def historical_once(**kwargs):
        calls.append(kwargs)
        assert kwargs["predecessor_source_repo"] == tmp_path / "governed-historical"
        return stored_validation, frozen_evidence

    monkeypatch.setattr(producer, "_validate_predecessor_authority", historical_once)
    successor_plan = tmp_path / "successor-plan.json"
    successor_plan_raw = _write(
        successor_plan,
        {"schema_version": "ember-issue1719-tranche-admission-plan-v1", "successor_id": "tranche4d", "cases": []},
    )
    successor_output = tmp_path / "successor"
    successor = producer.mint_successor(
        repo=ROOT,
        source_commit="4a9b874d8a7418265f0f727ccecae59cf1de70f4",
        source_custody=predecessor_output,
        predecessor_receipt_name="tranche-admission-receipt.json",
        predecessor_receipt_sha256=_sha(predecessor_raw),
        plan_path=successor_plan,
        plan_sha256=_sha(successor_plan_raw),
        output=successor_output,
        predecessor_source_repo=tmp_path / "governed-historical",
    )
    successor_receipt = json.loads((successor_output / "tranche-admission-receipt.json").read_bytes())
    assert successor_receipt["predecessor"]["historical_predecessor_reopen"] == frozen_evidence
    assert len(calls) == 1

    monkeypatch.setattr(producer, "_validate_predecessor_authority", real_validate_predecessor)
    final_plan = tmp_path / "final-plan.json"
    final_plan_raw = _write(
        final_plan,
        {"schema_version": "ember-issue1719-tranche-admission-plan-v1", "successor_id": "tranche4e", "cases": []},
    )
    final = producer.mint_successor(
        repo=ROOT,
        source_commit="4a9b874d8a7418265f0f727ccecae59cf1de70f4",
        source_custody=successor_output,
        predecessor_receipt_name="tranche-admission-receipt.json",
        predecessor_receipt_sha256=successor["receipt_sha256"],
        plan_path=final_plan,
        plan_sha256=_sha(final_plan_raw),
        output=tmp_path / "final",
    )
    assert final["result"] == "PARTIAL_AUTHORITY_SUCCESSOR"


def test_generic_successor_refuses_to_overwrite_existing_output(tmp_path: Path):
    producer = _load_producer()
    custody, predecessor_sha, _ = _source_custody(tmp_path)
    plan_path = tmp_path / "plan.json"
    plan_raw = _write(
        plan_path,
        {"schema_version": "ember-issue1719-tranche-admission-plan-v1", "successor_id": "tranche3r", "cases": []},
    )
    output = tmp_path / "published"
    output.mkdir()
    sentinel = output / "operator-owned.txt"
    sentinel.write_bytes(b"preserve me")

    with pytest.raises(FileExistsError, match="output already exists"):
        producer.mint_successor(
            repo=ROOT,
            source_commit="4a9b874d8a7418265f0f727ccecae59cf1de70f4",
            source_custody=custody,
            predecessor_receipt_name="tranche3-admission-receipt.json",
            predecessor_receipt_sha256=predecessor_sha,
            plan_path=plan_path,
            plan_sha256=_sha(plan_raw),
            output=output,
        )

    assert sentinel.read_bytes() == b"preserve me"
    assert {path.name for path in output.iterdir()} == {"operator-owned.txt"}


def test_generic_successor_loses_publish_race_without_replacing_foreign_custody(tmp_path: Path, monkeypatch):
    producer = _load_producer()
    custody, predecessor_sha, _ = _source_custody(tmp_path)
    plan_path = tmp_path / "plan.json"
    plan_raw = _write(
        plan_path,
        {"schema_version": "ember-issue1719-tranche-admission-plan-v1", "successor_id": "tranche3r", "cases": []},
    )
    output = tmp_path / "published"
    real_publish = producer.atomic_publish_no_replace

    def publish_after_foreign_winner(source: Path, destination: Path):
        destination.mkdir()
        (destination / "foreign.txt").write_bytes(b"foreign custody wins")
        return real_publish(source, destination)

    monkeypatch.setattr(producer, "atomic_publish_no_replace", publish_after_foreign_winner)
    with pytest.raises(FileExistsError):
        producer.mint_successor(
            repo=ROOT,
            source_commit="4a9b874d8a7418265f0f727ccecae59cf1de70f4",
            source_custody=custody,
            predecessor_receipt_name="tranche3-admission-receipt.json",
            predecessor_receipt_sha256=predecessor_sha,
            plan_path=plan_path,
            plan_sha256=_sha(plan_raw),
            output=output,
        )

    assert (output / "foreign.txt").read_bytes() == b"foreign custody wins"
    assert not list(tmp_path.glob(".published.staging-*"))


def test_generic_successor_refuses_forged_predecessor_validation_receipt(tmp_path: Path):
    producer = _load_producer()
    custody, predecessor_sha, _ = _source_custody(tmp_path)
    first_plan = tmp_path / "first-plan.json"
    first_plan_raw = _write(
        first_plan,
        {"schema_version": "ember-issue1719-tranche-admission-plan-v1", "successor_id": "tranche3r", "cases": []},
    )
    first_output = tmp_path / "first-published"
    producer.mint_successor(
        repo=ROOT,
        source_commit="4a9b874d8a7418265f0f727ccecae59cf1de70f4",
        source_custody=custody,
        predecessor_receipt_name="tranche3-admission-receipt.json",
        predecessor_receipt_sha256=predecessor_sha,
        plan_path=first_plan,
        plan_sha256=_sha(first_plan_raw),
        output=first_output,
    )
    receipt_path = first_output / "tranche-admission-receipt.json"
    receipt = json.loads(receipt_path.read_bytes())
    receipt["validation_receipt"]["authority_index_sha256"] = "0" * 64
    forged_receipt_raw = _write(receipt_path, receipt)
    log_path = first_output / "mint-log.json"
    log = json.loads(log_path.read_bytes())
    log["receipt_sha256"] = _sha(forged_receipt_raw)
    _write(log_path, log)
    next_plan = tmp_path / "next-plan.json"
    next_plan_raw = _write(
        next_plan,
        {"schema_version": "ember-issue1719-tranche-admission-plan-v1", "successor_id": "tranche4", "cases": []},
    )

    with pytest.raises(ValueError, match="predecessor validation receipt changed"):
        producer.mint_successor(
            repo=ROOT,
            source_commit="4a9b874d8a7418265f0f727ccecae59cf1de70f4",
            source_custody=first_output,
            predecessor_receipt_name="tranche-admission-receipt.json",
            predecessor_receipt_sha256=_sha(forged_receipt_raw),
            plan_path=next_plan,
            plan_sha256=_sha(next_plan_raw),
            output=tmp_path / "second-published",
        )


def test_generic_successor_refuses_nonfile_in_predecessor_custody(tmp_path: Path):
    producer = _load_producer()
    custody, predecessor_sha, _ = _source_custody(tmp_path)
    (custody / "unbound-directory").mkdir()
    plan_path = tmp_path / "plan.json"
    plan_raw = _write(
        plan_path,
        {"schema_version": "ember-issue1719-tranche-admission-plan-v1", "successor_id": "tranche3r", "cases": []},
    )
    with pytest.raises(ValueError, match="predecessor custody file set is not exact"):
        producer.mint_successor(
            repo=ROOT,
            source_commit="4a9b874d8a7418265f0f727ccecae59cf1de70f4",
            source_custody=custody,
            predecessor_receipt_name="tranche3-admission-receipt.json",
            predecessor_receipt_sha256=predecessor_sha,
            plan_path=plan_path,
            plan_sha256=_sha(plan_raw),
            output=tmp_path / "published",
        )


def test_generic_successor_refuses_postpublish_nonfile_and_rolls_back(tmp_path: Path, monkeypatch):
    producer = _load_producer()
    custody, predecessor_sha, _ = _source_custody(tmp_path)
    plan_path = tmp_path / "plan.json"
    plan_raw = _write(
        plan_path,
        {"schema_version": "ember-issue1719-tranche-admission-plan-v1", "successor_id": "tranche3r", "cases": []},
    )
    output = tmp_path / "published"
    real_publish = producer.atomic_publish_no_replace

    def publish_then_add_unbound_directory(source: Path, destination: Path):
        real_publish(source, destination)
        (destination / "unbound-directory").mkdir()

    monkeypatch.setattr(producer, "atomic_publish_no_replace", publish_then_add_unbound_directory)
    with pytest.raises(ValueError, match="published custody file set changed on reopen"):
        producer.mint_successor(
            repo=ROOT,
            source_commit="4a9b874d8a7418265f0f727ccecae59cf1de70f4",
            source_custody=custody,
            predecessor_receipt_name="tranche3-admission-receipt.json",
            predecessor_receipt_sha256=predecessor_sha,
            plan_path=plan_path,
            plan_sha256=_sha(plan_raw),
            output=output,
        )
    assert not output.exists()
