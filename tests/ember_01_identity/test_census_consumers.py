from __future__ import annotations

# goal_id: EMBER-01
# workstream_id: EMBER-01C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import json
import hashlib
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = ROOT / "scripts" / "ember_01_identity"
sys.path.insert(0, str(SCRIPT_DIR))

from census_consumers import build_census, build_census_set, build_git_census, discover_filesystem_sources  # noqa: E402

FIXTURE_COMMIT = "f" * 40
CENSUS_PATH = ROOT / "manifests" / "ember-01-identity" / "consumer-census-v1.json"
STABILITY_PATH = ROOT / "manifests" / "ember-01-identity" / "consumer-census-stability-v1.json"


def test_checked_census_matches_byte_stability_receipt() -> None:
    snapshot_bytes = CENSUS_PATH.read_bytes()
    snapshot = json.loads(snapshot_bytes)
    receipt = json.loads(STABILITY_PATH.read_text(encoding="utf-8"))
    digest = hashlib.sha256(snapshot_bytes).hexdigest()
    assert receipt["byte_identical"] is True
    assert receipt["snapshot_bytes"] == len(snapshot_bytes)
    assert receipt["snapshot_sha256"] == digest
    assert receipt["complete_run_sha256"] == [digest, digest]
    assert receipt["canonical_subject_sha256"] == snapshot["canonical_subject_sha256"]
    assert receipt["root_count"] == len(snapshot["roots"])
    assert receipt["evidence_record_count"] == len(snapshot["evidence"])
    assert receipt["absolute_host_paths_published"] is False
    rendered = snapshot_bytes.decode("utf-8")
    for drive_code in range(ord("A"), ord("Z") + 1):
        assert chr(drive_code) + ":" + chr(92) * 2 not in rendered

def test_census_is_deterministic_and_evidence_linked(tmp_path: Path) -> None:
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "train.py").write_text(
        "torch.save({'state_dict': model.state_dict()}, checkpoint_path)\n",
        encoding="utf-8",
    )
    (tmp_path / "server.ts").write_text(
        "const endpoint = process.env['EMBER_MODEL_URL'];\n",
        encoding="utf-8",
    )
    tracked = ["server.ts", "scripts/train.py"]

    first = build_census(
        tmp_path, tracked_files=tracked, source_commit="a" * 40
    )
    second = build_census(
        tmp_path,
        tracked_files=list(reversed(tracked)),
        source_commit="a" * 40,
    )
    assert first == second
    assert first["source_commit"] == "a" * 40
    assert first["schema"] == "ember-identity-consumer-census-v1"
    assert first["goal_id"] == "EMBER-01"
    assert first["workstream_id"] == "EMBER-01C"
    assert first["next_executed_outcome"] == "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember"
    assert first["coverage"]["files_scanned"] == 2
    assert first["coverage"]["files_with_identity_evidence"] == 2
    assert set(first["semantic_profiles"]) == set(first["categories"])
    assert all(
        row["path"]
        and row["line"] > 0
        and len(row["line_sha256"]) == 64
        and "excerpt" not in row
        and row["root_id"] == "public-master"
        and row["surface"] == "public"
        and row["current_input"]
        and row["derived_label"]
        and row["protocol"]
        and row["failure_behavior"]
        and row["claim_effect"]
        and row["conflict"]
        and row["integration_requirement"]
        for row in first["evidence"]
    )
    assert all(
        row["integration_requirement"] in first["semantic_profiles"]
        and first["semantic_profiles"][row["integration_requirement"]]["integration_requirement"]
        for row in first["evidence"]
    )
    assert {row["category"] for row in first["evidence"]} >= {
        "checkpoint_save_load",
        "serving_runtime",
    }


def test_census_excludes_generated_receipts_and_test_fixtures(tmp_path: Path) -> None:
    (tmp_path / "receipts").mkdir()
    (tmp_path / "receipts" / "run.json").write_text(
        json.dumps({"checkpoint": "model.pt"}), encoding="utf-8"
    )
    (tmp_path / "tests" / "fixtures").mkdir(parents=True)
    (tmp_path / "tests" / "fixtures" / "fake.py").write_text(
        "MODEL_ID = 'fake'\n", encoding="utf-8"
    )
    (tmp_path / "scripts" / "ember_01_identity").mkdir(parents=True)
    (tmp_path / "scripts" / "ember_01_identity" / "self.py").write_text(
        "MODEL_ID = 'self-reference'\n", encoding="utf-8"
    )
    census = build_census(
        tmp_path,
        tracked_files=[
            "receipts/run.json",
            "tests/fixtures/fake.py",
            "scripts/ember_01_identity/self.py",
        ],
        source_commit=FIXTURE_COMMIT,
    )
    assert census["evidence"] == []
    assert census["coverage"]["files_excluded"] == 3


