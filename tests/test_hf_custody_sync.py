# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""tests/test_hf_custody_sync.py — offline coverage for scripts/hf_custody (issue #1308).

Fully offline: huggingface_hub.HfApi is monkeypatched to a fake that never
touches the network. No test in this file may pass if a real HTTP call is made.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from hf_custody import pin, receipts, sync  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_dataset_dir(root: Path, files: dict[str, bytes]) -> str:
    root.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
    return sync.compute_filelist_manifest(root)["combined_sha256"]


def _inventory_line(**kwargs) -> str:
    return json.dumps(kwargs)


class FakeCommitInfo:
    def __init__(self, oid: str):
        self.oid = oid


class FakeHfApi:
    """Records calls; never touches the network."""

    def __init__(self):
        self.upload_calls: list[dict] = []

    def upload_folder(self, **kwargs):
        self.upload_calls.append(kwargs)
        return FakeCommitInfo(oid="deadbeef" * 5)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def eligible_dataset(tmp_path: Path):
    root = tmp_path / "data" / "arxiv-abstracts"
    combined_sha = _write_dataset_dir(
        root, {"a.jsonl": b"line one\n", "b.jsonl": b"line two\n"}
    )
    return root, combined_sha


@pytest.fixture
def review_dataset(tmp_path: Path):
    root = tmp_path / "data" / "courtlistener"
    root.mkdir(parents=True, exist_ok=True)
    (root / "opinions.csv").write_bytes(b"party,text\nDoe,...\n")
    return root


# ---------------------------------------------------------------------------
# Eligible-row selection
# ---------------------------------------------------------------------------

def test_select_eligible_rows_splits_by_disposition(eligible_dataset, review_dataset, tmp_path):
    root, combined_sha = eligible_dataset
    rows = [
        (1, {
            "local_canonical_path": str(root),
            "disposition": "UPLOAD_ALLOWED",
            "content_hash": combined_sha,
            "hash_method": "sha256_filelist_manifest",
            "hash_status": "complete",
        }),
        (2, {
            "local_canonical_path": str(review_dataset),
            "disposition": "REQUIRES_OPERATOR_REVIEW",
            "disposition_reason": "needs operator sign-off",
        }),
    ]
    eligible, skips = sync.select_eligible_rows(rows)
    assert [r for r, _ in eligible] == [1]
    assert len(skips) == 1
    assert skips[0].row_id == 2
    assert skips[0].status == "skipped"


# ---------------------------------------------------------------------------
# Ineligible-row skip with reason recorded
# ---------------------------------------------------------------------------

def test_ineligible_rows_all_dispositions_skipped_with_reason(tmp_path):
    rows = [
        (1, {"local_canonical_path": "x", "disposition": "REQUIRES_OPERATOR_REVIEW", "disposition_reason": "R1"}),
        (2, {"local_canonical_path": "y", "disposition": "LOCAL_ONLY", "disposition_reason": "R2"}),
        (3, {"local_canonical_path": "z", "disposition": "EXCLUDED", "disposition_reason": "R3"}),
    ]
    eligible, skips = sync.select_eligible_rows(rows)
    assert eligible == []
    assert len(skips) == 3
    for outcome, expected_reason_fragment in zip(skips, ["R1", "R2", "R3"]):
        assert outcome.status == "skipped"
        assert expected_reason_fragment in outcome.reason
        assert outcome.hf_repo is None
        assert outcome.hf_revision is None


def test_full_sync_preserves_skip_rows_for_withheld_dispositions(eligible_dataset, review_dataset, tmp_path):
    root, combined_sha = eligible_dataset
    inv_path = tmp_path / "inventory.jsonl"
    inv_path.write_text(
        "\n".join([
            _inventory_line(
                local_canonical_path=str(root),
                disposition="UPLOAD_ALLOWED",
                content_hash=combined_sha,
                hash_method="sha256_filelist_manifest",
                hash_status="complete",
            ),
            _inventory_line(
                local_canonical_path=str(review_dataset),
                disposition="REQUIRES_OPERATOR_REVIEW",
                disposition_reason="privacy review pending",
            ),
        ]) + "\n",
        encoding="utf-8",
    )
    outcomes = sync.sync(inv_path, repo_id="wordingone/ember-custody", execute=False)
    statuses = {o.row_id: o.status for o in outcomes}
    assert statuses[1] == "dry_run"
    assert statuses[2] == "skipped"
    assert "privacy review pending" in [o.reason for o in outcomes if o.row_id == 2][0]


