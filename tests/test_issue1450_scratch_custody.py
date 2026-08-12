# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""CPU-only custody-census contract for issue #1450."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tools import scratch_custody


def _run_hidden(*args, **kwargs):
    kwargs.setdefault("shell", False)
    kwargs.setdefault("creationflags", getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return subprocess.run(*args, **kwargs)


def test_git_child_is_explicitly_shell_free_and_hidden(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    observed: dict[str, object] = {}

    def capture_run(*args, **kwargs):
        observed.update(kwargs)
        return subprocess.CompletedProcess(args[0], 0, stdout="ok\n", stderr="")

    monkeypatch.setattr(scratch_custody.subprocess, "run", capture_run)
    assert scratch_custody._git(tmp_path, "rev-parse", "HEAD") == "ok"
    assert observed["shell"] is False
    assert observed["creationflags"] == getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _fixture(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    scratch = root / "scratch"
    (scratch / "run-a").mkdir(parents=True)
    (scratch / "run-a" / "result.bin").write_bytes(b"abc")
    (scratch / "run-b").mkdir()
    (scratch / "run-b" / "notes.txt").write_text("owned\n", encoding="utf-8")
    _run_hidden(["git", "-C", str(root), "init", "-q"], check=True, capture_output=True)
    _run_hidden(["git", "-C", str(root), "config", "user.email", "test@example.invalid"], check=True)
    _run_hidden(["git", "-C", str(root), "config", "user.name", "Issue 1450 Test"], check=True)
    _run_hidden(["git", "-C", str(root), "add", "scratch"], check=True)
    _run_hidden(["git", "-C", str(root), "commit", "-qm", "fixture"], check=True)
    return root


def test_census_is_closed_deterministic_and_path_free(tmp_path: Path):
    root = _fixture(tmp_path)
    manifest = scratch_custody.build_manifest(root, label="issue-1450", max_bytes=1024)
    assert set(manifest) == {
        "schema_version", "label", "target", "source_commit", "source_status_sha256",
        "authority", "policy", "entries", "top_level", "summary", "manifest_sha256",
    }
    assert manifest["authority"] == scratch_custody.AUTHORITY
    assert manifest["schema_version"] == scratch_custody.SCHEMA_VERSION
    assert manifest["entries"][0]["path"] == "run-a/result.bin"
    assert manifest["summary"] == {"files": 2, "bytes": 10}
    assert manifest["manifest_sha256"] == scratch_custody.manifest_sha256(manifest)
    assert not any(str(root) in json.dumps(manifest) for _ in [0])
    assert scratch_custody.validate_manifest(root, manifest) == manifest


def test_census_refuses_cap_before_manifest(tmp_path: Path):
    root = _fixture(tmp_path)
    with pytest.raises(scratch_custody.CensusError, match="byte budget"):
        scratch_custody.build_manifest(root, label="issue-1450", max_bytes=8)


@pytest.mark.parametrize("failed_command", ["rev-parse", "status", "ls-files"])
def test_census_refuses_when_git_source_binding_is_unreadable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failed_command: str,
):
    root = _fixture(tmp_path)
    real_git = scratch_custody._git

    def fail_one_git_command(repo: Path, *args: str) -> str | None:
        if args and args[0] == failed_command:
            return None
        return real_git(repo, *args)

    monkeypatch.setattr(scratch_custody, "_git", fail_one_git_command)
    with pytest.raises(scratch_custody.CensusError, match="Git source binding"):
        scratch_custody.build_manifest(root, label="issue-1450", max_bytes=1024)


def test_census_refuses_nested_directory_that_omits_repository_scratch(tmp_path: Path):
    root = _fixture(tmp_path)
    nested = root / "foreign-root"
    (nested / "scratch" / "decoy").mkdir(parents=True)
    (nested / "scratch" / "decoy" / "result.bin").write_bytes(b"decoy")

    with pytest.raises(scratch_custody.CensusError, match="repository root"):
        scratch_custody.build_manifest(nested, label="issue-1450", max_bytes=1024)


def test_guard_refuses_file_drift_and_manifest_tamper(tmp_path: Path):
    root = _fixture(tmp_path)
    manifest = scratch_custody.build_manifest(root, label="issue-1450", max_bytes=1024)
    (root / "scratch" / "run-a" / "result.bin").write_bytes(b"tampered")
    with pytest.raises(scratch_custody.CensusError, match="entry bytes|manifest drift"):
        scratch_custody.validate_manifest(root, manifest)
    manifest = scratch_custody.build_manifest(root, label="issue-1450", max_bytes=1024)
    manifest["entries"][0]["sha256"] = "0" * 64
    manifest["manifest_sha256"] = scratch_custody.manifest_sha256(manifest)
    with pytest.raises(scratch_custody.CensusError, match="entry bytes|top-level projection"):
        scratch_custody.validate_manifest(root, manifest)


def test_guard_rejects_unknown_or_aliased_inventory_rows(tmp_path: Path):
    root = _fixture(tmp_path)
    manifest = scratch_custody.build_manifest(root, label="issue-1450", max_bytes=1024)
    manifest["unexpected"] = True
    with pytest.raises(scratch_custody.CensusError, match="closed"):
        scratch_custody.validate_manifest(root, manifest)
    manifest = scratch_custody.build_manifest(root, label="issue-1450", max_bytes=1024)
    manifest["entries"][0]["path"] = "../outside"
    manifest["manifest_sha256"] = scratch_custody.manifest_sha256(manifest)
    with pytest.raises(scratch_custody.CensusError, match="path"):
        scratch_custody.validate_manifest(root, manifest)


def test_manifest_consumers_refuse_noncanonical_commit_and_nonfile_kind(tmp_path: Path):
    root = _fixture(tmp_path)
    manifest = scratch_custody.build_manifest(root, label="issue-1450", max_bytes=1024)
    manifest["source_commit"] = "UNBOUND"
    manifest["manifest_sha256"] = scratch_custody.manifest_sha256(manifest)
    with pytest.raises(scratch_custody.CensusError, match="source commit"):
        scratch_custody.build_disposition(manifest, {})

    manifest = scratch_custody.build_manifest(root, label="issue-1450", max_bytes=1024)
    manifest["entries"][0]["kind"] = "directory"
    manifest["manifest_sha256"] = scratch_custody.manifest_sha256(manifest)
    with pytest.raises(scratch_custody.CensusError, match="entry kind"):
        scratch_custody.build_disposition(manifest, {})


@pytest.mark.parametrize(
    ("mutate", "expected_error"),
    [
        (lambda manifest: manifest.__setitem__("source_commit", "UNBOUND"), "source commit"),
        (
            lambda manifest: manifest["entries"][0].__setitem__("kind", "directory"),
            "entry kind",
        ),
    ],
    ids=["noncanonical-source-commit", "nonfile-entry-kind"],
)
def test_cli_disposition_refuses_malformed_manifest_without_writing_output(
    tmp_path: Path, mutate, expected_error: str,
):
    root = _fixture(tmp_path)
    manifest = scratch_custody.build_manifest(root, label="issue-1450", max_bytes=1024)
    mutate(manifest)
    manifest["manifest_sha256"] = scratch_custody.manifest_sha256(manifest)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    annotations_path = tmp_path / "annotations.json"
    annotations_path.write_text("{}", encoding="utf-8")
    output = tmp_path / "disposition.json"

    result = _run_hidden(
        [
            sys.executable,
            str(Path(__file__).resolve().parents[1] / "tools" / "scratch_custody.py"),
            "disposition",
            "--manifest",
            str(manifest_path),
            "--annotations",
            str(annotations_path),
            "--output",
            str(output),
        ],
        text=True,
        capture_output=True,
    )

    assert result.returncode != 0
    assert expected_error in result.stderr
    assert not output.exists()
    assert not output.with_name(output.name + ".tmp").exists()


def test_guard_rejects_symlinked_entry(tmp_path: Path):
    root = _fixture(tmp_path)
    outside = tmp_path / "outside"
    outside.write_text("outside", encoding="utf-8")
    try:
        (root / "scratch" / "run-a" / "escape").symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation unavailable")
    with pytest.raises(scratch_custody.CensusError, match="reparse|symlink"):
        scratch_custody.build_manifest(root, label="issue-1450", max_bytes=1024)


def test_cli_guard_has_no_success_on_tampered_root(tmp_path: Path):
    root = _fixture(tmp_path)
    manifest_path = tmp_path / "manifest.json"
    assert scratch_custody.write_manifest(root, manifest_path, label="issue-1450", max_bytes=1024) == manifest_path
    (root / "scratch" / "run-b" / "notes.txt").write_text("drift\n", encoding="utf-8")
    result = _run_hidden(
        [
            sys.executable,
            str(Path(__file__).resolve().parents[1] / "tools" / "scratch_custody.py"),
            "guard",
            "--root",
            str(root),
            "--manifest",
            str(manifest_path),
        ],
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert "entry bytes" in result.stderr or "manifest drift" in result.stderr


def test_cli_census_refuses_nested_root_without_writing_output(tmp_path: Path):
    root = _fixture(tmp_path)
    nested = root / "foreign-root"
    (nested / "scratch" / "decoy").mkdir(parents=True)
    (nested / "scratch" / "decoy" / "result.bin").write_bytes(b"decoy")
    output = tmp_path / "nested-manifest.json"
    result = _run_hidden(
        [
            sys.executable,
            str(Path(__file__).resolve().parents[1] / "tools" / "scratch_custody.py"),
            "census",
            "--root",
            str(nested),
            "--output",
            str(output),
            "--label",
            "issue-1450",
            "--max-bytes",
            "1024",
        ],
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert "repository root" in result.stderr
    assert not output.exists()


def test_manifest_writer_refuses_existing_temporary_without_mutation(tmp_path: Path):
    root = _fixture(tmp_path)
    output = tmp_path / "manifest.json"
    temporary = tmp_path / "manifest.json.tmp"
    temporary.write_bytes(b"existing-custody")

    with pytest.raises(scratch_custody.CensusError, match="temporary"):
        scratch_custody.write_manifest(
            root, output, label="issue-1450", max_bytes=1024,
        )

    assert temporary.read_bytes() == b"existing-custody"
    assert not output.exists()


def test_disposition_is_set_equal_to_census_and_defaults_unresolved_rows_to_keep(tmp_path: Path):
    root = _fixture(tmp_path)
    manifest = scratch_custody.build_manifest(root, label="issue-1450", max_bytes=1024)
    disposition = scratch_custody.build_disposition(
        manifest,
        {
            "run-a": {
                "producer": "scripts/example.py:10",
                "issue_or_run": "#1450 fixture",
                "references": ["z-reference", "a-reference", "z-reference"],
                "identical_copy": "NOT_FOUND",
            }
        },
    )

    assert disposition["schema_version"] == "ember-scratch-disposition-v1"
    assert disposition["ticket"] == scratch_custody.DISPOSITION_TICKET
    assert disposition["sha_convention"] == scratch_custody.SHA_CONVENTION
    assert disposition["invariant_sha256"] == scratch_custody.INVARIANT_SHA256
    assert disposition["authority"] == scratch_custody.AUTHORITY
    assert disposition["source_manifest_sha256"] == manifest["manifest_sha256"]
    assert disposition["source"] == {
        "commit": manifest["source_commit"],
        "status_sha256": manifest["source_status_sha256"],
        "files": manifest["summary"]["files"],
        "bytes": manifest["summary"]["bytes"],
    }
    assert [row["path"] for row in disposition["entries"]] == ["run-a", "run-b"]
    assert disposition["entries"][0]["producer"] == "scripts/example.py:10"
    assert disposition["entries"][0]["references"] == ["a-reference", "z-reference"]
    assert disposition["entries"][0]["disposition"] == "KEEP_UNRESOLVED"
    assert disposition["entries"][1]["producer"] == "UNKNOWN"
    assert disposition["entries"][1]["issue_or_run"] == "UNKNOWN"
    assert disposition["entries"][1]["identical_copy"] == "UNRESOLVED"
    assert disposition["entries"][1]["disposition"] == "KEEP_UNRESOLVED"
    assert disposition["summary"] == {
        "entries": 2,
        "keep_unresolved": 2,
        "move_ready": 0,
    }
    assert scratch_custody.validate_disposition(manifest, disposition) == disposition


def test_disposition_refuses_foreign_annotation_and_tampered_move_credit(tmp_path: Path):
    root = _fixture(tmp_path)
    manifest = scratch_custody.build_manifest(root, label="issue-1450", max_bytes=1024)
    annotation = {
        "producer": "UNKNOWN",
        "issue_or_run": "UNKNOWN",
        "references": [],
        "identical_copy": "UNRESOLVED",
    }
    with pytest.raises(scratch_custody.CensusError, match="annotation path"):
        scratch_custody.build_disposition(manifest, {"foreign-run": annotation})

    disposition = scratch_custody.build_disposition(manifest, {})
    disposition["entries"][0]["disposition"] = "MOVE_READY"
    disposition["disposition_sha256"] = scratch_custody.disposition_sha256(disposition)
    with pytest.raises(scratch_custody.CensusError, match="move authority"):
        scratch_custody.validate_disposition(manifest, disposition)

    disposition = scratch_custody.build_disposition(manifest, {})
    disposition["source"]["files"] += 1
    disposition["disposition_sha256"] = scratch_custody.disposition_sha256(disposition)
    with pytest.raises(scratch_custody.CensusError, match="source binding"):
        scratch_custody.validate_disposition(manifest, disposition)

    for forged_path in (
        r"C:\host\producer.py",
        "C:producer.py",
        "../foreign/producer.py",
        "./producer.py",
        "scripts/../foreign.py",
    ):
        annotation["producer"] = forged_path
        with pytest.raises(scratch_custody.CensusError, match="path-free"):
            scratch_custody.build_disposition(manifest, {"run-a": annotation})


def test_disposition_refuses_duplicate_or_malformed_census_rows(tmp_path: Path):
    root = _fixture(tmp_path)
    manifest = scratch_custody.build_manifest(root, label="issue-1450", max_bytes=1024)
    manifest["top_level"].append(dict(manifest["top_level"][0]))
    manifest["manifest_sha256"] = scratch_custody.manifest_sha256(manifest)

    with pytest.raises(scratch_custody.CensusError, match="top-level path"):
        scratch_custody.build_disposition(manifest, {})


def test_disposition_rederives_manifest_projection_and_summary(tmp_path: Path):
    root = _fixture(tmp_path)
    manifest = scratch_custody.build_manifest(root, label="issue-1450", max_bytes=1024)
    manifest["top_level"][0]["bytes"] += 1
    manifest["top_level"][0]["sha256"] = "0" * 64
    manifest["manifest_sha256"] = scratch_custody.manifest_sha256(manifest)
    with pytest.raises(scratch_custody.CensusError, match="top-level projection"):
        scratch_custody.build_disposition(manifest, {})

    manifest = scratch_custody.build_manifest(root, label="issue-1450", max_bytes=1024)
    manifest["summary"]["files"] += 1
    manifest["summary"]["bytes"] += 1
    manifest["manifest_sha256"] = scratch_custody.manifest_sha256(manifest)
    with pytest.raises(scratch_custody.CensusError, match="summary projection"):
        scratch_custody.build_disposition(manifest, {})

    manifest = scratch_custody.build_manifest(root, label="issue-1450", max_bytes=1024)
    manifest["entries"].reverse()
    manifest["top_level"] = scratch_custody._top_level(manifest["entries"])
    manifest["manifest_sha256"] = scratch_custody.manifest_sha256(manifest)
    with pytest.raises(scratch_custody.CensusError, match="entry order"):
        scratch_custody.build_disposition(manifest, {})

    manifest = scratch_custody.build_manifest(root, label="issue-1450", max_bytes=1024)
    disposition = scratch_custody.build_disposition(manifest, {})
    disposition["entries"].reverse()
    disposition["disposition_sha256"] = scratch_custody.disposition_sha256(disposition)
    with pytest.raises(scratch_custody.CensusError, match="entry order"):
        scratch_custody.validate_disposition(manifest, disposition)


def test_cli_writes_and_guards_closed_disposition_without_move_authority(tmp_path: Path):
    root = _fixture(tmp_path)
    manifest_path = tmp_path / "manifest.json"
    annotations_path = tmp_path / "annotations.json"
    disposition_path = tmp_path / "disposition.json"
    scratch_custody.write_manifest(
        root, manifest_path, label="issue-1450", max_bytes=1024,
    )
    annotations_path.write_text("{}", encoding="utf-8")
    tool = str(Path(__file__).resolve().parents[1] / "tools" / "scratch_custody.py")

    write_result = _run_hidden(
        [
            sys.executable, tool, "disposition", "--manifest", str(manifest_path),
            "--annotations", str(annotations_path), "--output", str(disposition_path),
        ],
        text=True,
        capture_output=True,
    )
    assert write_result.returncode == 0, write_result.stderr
    assert write_result.stdout.strip() == "DISPOSITION_WRITTEN"

    guard_result = _run_hidden(
        [
            sys.executable, tool, "disposition-guard", "--manifest", str(manifest_path),
            "--disposition", str(disposition_path),
        ],
        text=True,
        capture_output=True,
    )
    assert guard_result.returncode == 0, guard_result.stderr
    assert guard_result.stdout.strip() == "DISPOSITION_GUARD_PASS"
    written = json.loads(disposition_path.read_text(encoding="utf-8"))
    assert written["summary"] == {"entries": 2, "keep_unresolved": 2, "move_ready": 0}

    written["entries"][0]["disposition"] = "MOVE_READY"
    written["disposition_sha256"] = scratch_custody.disposition_sha256(written)
    disposition_path.write_text(json.dumps(written), encoding="utf-8")
    refused = _run_hidden(
        [
            sys.executable, tool, "disposition-guard", "--manifest", str(manifest_path),
            "--disposition", str(disposition_path),
        ],
        text=True,
        capture_output=True,
    )
    assert refused.returncode != 0
    assert "move authority" in refused.stderr


def test_disposition_contract_documents_no_move_authority_and_closed_schema():
    repo = Path(__file__).resolve().parents[1]
    contract = (repo / "docs" / "hygiene" / "issue-1450-scratch-custody-v1.md").read_text(
        encoding="utf-8",
    )
    schema = json.loads(
        (repo / "docs" / "hygiene" / "issue-1450-scratch-disposition-v1.schema.json").read_text(
            encoding="utf-8",
        )
    )
    manifest_schema = json.loads(
        (repo / "docs" / "hygiene" / "issue-1450-scratch-custody-v1.schema.json").read_text(
            encoding="utf-8",
        )
    )

    assert "disposition-guard" in contract
    assert "KEEP_UNRESOLVED" in contract
    assert "does not grant move or deletion authority" in " ".join(contract.split())
    assert "ticket=ISSUE-1450-SCRATCH-DISPOSITION" in contract
    assert "timezone-aware `ts`" in contract
    assert "`sha_convention`" in contract
    assert "`invariant_sha256`" in contract
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {
        "schema_version", "ticket", "ts", "sha_convention", "invariant_sha256", "authority",
        "source_manifest_sha256", "source", "entries", "summary", "disposition_sha256",
    }
    assert schema["properties"]["entries"]["items"]["properties"]["disposition"] == {
        "const": "KEEP_UNRESOLVED",
    }
    top_level = manifest_schema["properties"]["top_level"]["items"]
    assert top_level["additionalProperties"] is False
    assert set(top_level["required"]) == {"path", "files", "bytes", "sha256"}
    assert manifest_schema["properties"]["source_commit"] == {
        "type": "string",
        "pattern": "^[0-9a-f]{40}$",
    }


def test_public_disposition_satisfies_repository_receipt_floor():
    repo = Path(__file__).resolve().parents[1]
    receipt = repo / "receipts" / "issue-1450" / "live-scratch-disposition-v1.json"
    result = _run_hidden(
        [sys.executable, str(repo / "scripts" / "receipt_check.py"), "--file", str(receipt)],
        cwd=repo,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