def test_same_line_can_expose_multiple_identity_roles(tmp_path: Path) -> None:
    (tmp_path / "cli.ts").write_text(
        "const LOCAL_MODEL_ID = 'qwen-3.6'; // borrowed reference provider\n",
        encoding="utf-8",
    )
    census = build_census(
        tmp_path, tracked_files=["cli.ts"], source_commit=FIXTURE_COMMIT
    )
    rows = census["evidence"]
    assert {row["category"] for row in rows} >= {
        "cli_operator_surface",
        "borrowed_reference",
    }


def test_every_identity_bearing_line_is_preserved(tmp_path: Path) -> None:
    (tmp_path / "many.py").write_text(
        "\n".join(f"checkpoint_path_{index} = 'model.pt'" for index in range(10)) + "\n",
        encoding="utf-8",
    )
    census = build_census(
        tmp_path, tracked_files=["many.py"], source_commit=FIXTURE_COMMIT
    )
    checkpoint_rows = [
        row for row in census["evidence"] if row["category"] == "checkpoint_save_load"
    ]
    assert len(checkpoint_rows) == 10
    assert census["categories"]["checkpoint_save_load"]["raw_match_count"] == 10
    assert all("checkpoint_path" in row["current_input"] for row in checkpoint_rows)
    assert all(row["matched_terms"] for row in checkpoint_rows)
    assert all(row["evidence_scope"] == "LINE" for row in checkpoint_rows)


def test_jsonl_state_is_one_content_hashed_surface_per_category(tmp_path: Path) -> None:
    content = "\n".join(
        json.dumps({"pid": index, "checkpoint": f"model-{index}.pt"})
        for index in range(100)
    ) + "\n"
    (tmp_path / "activity.jsonl").write_text(content, encoding="utf-8")
    census = build_census(
        tmp_path, tracked_files=["activity.jsonl"], source_commit=FIXTURE_COMMIT
    )
    checkpoint_rows = [
        row for row in census["evidence"] if row["category"] == "checkpoint_save_load"
    ]
    watchdog_rows = [
        row for row in census["evidence"] if row["category"] == "process_registry_watchdog"
    ]
    assert len(checkpoint_rows) == 1
    assert len(watchdog_rows) == 1
    assert checkpoint_rows[0]["evidence_scope"] == "FILE_CATEGORY"
    assert checkpoint_rows[0]["content_sha256"] == hashlib.sha256(
        (tmp_path / "activity.jsonl").read_bytes()
    ).hexdigest()


def test_generic_claim_and_receipt_prose_is_not_publication_identity(tmp_path: Path) -> None:
    (tmp_path / "notes.md").write_text(
        "This claim cites a receipt but defines no publication identity surface.\n",
        encoding="utf-8",
    )
    census = build_census(
        tmp_path, tracked_files=["notes.md"], source_commit=FIXTURE_COMMIT
    )
    assert not any(row["category"] == "publication_report" for row in census["evidence"])


def test_census_does_not_republish_local_paths(tmp_path: Path) -> None:
    (tmp_path / "runtime.py").write_text(
        "checkpoint_path = r'C:\\private\\model.pt'\n",
        encoding="utf-8",
    )
    census = build_census(
        tmp_path, tracked_files=["runtime.py"], source_commit=FIXTURE_COMMIT
    )
    rendered = json.dumps(census)
    assert "C:\\\\private" not in rendered
    assert all("excerpt" not in row for row in census["evidence"])


def test_sensitive_relative_path_terms_are_hash_redacted_but_locatable(tmp_path: Path) -> None:
    relative = "baseline/Sensitive-Return.md"
    (tmp_path / "baseline").mkdir()
    (tmp_path / relative).write_text("checkpoint identity\n", encoding="utf-8")
    census = build_census(
        tmp_path,
        tracked_files=[relative],
        source_commit=FIXTURE_COMMIT,
        path_redactions=["sensitive", "line"],
    )
    row = census["evidence"][0]
    assert "sensitive" not in row["path"].lower()
    assert "{redacted-" in row["path"]
    assert row["path"].startswith("baseline/")
    assert row["path_sha256"] == hashlib.sha256(relative.encode()).hexdigest()


def test_census_binds_logical_root_without_publishing_absolute_root(tmp_path: Path) -> None:
    (tmp_path / "runtime.py").write_text(
        "LOCAL_MODEL_ID = 'qwen-reference'\n", encoding="utf-8"
    )
    census = build_census(
        tmp_path,
        tracked_files=["runtime.py"],
        source_commit=FIXTURE_COMMIT,
        root_id="private-backup",
        surface="private",
    )
    rendered = json.dumps(census)
    assert census["root_id"] == "private-backup"
    assert census["surface"] == "private"
    assert str(tmp_path) not in rendered
    assert all(row["root_id"] == "private-backup" for row in census["evidence"])


