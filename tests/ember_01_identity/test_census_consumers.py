from __future__ import annotations

# goal_id: EMBER-01
# workstream_id: EMBER-01C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import json
import hashlib
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = ROOT / "scripts" / "ember_01_identity"
sys.path.insert(0, str(SCRIPT_DIR))

from census_consumers import build_census, build_census_set, build_git_census, discover_filesystem_sources, materialize_scoped_semantics, resolve_root_locator_spec, summarize_snapshot_adjudication  # noqa: E402

FIXTURE_COMMIT = "f" * 40
CENSUS_PATH = ROOT / "manifests" / "ember-01-identity" / "consumer-census-v1.json"
STABILITY_PATH = ROOT / "manifests" / "ember-01-identity" / "consumer-census-stability-v1.json"
SEMANTICS_PATH = ROOT / "manifests" / "ember-01-identity" / "consumer-semantics-v1.json"
ROOT_LOCATOR_SPEC_PATH = ROOT / "manifests" / "ember-01-identity" / "consumer-census-roots-v1.json"
CONSUMER_SCOPE_PATH = ROOT / "manifests" / "ember-01-identity" / "consumer-scope-v1.json"


def test_checked_semantics_manifest_covers_every_identity_category_without_placeholders() -> None:
    rows = json.loads(SEMANTICS_PATH.read_text(encoding="utf-8"))
    required = {
        "architecture_config", "training_optimizer", "checkpoint_save_load",
        "serving_runtime", "cli_operator_surface", "evaluation_benchmark",
        "publication_report", "borrowed_reference", "process_registry_watchdog",
        "parameter_identity", "tokenizer_data_lineage", "mechanism_identity",
        "receipt_identity",
    }
    assert {row["category"] for row in rows} == required
    assert all(row["root_id"] == "live-execution-tree" for row in rows)
    assert all(len(row["evidence_sha256"]) == 64 for row in rows)
    assert all("UNRESOLVED" not in value and "POTENTIAL_ONLY" not in value
               for row in rows for value in row.values())


def test_checked_root_locator_spec_is_path_safe_and_complete() -> None:
    payload = json.loads(ROOT_LOCATOR_SPEC_PATH.read_text(encoding="utf-8"))
    assert payload["schema"] == "ember-census-root-locators-v1"
    assert payload["portable_root_id"] == "public-master"
    roots = payload["roots"]
    assert len(roots) == 8
    assert {row["root_id"] for row in roots} == {
        "public-master", "private-backup-default", "identity-contract-candidate",
        "live-execution-tree", "live-benchmark-assets",
        "coordination-evidence-primary", "coordination-evidence-secondary",
        "configured-private-backup-root",
    }
    rendered = json.dumps(payload)
    assert not any(f"{chr(code)}:\\\\" in rendered for code in range(ord("A"), ord("Z") + 1))
    assert all(set(row["locator"]) <= {"kind", "env"} for row in roots)


def test_checked_consumer_scope_is_portable_exact_and_claims_only_conservative_completeness() -> None:
    scope = json.loads(CONSUMER_SCOPE_PATH.read_text(encoding="utf-8"))
    assert scope["schema"] == "ember-reviewed-consumer-scope-v1"
    assert scope["root_id"] == "public-master"
    assert scope["source_commit"] == "ca500aabe0f597ab85e762ceb53748724fb0ae98"
    assert scope["global_consumer_completeness"] == "CONSERVATIVE_SUPERSET_COMPLETE"
    assert scope["candidate_adjudication"] == {
        "schema": "ember-conservative-candidate-adjudication-v1",
        "policy_id": "fail-closed-static-superset-v1",
        "root_id": "public-master",
        "source_commit": scope["source_commit"],
        "roles": {
            "EXECUTABLE_CANDIDATE": "CONSERVATIVE_CONSUMER",
            "DOCUMENTATION_EVIDENCE": "REVIEWED_IDENTITY_SOURCE",
            "DATA_EVIDENCE": "REVIEWED_IDENTITY_SOURCE",
            "OPAQUE_FILE": "CONSERVATIVE_CONSUMER",
        },
    }
    ids = [row["consumer_id"] for row in scope["consumers"]]
    assert len(ids) == len(set(ids)) == 13
    assert {row["category"] for row in scope["consumers"]} == {
        "architecture_config", "training_optimizer", "checkpoint_save_load",
        "serving_runtime", "cli_operator_surface", "evaluation_benchmark",
        "publication_report", "borrowed_reference", "process_registry_watchdog",
        "parameter_identity", "tokenizer_data_lineage", "mechanism_identity",
        "receipt_identity",
    }


