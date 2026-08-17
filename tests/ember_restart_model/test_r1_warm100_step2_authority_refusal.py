# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RECEIPT = (
    ROOT
    / "receipts"
    / "ember-restart-3b"
    / "r1-warm100-step2-authority-refusal-v1.json"
)


def _payload_sha256(payload: dict) -> str:
    unsigned = {key: value for key, value in payload.items() if key != "payload_sha256"}
    encoded = json.dumps(
        unsigned, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def test_step2_authority_refusal_is_closed_and_content_addressed() -> None:
    payload = json.loads(RECEIPT.read_text(encoding="utf-8"))

    assert payload["schema_version"] == "ember-r1-step2-authority-refusal-v1"
    assert payload["result"] == "REFUSED"
    assert payload["payload_sha256"] == _payload_sha256(payload)
    assert payload["synthesized_values"] == []
    assert payload["training_launched"] is False
    assert payload["gpu_allocated"] is False
    assert {ground["code"] for ground in payload["grounds"]} == {
        "MISSING_ADMISSIBLE_OWNED_RUNG_AUTHORITY",
        "HISTORICAL_SUBJECT_CONFLICTS_WITH_FRESH_GENESIS_DECISION",
    }


def test_every_missing_field_names_the_authorities_that_failed_to_supply_it() -> None:
    payload = json.loads(RECEIPT.read_text(encoding="utf-8"))
    missing = payload["missing_fields"]

    assert len(missing) == 18
    assert len({row["field"] for row in missing}) == len(missing)
    for row in missing:
        assert row["consulted_authorities"]
        assert all(
            authority in payload["authorities_consulted"]
            for authority in row["consulted_authorities"]
        )
        assert row["finding"] == "NOT_SUPPLIED"


def test_historical_archive_is_excluded_by_both_hash_conflicts() -> None:
    payload = json.loads(RECEIPT.read_text(encoding="utf-8"))
    archive = payload["excluded_archive"]

    assert archive["seat_claim_status"] == "NON_ADMISSIBLE"
    assert archive["raw_sha256"] == "b29eac5837d41779e21321d27a0637376fbee12509d167121b186c53c5838581"
    assert archive["hash_conflicts"] == [
        {
            "field": "parameter_receipt_sha256",
            "archive": "e3565f1e73e5384480c19cfc2007141905d8fa1787538d4fcb282319ccde8cfd",
            "tracked_authority": "f3cd8773c9db9e83a1f3566ecb7c02d33be185dde619ea7b4e4c7050bd44e042",
        },
        {
            "field": "trusted_verifier_registry_sha256",
            "archive": "72d9e738a3e7849481d26ff2011735362d74d16d0fb3b006d719d0df941ee04f",
            "tracked_authority": "845ae1cdc34b4df29c4428cda2f2cee8d045a1db9df831e99e4a6f4c1960309e",
        },
    ]


def test_fresh_genesis_decision_and_d011_are_explicitly_bound() -> None:
    payload = json.loads(RECEIPT.read_text(encoding="utf-8"))
    decision = payload["fresh_genesis_decision"]

    assert decision["issue_comment_id"] == 5287388117
    assert decision["subject"] == "FRESH_GENESIS"
    assert decision["historical_checkpoint_disposition"] == "NEVER_RESTORE"
    assert decision["authority_matrix_row"] == "D-011"
    assert payload["subject_checkpoint_sha256"] == "bf20f05018991eb611b0623edd50a00ec30639da2f8ccae646f6962f152a2a2b"


def test_tracked_authority_bytes_reopen_to_the_receipted_hashes() -> None:
    payload = json.loads(RECEIPT.read_text(encoding="utf-8"))

    for authority_name in ("tracked_execution_authorities", "tracked_current_subject"):
        authority = payload["authorities_consulted"][authority_name]
        assert hashlib.sha256(
            (ROOT / authority["path"]).read_bytes()
        ).hexdigest() == authority["sha256"]

    validator = payload["validator"]
    assert hashlib.sha256((ROOT / validator["path"]).read_bytes()).hexdigest() == validator["sha256"]
    decision = payload["fresh_genesis_decision"]
    matrix = ROOT / decision["authority_matrix_path"]
    assert (
        hashlib.sha256(matrix.read_bytes()).hexdigest()
        == decision["authority_matrix_sha256"]
    )
    assert "| D-011 | ENFORCED;HISTORICAL_ONLY |" in matrix.read_text(encoding="utf-8")