def test_multi_surface_census_is_order_independent_and_path_safe(tmp_path: Path) -> None:
    public = tmp_path / "public"
    private = tmp_path / "private"
    public.mkdir()
    private.mkdir()
    (public / "serve.py").write_text("EMBER_MODEL_URL = 'local'\n", encoding="utf-8")
    (private / "train.py").write_text("optimizer.step()\n", encoding="utf-8")
    specs = [
        {"root": public, "root_id": "public-master", "surface": "public", "tracked_files": ["serve.py"], "source_commit": "a" * 40},
        {"root": private, "root_id": "private-backup", "surface": "private", "tracked_files": ["train.py"], "source_commit": "b" * 40},
    ]
    first = build_census_set(specs)
    second = build_census_set(list(reversed(specs)))
    assert first == second
    assert [row["root_id"] for row in first["roots"]] == ["private-backup", "public-master"]
    assert {row["surface"] for row in first["evidence"]} == {"public", "private"}
    assert set(first["semantic_profiles"]) >= {row["category"] for row in first["evidence"]}
    canonical = json.dumps(
        {"roots": first["roots"], "semantic_profiles": first["semantic_profiles"], "evidence": first["evidence"]},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    assert first["canonical_subject_sha256"] == hashlib.sha256(canonical).hexdigest()
    rendered = json.dumps(first)
    assert str(public) not in rendered
    assert str(private) not in rendered


def test_filesystem_surface_discovers_untracked_sources_and_binds_content(tmp_path: Path) -> None:
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "runtime.json").write_text(
        '{"model_path":"owned.ckpt"}\n', encoding="utf-8"
    )
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "ignored.py").write_text("checkpoint='ignored'\n", encoding="utf-8")
    (tmp_path / "receipts").mkdir()
    (tmp_path / "receipts" / "large.json").write_text(
        '{"checkpoint":"excluded"}\n', encoding="utf-8"
    )
    (tmp_path / "bulk").mkdir()
    (tmp_path / "bulk" / "shard.json").write_text(
        '{"checkpoint":"not-a-consumer"}\n', encoding="utf-8"
    )
    files, errors = discover_filesystem_sources(tmp_path, include_prefixes=["state/"])
    assert files == ["state/runtime.json"]
    assert errors == []
    census = build_census_set(
        [{"root": tmp_path, "root_id": "live-runtime", "surface": "live-local", "mode": "filesystem"}]
    )
    assert census["roots"][0]["source_commit"]
    assert census["roots"][0]["discovery_errors"] == []
    assert census["evidence"][0]["root_id"] == "live-runtime"


def test_missing_filesystem_surface_is_explicit_and_does_not_abort(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    census = build_census_set(
        [{"root": missing, "root_id": "missing-private-root", "surface": "private", "mode": "filesystem"}]
    )
    assert census["roots"][0]["availability"] == "MISSING"
    assert census["roots"][0]["discovery_errors"][0]["error_class"] == "FileNotFoundError"
    assert str(missing) not in json.dumps(census)


def test_cli_builds_multi_surface_snapshot_from_local_root_spec(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    root.mkdir()
    (root / "state.json").write_text('{"model_path":"owned.ckpt"}\n', encoding="utf-8")
    spec = tmp_path / "roots.json"
    output = tmp_path / "census.json"
    spec.write_text(
        json.dumps([{"root": str(root), "root_id": "live-runtime", "surface": "live-local", "mode": "filesystem"}]),
        encoding="utf-8",
    )
    completed = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "census_consumers.py"), "--roots-spec", str(spec), "--output", str(output)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema"] == "ember-identity-consumer-census-set-v1"
    assert str(root) not in json.dumps(payload)


def test_git_surface_discovers_tracked_files_when_list_is_omitted(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "serve.py").write_text("EMBER_MODEL_URL = 'local'\n", encoding="utf-8")
    subprocess.run(["git", "add", "serve.py"], cwd=tmp_path, check=True)
    census = build_census(tmp_path, source_commit=FIXTURE_COMMIT)
    assert census["coverage"]["tracked_candidates"] == 1
    assert census["evidence"][0]["path"] == "serve.py"


def test_git_object_census_ignores_deleted_or_empty_checkout_state(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "fixture@example.invalid"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Fixture"], cwd=tmp_path, check=True)
    (tmp_path / "serve.py").write_text("EMBER_MODEL_URL = 'committed'\n", encoding="utf-8")
    subprocess.run(["git", "add", "serve.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=tmp_path, check=True)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True, capture_output=True, check=True
    ).stdout.strip()
    (tmp_path / "serve.py").unlink()
    subprocess.run(["git", "add", "-u"], cwd=tmp_path, check=True)
    census = build_git_census(
        tmp_path, source_commit=commit, root_id="private-backup", surface="private"
    )
    assert census["coverage"]["tracked_candidates"] == 1
    assert census["evidence"][0]["path"] == "serve.py"
    assert census["evidence"][0]["root_id"] == "private-backup"