# ---------------------------------------------------------------------------
# Sha mismatch refusal
# ---------------------------------------------------------------------------

def test_sha_mismatch_refuses_that_row(eligible_dataset, monkeypatch: pytest.MonkeyPatch):
    root, combined_sha = eligible_dataset
    row = {
        "local_canonical_path": str(root),
        "disposition": "UPLOAD_ALLOWED",
        "content_hash": "0" * 64,  # deliberately wrong
        "hash_method": "sha256_filelist_manifest",
        "hash_status": "complete",
    }
    outcome = sync.sync_row(api=None, row_id=1, row=row, repo_id="wordingone/ember-custody", execute=False)
    assert outcome.status == "refused"
    assert "sha256_mismatch" in outcome.reason
    assert outcome.hf_revision is None


def test_sha_match_allows_dry_run_row(eligible_dataset):
    root, combined_sha = eligible_dataset
    row = {
        "local_canonical_path": str(root),
        "disposition": "UPLOAD_ALLOWED",
        "content_hash": combined_sha,
        "hash_method": "sha256_filelist_manifest",
        "hash_status": "complete",
    }
    outcome = sync.sync_row(api=None, row_id=1, row=row, repo_id="wordingone/ember-custody", execute=False)
    assert outcome.status == "dry_run"
    assert outcome.manifest_sha256 == combined_sha


# ---------------------------------------------------------------------------
# Missing-manifest refusal (whole-run fail-closed)
# ---------------------------------------------------------------------------

