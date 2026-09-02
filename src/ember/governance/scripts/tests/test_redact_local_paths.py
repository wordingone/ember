# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import redact_local_paths


SCRIPT = Path(redact_local_paths.__file__).resolve()


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    )


def _init_repo(repo: Path) -> None:
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "commit", "--allow-empty", "-m", "initial")


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-B", str(SCRIPT), "--repo-root", str(repo), *args],
        cwd=repo,
        text=True,
        capture_output=True,
    )


def test_recursive_normalization_rewrites_repo_and_external_paths(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    internal = repo / "receipts" / "nested.json"
    external = tmp_path / "private" / "secret.json"
    payload = {
        "internal": str(internal),
        "external": f"failed while reading {external}",
        "nested": [str(internal).replace("\\", "/")],
        str(external): "path-bearing key",
    }

    normalized, count = redact_local_paths.normalize_json_paths(payload, repo)

    assert count == 4
    assert normalized["internal"] == "receipts/nested.json"
    assert normalized["external"] == "failed while reading local:secret.json"
    assert normalized["nested"] == ["receipts/nested.json"]
    assert normalized["local:secret.json"] == "path-bearing key"
    assert normalized["redaction_note"] == {
        "policy": "repo-relative-or-local-basename",
        "replacement_count": 4,
    }


def test_exact_drive_path_with_spaces_is_one_external_path(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    normalized, count = redact_local_paths.normalize_json_paths(
        {"path": r"C:\private folder\nested receipt.json"},
        repo,
    )

    assert count == 1
    assert normalized["path"] == "local:nested receipt.json"


def test_existing_redaction_note_is_refused_instead_of_overwritten(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    with pytest.raises(redact_local_paths.ReceiptPathError, match="already contains"):
        redact_local_paths.normalize_json_paths(
            {"redaction_note": "historical landing note", "path": r"C:\private\x.json"},
            repo,
        )


def test_check_mode_detects_violations_without_writing(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    receipt = repo / "new.json"
    original = json.dumps({"path": str(repo / "receipts" / "x.json")}) + "\n"
    receipt.write_text(original, encoding="utf-8")

    result = _run(repo, "--check", str(receipt))

    assert result.returncode == 1
    assert "new.json" in result.stdout
    assert receipt.read_text(encoding="utf-8") == original


def test_explicit_file_redaction_reports_per_file_count(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    receipt = repo / "new.json"
    receipt.write_text(
        json.dumps({"inside": str(repo / "a.json"), "outside": r"C:\private\b.json"}),
        encoding="utf-8",
    )

    result = _run(repo, str(receipt))

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report == {
        "files": [{"path": "new.json", "redaction_count": 2}],
        "mode": "write",
        "total_redactions": 2,
    }
    data = json.loads(receipt.read_text(encoding="utf-8"))
    assert data["inside"] == "a.json"
    assert data["outside"] == "local:b.json"
    assert data["redaction_note"]["replacement_count"] == 2


@pytest.mark.parametrize("unsafe", ["receipts", "*.json"])
def test_directory_and_glob_inputs_are_refused(tmp_path: Path, unsafe: str) -> None:
    repo = tmp_path / "repo"
    (repo / "receipts").mkdir(parents=True)

    result = _run(repo, unsafe)

    assert result.returncode == 2
    assert "explicit JSON file" in result.stderr


def test_tracked_at_base_refuses_without_reasoned_override(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    receipt = repo / "receipt.json"
    receipt.write_text('{"path":"safe"}\n', encoding="utf-8")
    _git(repo, "add", "receipt.json")
    _git(repo, "commit", "-m", "base")
    receipt.write_text(json.dumps({"path": str(repo / "changed.json")}), encoding="utf-8")

    refused = _run(repo, str(receipt))
    assert refused.returncode == 2
    assert "tracked at merge base" in refused.stderr

    allowed = _run(
        repo,
        "--first-landing-override",
        "receipt is being introduced to the public branch by this landing",
        str(receipt),
    )
    assert allowed.returncode == 0, allowed.stderr
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert payload["path"] == "changed.json"
    assert payload["redaction_note"]["first_landing_override_reason"] == (
        "receipt is being introduced to the public branch by this landing"
    )


def test_invalid_base_refuses_instead_of_treating_file_as_untracked(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    receipt = repo / "receipt.json"
    receipt.write_text('{"path":"safe"}\n', encoding="utf-8")

    result = _run(repo, "--base", "not-a-commit", str(receipt))

    assert result.returncode == 2
    assert "cannot resolve selected base" in result.stderr


def test_invalid_json_and_non_object_top_level_fail_closed(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    invalid = repo / "invalid.json"
    invalid.write_bytes(b"\xff")
    array = repo / "array.json"
    array.write_text('["C:\\\\private\\\\x.json"]', encoding="utf-8")

    assert _run(repo, str(invalid)).returncode == 2
    assert _run(repo, str(array)).returncode == 2


def _load_custody_module(repo_root: Path):
    path = repo_root / "scripts" / "ember_totality" / "test_c_custody.py"
    spec = importlib.util.spec_from_file_location("custody_writer_under_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_custody_sidecar_writer_normalizes_paths_before_write(tmp_path: Path) -> None:
    source_root = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
    module = _load_custody_module(source_root)
    repo = tmp_path / "repo"
    repo.mkdir()
    external = tmp_path / "private" / "secret.json"

    rel = module._write_sidecar(
        str(repo),
        {
            "ticket": "C-CUSTODY-CHK",
            "offenders": {
                "inside": str(repo / "receipts" / "x.json"),
                "outside": str(external),
            },
        },
    )

    data = json.loads((repo / rel).read_text(encoding="utf-8"))
    assert data["offenders"]["inside"] == "receipts/x.json"
    assert data["offenders"]["outside"] == "local:secret.json"
    assert data["redaction_note"]["replacement_count"] == 2
