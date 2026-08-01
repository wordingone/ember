# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import importlib.util
import json
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACT = REPO_ROOT / "docs" / "ember-restart" / "integration-contract-v1.md"
CURRENT_SUBJECT = REPO_ROOT / "manifests" / "ember-current-subject-v1.json"
GENERATOR = REPO_ROOT / "scripts" / "gen_readme_status.py"


def load_generator():
    spec = importlib.util.spec_from_file_location("gen_readme_status", GENERATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_contract_names_current_step2_truth_and_fail_closed_boundary() -> None:
    text = CONTRACT.read_text(encoding="utf-8")

    assert "BF20F05018991EB611B0623EDD50A00EC30639DA2F8CCAE646F6962F152A2A2B" in text
    assert "2,048 observed text tokens" in text
    assert "1,020,589,568 active parameters" in text
    assert "shared route only" in text
    assert "CHECKPOINT_CANDIDATE_NOT_ADMITTED" in text
    assert "AF954C22FB8FB7A0DC640BFD2E0AB97E8E4CDE989607372FC45C3DB7878699A4" in text
    assert "historical step-1 predecessor" in text
    assert "not sufficiently pretrained" in text
    assert "not capability-admitted" in text


def test_contract_next_execution_requires_runtime_and_receipt_closure_before_gpu() -> None:
    text = CONTRACT.read_text(encoding="utf-8")

    assert "exact step-2 checkpoint is both parent and immutable root" in text
    assert "same-byte hardened-counter realization receipt" in text
    assert "same-open-handle required-shard loading" in text
    assert "No GPU dispatch is authorized by this contract state" in text


def test_current_subject_is_one_closed_machine_readable_identity() -> None:
    payload = json.loads(CURRENT_SUBJECT.read_text(encoding="utf-8"))

    assert payload["schema_version"] == "ember-current-subject-v1"
    assert payload["authority"] == {
        "goal_id": "EMBER-02",
        "workstream_id": "EMBER-02A",
        "next_executed_outcome": (
            "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember"
        ),
    }
    subject = payload["subject"]
    assert subject["checkpoint_manifest_sha256"] == (
        "bf20f05018991eb611b0623edd50a00ec30639da2f8ccae646f6962f152a2a2b"
    )
    assert subject["model_config_sha256"] == (
        "559959894dc603f9fbccbb091b3a084fef23b58d29add05efd14799a9a298ae0"
    )
    assert subject["tokenizer_sha256"] == (
        "2c557e7ffe64706112ea947d056be503005d90b16f64c57ec354267c7e9e9c97"
    )
    assert subject["optimizer_state_sha256"] == (
        "ee864fc9779e7f0d943a08836253726a41f86679360f477a35d5348486f3162b"
    )
    assert subject["token_cursor"] == {
        "global_step": 2,
        "record_index": 2,
        "token_offset": 2048,
        "tokens_seen": 2048,
    }
    assert subject["active_route"] == "shared"
    assert subject["parameters"] == {
        "active": 1_020_589_568,
        "allocated": 3_839_161_856,
        "episode_trainable": 1_020_589_568,
        "served": 3_839_161_856,
        "trainable": 3_839_161_856,
        "unique": 3_839_161_856,
    }
    assert subject["disposition"] == "CHECKPOINT_CANDIDATE_NOT_ADMITTED"
    assert subject["evidence_paths"] == sorted(subject["evidence_paths"])
    assert all(not Path(path).is_absolute() for path in subject["evidence_paths"])


def test_readme_and_continuity_are_generated_from_current_subject() -> None:
    module = load_generator()
    payload = module.load_current_subject(CURRENT_SUBJECT)
    module.validate_current_subject_evidence(payload, REPO_ROOT)
    block = module.render_current_subject_block(payload)

    assert "optimizer state (custody-only, public bytes absent)" in block
    assert block in (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert block in (REPO_ROOT / "CONTINUITY.md").read_text(encoding="utf-8")


def test_readme_human_summary_agrees_with_current_subject() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

    assert "approximately 2.195B owned checkpoint" not in readme
    assert "3.839B allocated, unique, trainable, and served" in readme
    assert "1.021B active and episode-trainable parameters" in readme


def test_subject_surface_mismatches_fail_closed(tmp_path: Path) -> None:
    module = load_generator()
    payload = module.load_current_subject(CURRENT_SUBJECT)
    readme = tmp_path / "README.md"
    continuity = tmp_path / "CONTINUITY.md"
    readme.write_text((REPO_ROOT / "README.md").read_text(encoding="utf-8"), encoding="utf-8")
    continuity.write_text(
        (REPO_ROOT / "CONTINUITY.md").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    readme.write_text(
        readme.read_text(encoding="utf-8").replace(
            payload["subject"]["checkpoint_manifest_sha256"], "a" * 64, 1
        ),
        encoding="utf-8",
    )
    assert not module.subject_surfaces_current(payload, readme, continuity)

    readme.write_text((REPO_ROOT / "README.md").read_text(encoding="utf-8"), encoding="utf-8")
    payload["subject"]["token_cursor"]["tokens_seen"] = 1024
    assert not module.subject_surfaces_current(payload, readme, continuity)


def test_current_subject_schema_rejects_missing_optimizer_and_extra_fields(
    tmp_path: Path,
) -> None:
    module = load_generator()
    payload = json.loads(CURRENT_SUBJECT.read_text(encoding="utf-8"))
    candidate = tmp_path / "subject.json"

    del payload["subject"]["optimizer_state_sha256"]
    candidate.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="subject fields are not closed"):
        module.load_current_subject(candidate)

    payload = json.loads(CURRENT_SUBJECT.read_text(encoding="utf-8"))
    payload["subject"]["unreviewed_identity"] = "forbidden"
    candidate.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="subject fields are not closed"):
        module.load_current_subject(candidate)


def test_current_subject_must_rederive_from_checked_in_public_evidence() -> None:
    module = load_generator()
    payload = module.load_current_subject(CURRENT_SUBJECT)
    module.validate_current_subject_evidence(payload, REPO_ROOT)

    payload["subject"]["checkpoint_manifest_sha256"] = "a" * 64
    with pytest.raises(ValueError, match="public evidence"):
        module.validate_current_subject_evidence(payload, REPO_ROOT)