def test_missing_sha_fields_on_eligible_row_refuses_whole_run(eligible_dataset, tmp_path):
    root, combined_sha = eligible_dataset
    inv_path = tmp_path / "inventory.jsonl"
    inv_path.write_text(
        _inventory_line(
            local_canonical_path=str(root),
            disposition="UPLOAD_ALLOWED",
            # content_hash / hash_method / hash_status all missing
        ) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(sync.InventoryRefusal, match="missing field"):
        sync.sync(inv_path, repo_id="wordingone/ember-custody", execute=False)


def test_unsupported_hash_method_on_eligible_row_refuses_whole_run(eligible_dataset, tmp_path):
    root, combined_sha = eligible_dataset
    inv_path = tmp_path / "inventory.jsonl"
    inv_path.write_text(
        _inventory_line(
            local_canonical_path=str(root),
            disposition="UPLOAD_ALLOWED",
            content_hash="{\"first\": {}}",
            hash_method="sample_first_largest_newest_sha256",
            hash_status="deferred-bulk",
        ) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(sync.InventoryRefusal, match="not verifiable"):
        sync.sync(inv_path, repo_id="wordingone/ember-custody", execute=False)


def test_refusal_uploads_nothing(eligible_dataset, review_dataset, tmp_path, monkeypatch: pytest.MonkeyPatch):
    root, combined_sha = eligible_dataset
    fake_api = FakeHfApi()
    monkeypatch.setattr(sync, "HfApi", lambda: fake_api)

    inv_path = tmp_path / "inventory.jsonl"
    inv_path.write_text(
        "\n".join([
            _inventory_line(local_canonical_path=str(root), disposition="UPLOAD_ALLOWED"),
            _inventory_line(
                local_canonical_path=str(review_dataset),
                disposition="REQUIRES_OPERATOR_REVIEW",
                disposition_reason="pending",
            ),
        ]) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(sync.InventoryRefusal):
        sync.sync(inv_path, repo_id="wordingone/ember-custody", execute=True)
    assert fake_api.upload_calls == []


# ---------------------------------------------------------------------------
# Dry-run performs zero upload calls
# ---------------------------------------------------------------------------

def test_dry_run_default_makes_zero_upload_calls(eligible_dataset, tmp_path, monkeypatch: pytest.MonkeyPatch):
    root, combined_sha = eligible_dataset
    fake_api = FakeHfApi()
    monkeypatch.setattr(sync, "HfApi", lambda: fake_api)

    inv_path = tmp_path / "inventory.jsonl"
    inv_path.write_text(
        _inventory_line(
            local_canonical_path=str(root),
            disposition="UPLOAD_ALLOWED",
            content_hash=combined_sha,
            hash_method="sha256_filelist_manifest",
            hash_status="complete",
        ) + "\n",
        encoding="utf-8",
    )
    outcomes = sync.sync(inv_path, repo_id="wordingone/ember-custody", execute=False)
    assert fake_api.upload_calls == []
    assert outcomes[0].status == "dry_run"
    assert outcomes[0].hf_revision is None


def test_execute_true_calls_upload_folder_exactly_once_per_eligible_row(
    eligible_dataset, tmp_path, monkeypatch: pytest.MonkeyPatch
):
    root, combined_sha = eligible_dataset
    fake_api = FakeHfApi()
    monkeypatch.setattr(sync, "HfApi", lambda: fake_api)

    inv_path = tmp_path / "inventory.jsonl"
    inv_path.write_text(
        _inventory_line(
            local_canonical_path=str(root),
            disposition="UPLOAD_ALLOWED",
            content_hash=combined_sha,
            hash_method="sha256_filelist_manifest",
            hash_status="complete",
        ) + "\n",
        encoding="utf-8",
    )
    outcomes = sync.sync(inv_path, repo_id="wordingone/ember-custody", execute=True)
    assert len(fake_api.upload_calls) == 1
    call = fake_api.upload_calls[0]
    assert call["repo_id"] == "wordingone/ember-custody"
    assert call["repo_type"] == "dataset"
    assert call["folder_path"] == str(root)
    assert outcomes[0].status == "uploaded"
    assert outcomes[0].hf_revision == "deadbeef" * 5


# ---------------------------------------------------------------------------
# Receipt row shape + revision pin present
# ---------------------------------------------------------------------------

def test_receipt_row_shape(eligible_dataset, tmp_path, monkeypatch: pytest.MonkeyPatch):
    root, combined_sha = eligible_dataset
    fake_api = FakeHfApi()
    monkeypatch.setattr(sync, "HfApi", lambda: fake_api)

    row = {
        "local_canonical_path": str(root),
        "disposition": "UPLOAD_ALLOWED",
        "content_hash": combined_sha,
        "hash_method": "sha256_filelist_manifest",
        "hash_status": "complete",
    }
    outcome = sync.sync_row(fake_api, row_id=1, row=row, repo_id="wordingone/ember-custody", execute=True)
    receipt = outcome.to_receipt_dict(ts="20260802T000000Z")

    expected_keys = {
        "ts", "inventory_row_id", "local_path", "disposition", "status", "reason",
        "files_count", "bytes", "manifest_sha256", "hf_repo", "hf_revision",
        "commit_message", "path_in_repo", "sha_convention",
    }
    assert set(receipt.keys()) == expected_keys
    assert receipt["status"] == "uploaded"
    assert receipt["hf_revision"] == "deadbeef" * 5
    assert receipt["hf_repo"] == "wordingone/ember-custody"
    assert receipt["inventory_row_id"] == 1
    assert receipt["manifest_sha256"] == combined_sha


def test_receipts_append_only_jsonl_roundtrip(tmp_path):
    path = tmp_path / "receipts.jsonl"
    receipts.append_receipt(path, {"a": 1})
    receipts.append_receipt(path, {"a": 2})
    rows = receipts.read_receipts(path)
    assert rows == [{"a": 1}, {"a": 2}]
    # append-only: file grows, never rewritten/truncated
    assert path.read_text(encoding="utf-8").count("\n") == 2


# ---------------------------------------------------------------------------
# pin.py output format
# ---------------------------------------------------------------------------

def test_pin_pinned_prefix_format():
    receipt = {
        "hf_repo": "wordingone/ember-custody",
        "hf_revision": "abc123",
        "status": "uploaded",
    }
    assert pin.pinned_prefix(receipt) == "hf://datasets/wordingone/ember-custody@abc123"


def test_pin_rejects_unpinned_receipt():
    for bad in (
        {"hf_repo": "wordingone/ember-custody", "hf_revision": None, "status": "dry_run"},
        {"hf_repo": None, "hf_revision": "abc123", "status": "uploaded"},
        {"hf_repo": "wordingone/ember-custody", "status": "skipped"},
    ):
        with pytest.raises(ValueError):
            pin.pinned_prefix(bad)


def test_pin_cli_prints_only_uploaded_rows(tmp_path, capsys):
    receipts_path = tmp_path / "receipts.jsonl"
    receipts.append_receipt(receipts_path, {
        "inventory_row_id": 1, "hf_repo": "wordingone/ember-custody",
        "hf_revision": "deadbeef", "status": "uploaded",
    })
    receipts.append_receipt(receipts_path, {
        "inventory_row_id": 2, "hf_repo": None, "hf_revision": None, "status": "skipped",
    })
    rc = pin.main(["--receipts", str(receipts_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert out.strip() == "hf://datasets/wordingone/ember-custody@deadbeef"