def test_scoped_semantics_reanchor_reviewed_consumers_to_portable_root() -> None:
    scope = json.loads(CONSUMER_SCOPE_PATH.read_text(encoding="utf-8"))
    semantics = json.loads(SEMANTICS_PATH.read_text(encoding="utf-8"))
    rows = materialize_scoped_semantics(scope, semantics)
    assert {row["consumer_id"] for row in rows} == {
        row["consumer_id"] for row in scope["consumers"]
    }
    assert all(row["root_id"] == "public-master" for row in rows)


def test_root_locator_spec_resolves_repo_env_and_missing_without_serializing_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    external = tmp_path / "external"
    external.mkdir()
    monkeypatch.setenv("EMBER_TEST_EXTERNAL", str(external))
    payload = {
        "schema": "ember-census-root-locators-v1",
        "portable_root_id": "repo",
        "roots": [
            {"root_id":"repo","surface":"public","mode":"filesystem","locator":{"kind":"repo_root"}},
            {"root_id":"env","surface":"private","mode":"filesystem","locator":{"kind":"env","env":"EMBER_TEST_EXTERNAL"}},
            {"root_id":"missing","surface":"private","mode":"filesystem","locator":{"kind":"missing"}},
        ],
    }
    resolved = resolve_root_locator_spec(payload, repo_root=tmp_path)
    assert [Path(row["root"]) for row in resolved[:2]] == [tmp_path, external]
    assert not Path(resolved[2]["root"]).exists()
    assert all("locator" not in row for row in resolved)


def test_portable_root_profile_requires_no_host_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = json.loads(ROOT_LOCATOR_SPEC_PATH.read_text(encoding="utf-8"))
    for key in list(os.environ):
        if key.startswith("EMBER_CENSUS_"):
            monkeypatch.delenv(key, raising=False)
    resolved = resolve_root_locator_spec(
        payload, repo_root=tmp_path, replay_profile="portable"
    )
    assert [row["root_id"] for row in resolved] == ["public-master"]


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
    assert receipt["artifact_class"] == "ENVIRONMENTAL_DISCOVERY"
    assert receipt["global_consumer_completeness"] == "NOT_CLAIMED"
    assert summarize_snapshot_adjudication(
        snapshot, receipt["environmental_adjudication"]
    ) == {
        "adjudication_counts": {
            "CONSERVATIVE_CONSUMER": 57694,
            "REVIEWED_IDENTITY_SOURCE": 7495,
        },
        "unadjudicated_count": 0,
        "global_consumer_completeness": "ENVIRONMENTAL_DISCOVERY_ONLY",
    }
    portable = receipt["portable_replay"]
    assert portable["byte_identical"] is True
    assert portable["snapshot_sha256"] == "d34208f7c617c151d2e07f4a185e86c5868fe3e6d7bb986148b75fa39aac1d4a"
    assert portable["verified_consumer_count"] == 13
    assert portable["tracked_file_count"] == portable["files_accounted"] == 2878
    assert portable["evidence_record_count"] == 24648
    assert portable["discovered_evidence_count"] == 24635
    assert portable["unadjudicated_count"] == 0
    assert portable["global_consumer_completeness"] == "CONSERVATIVE_SUPERSET_COMPLETE"
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
        and row["claim_effect"]
        and row["integration_requirement"]
        for row in first["evidence"]
    )
    assert all(
            row["category"] in first["semantic_profiles"]
            and first["semantic_profiles"][row["category"]]["integration_requirement"]
        for row in first["evidence"]
    )
    assert {row["category"] for row in first["evidence"]} >= {
        "checkpoint_save_load",
        "serving_runtime",
    }


def test_census_includes_receipt_test_and_identity_sources_but_excludes_its_generated_snapshot(tmp_path: Path) -> None:
    (tmp_path / "receipts").mkdir()
    (tmp_path / "receipts" / "run.json").write_text(
        json.dumps({"checkpoint": "model.pt"}), encoding="utf-8"
    )
    (tmp_path / "tests" / "fixtures").mkdir(parents=True)
    (tmp_path / "tests" / "fixtures" / "fake.py").write_text(
        "LOCAL_MODEL_ID = 'fake'\n", encoding="utf-8"
    )
    (tmp_path / "scripts" / "ember_01_identity").mkdir(parents=True)
    (tmp_path / "scripts" / "ember_01_identity" / "self.py").write_text(
        "LOCAL_MODEL_ID = 'self-reference'\n", encoding="utf-8"
    )
    (tmp_path / "manifests" / "ember-01-identity").mkdir(parents=True)
    (tmp_path / "manifests" / "ember-01-identity" / "consumer-census-v1.json").write_text(
        json.dumps({"checkpoint": "self-reference"}), encoding="utf-8"
    )
    census = build_census(
        tmp_path,
        tracked_files=[
            "receipts/run.json",
            "tests/fixtures/fake.py",
            "scripts/ember_01_identity/self.py",
            "manifests/ember-01-identity/consumer-census-v1.json",
        ],
        source_commit=FIXTURE_COMMIT,
    )
    assert {row["path"] for row in census["evidence"]} == {
        "receipts/run.json",
        "tests/fixtures/fake.py",
        "scripts/ember_01_identity/self.py",
    }
    assert census["coverage"]["files_excluded"] == 1
    classes = {row["path"]: row["record_class"] for row in census["evidence"]}
    assert classes["tests/fixtures/fake.py"] == "CANDIDATE_EXECUTABLE_MATCH"
    assert classes["scripts/ember_01_identity/self.py"].startswith("CANDIDATE_")
    roles = {row["path"]: row["source_role"] for row in census["evidence"]}
    assert roles["receipts/run.json"] == "DATA_EVIDENCE"
    assert roles["tests/fixtures/fake.py"] == "EXECUTABLE_CANDIDATE"
    assert roles["scripts/ember_01_identity/self.py"] == "EXECUTABLE_CANDIDATE"


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
    assert all(row["review_state"] == "UNADJUDICATED" for row in rows)
    assert all(row["claim_effect"] == "NO_CREDIT" for row in rows)
    assert all(
        field not in row
        for row in rows
        for field in ("derived_label", "protocol", "failure_behavior", "conflict")
    )


def test_exact_semantics_override_is_required_for_verified_consumer_record(tmp_path: Path) -> None:
    (tmp_path / "server.py").write_text("EMBER_MODEL_URL = config.endpoint\n", encoding="utf-8")
    semantics = [{
        "root_id": "public-master",
        "path": "server.py",
        "category": "serving_runtime",
        "evidence_sha256": hashlib.sha256(
            "EMBER_MODEL_URL = config.endpoint".encode()
        ).hexdigest(),
        "current_input": "config.endpoint",
        "derived_label": "selected serving endpoint",
        "protocol": "environment-or-config endpoint selection",
        "failure_behavior": "falls back when identity binding is absent",
        "claim_effect": "can select the served subject",
        "conflict": "endpoint location is not checkpoint identity",
        "integration_requirement": "require a validated manifest before endpoint adoption",
    }]
    census = build_census(
        tmp_path,
        tracked_files=["server.py"],
        source_commit=FIXTURE_COMMIT,
        consumer_semantics=semantics,
    )
    row = census["evidence"][0]
    assert row["record_class"] == "VERIFIED_CONSUMER"
    for field in (
        "current_input", "derived_label", "protocol", "failure_behavior",
        "claim_effect", "conflict", "integration_requirement",
    ):
        assert row[field] == semantics[0][field]


def test_semantics_override_selects_one_exact_evidence_record(tmp_path: Path) -> None:
    first = "EMBER_MODEL_URL = config.primary"
    second = "EMBER_MODEL_URL = config.fallback"
    (tmp_path / "server.py").write_text(first + "\n" + second + "\n", encoding="utf-8")
    semantics = [{
        "root_id": "public-master",
        "path": "server.py",
        "category": "serving_runtime",
        "evidence_sha256": hashlib.sha256(first.encode()).hexdigest(),
        "current_input": "config.primary",
        "derived_label": "primary serving endpoint",
        "protocol": "primary configuration",
        "failure_behavior": "fails closed when absent",
        "claim_effect": "selects primary served endpoint",
        "conflict": "endpoint is not checkpoint identity",
        "integration_requirement": "validate manifest before primary adoption",
    }]
    rows = build_census(
        tmp_path,
        tracked_files=["server.py"],
        source_commit=FIXTURE_COMMIT,
        consumer_semantics=semantics,
    )["evidence"]
    assert [row["record_class"] for row in rows] == [
        "VERIFIED_CONSUMER",
        "CANDIDATE_EXECUTABLE_MATCH",
    ]


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


def test_required_memory_world_dream_adapter_update_deletion_and_receipt_surfaces_are_classified(tmp_path: Path) -> None:
    (tmp_path / "loop.py").write_text(
        "temporary_adapter = lora_buffer\n"
        "world_model = dreaming_loop(memory_system)\n"
        "deletion_test = verified_experience_update\n"
        "receipt_bundle = receipt_store\n",
        encoding="utf-8",
    )
    rows = build_census(
        tmp_path, tracked_files=["loop.py"], source_commit=FIXTURE_COMMIT
    )["evidence"]
    categories = {row["category"] for row in rows}
    assert "mechanism_identity" in categories
    assert "receipt_identity" in categories


def test_chained_receipt_store_state_identifier_is_classified(tmp_path: Path) -> None:
    (tmp_path / "store.py").write_text(
        'raise RuntimeError("receipt_store_deleted")\n', encoding="utf-8"
    )
    rows = build_census(
        tmp_path, tracked_files=["store.py"], source_commit=FIXTURE_COMMIT
    )["evidence"]
    assert "receipt_identity" in {row["category"] for row in rows}


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
    assert first["candidate_discovery"]["global_consumer_completeness"] == "NOT_CLAIMED"
    assert first["candidate_discovery"]["unadjudicated_count"] == 2
    assert first["candidate_discovery"]["source_role_counts"] == {
        "EXECUTABLE_CANDIDATE": 2
    }
    rendered = json.dumps(first)
    assert str(public) not in rendered
    assert str(private) not in rendered


def test_conservative_policy_adjudicates_every_exact_candidate_without_invented_credit(
    tmp_path: Path,
) -> None:
    (tmp_path / "runtime.py").write_text(
        "checkpoint = load_model(model_path)\n", encoding="utf-8"
    )
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "identity.md").write_text(
        "checkpoint identity\n", encoding="utf-8"
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_runtime.py").write_text(
        "checkpoint = fake_checkpoint\n", encoding="utf-8"
    )
    policy = {
        "schema": "ember-conservative-candidate-adjudication-v1",
        "policy_id": "fail-closed-static-superset-v1",
        "root_id": "public-master",
        "source_commit": FIXTURE_COMMIT,
        "roles": {
            "EXECUTABLE_CANDIDATE": "CONSERVATIVE_CONSUMER",
            "DOCUMENTATION_EVIDENCE": "REVIEWED_IDENTITY_SOURCE",
            "DATA_EVIDENCE": "REVIEWED_IDENTITY_SOURCE",
            "OPAQUE_FILE": "CONSERVATIVE_CONSUMER",
        },
    }
    census = build_census_set(
        [{
            "root": tmp_path,
            "root_id": "public-master",
            "surface": "public",
            "tracked_files": [
                "runtime.py", "docs/identity.md", "tests/test_runtime.py"
            ],
            "source_commit": FIXTURE_COMMIT,
        }],
        adjudication_policy=policy,
    )
    classes = {row["path"]: row["record_class"] for row in census["evidence"]}
    assert classes == {
        "docs/identity.md": "REVIEWED_IDENTITY_SOURCE",
        "runtime.py": "CONSERVATIVE_CONSUMER",
        "tests/test_runtime.py": "CONSERVATIVE_CONSUMER",
    }
    assert census["candidate_discovery"] == {
        "record_count": 4,
        "unadjudicated_count": 0,
        "source_role_counts": {
            "DOCUMENTATION_EVIDENCE": 1,
                "EXECUTABLE_CANDIDATE": 3,
        },
        "adjudication_counts": {
            "CONSERVATIVE_CONSUMER": 3,
            "REVIEWED_IDENTITY_SOURCE": 1,
        },
        "global_consumer_completeness": "CONSERVATIVE_SUPERSET_COMPLETE",
    }
    for row in census["evidence"]:
        assert row["claim_effect"] == "NO_CREDIT"
        assert row["review_state"] == "POLICY_ADJUDICATED"
        assert row["content_sha256"]
        assert row["line_sha256"]
        assert row["derived_label"]
        assert row["protocol"]
        assert row["failure_behavior"]
        assert row["conflict"]


def test_complete_policy_accounts_for_every_file_and_never_auto_dismisses_tests(
    tmp_path: Path,
) -> None:
    (tmp_path / "runtime.py").write_text("print('no identity token')\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_runtime.py").write_text(
        "def test_stub(): pass\n", encoding="utf-8"
    )
    (tmp_path / "notes.md").write_text("ordinary note\n", encoding="utf-8")
    (tmp_path / "opaque.bin").write_bytes(b"\x00\xff\x00")
    policy = {
        "schema": "ember-conservative-candidate-adjudication-v1",
        "policy_id": "fail-closed-static-superset-v1",
        "root_id": "public-master",
        "source_commit": FIXTURE_COMMIT,
        "roles": {
            "EXECUTABLE_CANDIDATE": "CONSERVATIVE_CONSUMER",
            "DOCUMENTATION_EVIDENCE": "REVIEWED_IDENTITY_SOURCE",
            "DATA_EVIDENCE": "REVIEWED_IDENTITY_SOURCE",
            "OPAQUE_FILE": "CONSERVATIVE_CONSUMER",
        },
    }
    census = build_census_set(
        [{
            "root": tmp_path,
            "root_id": "public-master",
            "surface": "public",
            "tracked_files": [
                "runtime.py", "tests/test_runtime.py", "notes.md", "opaque.bin"
            ],
            "source_commit": FIXTURE_COMMIT,
        }],
        adjudication_policy=policy,
    )
    assert {row["path"] for row in census["evidence"]} == {
        "runtime.py", "tests/test_runtime.py", "notes.md", "opaque.bin"
    }
    by_path = {row["path"]: row for row in census["evidence"]}
    assert by_path["tests/test_runtime.py"]["record_class"] == "CONSERVATIVE_CONSUMER"
    assert by_path["opaque.bin"]["record_class"] == "CONSERVATIVE_CONSUMER"
    assert by_path["notes.md"]["record_class"] == "REVIEWED_IDENTITY_SOURCE"
    assert census["roots"][0]["coverage"]["tracked_candidates"] == 4
    assert census["roots"][0]["coverage"]["files_accounted"] == 4
    assert census["candidate_discovery"]["unadjudicated_count"] == 0
    assert census["candidate_discovery"]["global_consumer_completeness"] == (
        "CONSERVATIVE_SUPERSET_COMPLETE"
    )
    for row in census["evidence"]:
        assert row["derived_label"]
        assert row["protocol"]
        assert row["failure_behavior"]
        assert row["conflict"]


def test_multi_surface_semantics_resolve_only_in_their_declared_root(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "train.py").write_text("optimizer.step()\n", encoding="utf-8")
    line = "EMBER_MODEL_URL = config.endpoint"
    (second / "serve.py").write_text(line + "\n", encoding="utf-8")
    semantics = [{
        "root_id": "second-root", "path": "serve.py",
        "category": "serving_runtime",
        "evidence_sha256": hashlib.sha256(line.encode()).hexdigest(),
        "current_input": "config.endpoint", "derived_label": "selected endpoint",
        "protocol": "configuration selection", "failure_behavior": "fails closed",
        "claim_effect": "selects served subject", "conflict": "endpoint is not identity",
        "integration_requirement": "validate manifest before endpoint adoption",
    }]
    census = build_census_set([
        {"root": first, "root_id": "first-root", "surface": "public", "tracked_files": ["train.py"], "source_commit": "a" * 40},
        {"root": second, "root_id": "second-root", "surface": "live-local", "tracked_files": ["serve.py"], "source_commit": "b" * 40},
    ], consumer_semantics=semantics)
    verified = [row for row in census["evidence"] if row["record_class"] == "VERIFIED_CONSUMER"]
    assert [(row["root_id"], row["path"]) for row in verified] == [("second-root", "serve.py")]


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
