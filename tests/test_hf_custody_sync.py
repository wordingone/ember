# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""tests/test_hf_custody_sync.py — offline coverage for scripts/hf_custody (issue #1308).

Fully offline: huggingface_hub.HfApi is monkeypatched to a fake that never
touches the network. No test in this file may pass if a real HTTP call is made.

Covers the PR #1311 review fixes:
  M1 — whole-run verify-then-upload (a single mismatch/collision/symlink
       aborts the ENTIRE run before the first upload_folder call).
  M2 — receipts are appended per-outcome, immediately, so a mid-run failure
       still leaves earlier rows' receipts on disk.
  M3 — hf_revision is always None or a real 40-hex commit sha; no commit_url
       fallback, enforced both at upload time and at receipt-write time.
  M4 — publish_note -> README.md upload + readme_uploaded receipt flag (a);
       dotfiles/.git* excluded from the upload fileset via ignore_patterns,
       while verification still hashes them (b).
  m5 — path_in_repo basename collisions are a hard, whole-run refusal.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from hf_custody import pin, receipts, sync  # noqa: E402

VALID_REVISION = "a" * 40
OTHER_VALID_REVISION = "b" * 40


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


def _eligible_row(local_path: str, content_hash: str, **extra) -> dict:
    return {
        "local_canonical_path": local_path,
        "disposition": "UPLOAD_ALLOWED",
        "content_hash": content_hash,
        "hash_method": "sha256_filelist_manifest",
        "hash_status": "complete",
        **extra,
    }


class FakeCommitInfo:
    def __init__(self, oid: str | None = VALID_REVISION, commit_url: str | None = None):
        self.oid = oid
        self.commit_url = commit_url


class FakeHfApi:
    """Records calls; never touches the network."""

    def __init__(self, oid: str | None = VALID_REVISION):
        self.upload_calls: list[dict] = []
        self.upload_file_calls: list[dict] = []
        self._oid = oid

    def upload_folder(self, **kwargs):
        self.upload_calls.append(kwargs)
        return FakeCommitInfo(oid=self._oid)

    def upload_file(self, **kwargs):
        self.upload_file_calls.append(kwargs)
        return FakeCommitInfo(oid=self._oid)


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
def second_eligible_dataset(tmp_path: Path):
    root = tmp_path / "data" / "gutenberg-expansion"
    combined_sha = _write_dataset_dir(root, {"c.txt": b"gutenberg content\n"})
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
        (1, _eligible_row(str(root), combined_sha)),
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
            _inventory_line(**_eligible_row(str(root), combined_sha)),
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
# M1 — whole-run verification, never per-row
# ---------------------------------------------------------------------------

def test_tampered_row_aborts_whole_run_before_any_upload(
    eligible_dataset, second_eligible_dataset, tmp_path, monkeypatch: pytest.MonkeyPatch
):
    root1, sha1 = eligible_dataset
    root2, sha2 = second_eligible_dataset
    root3 = tmp_path / "data" / "wikimedia-commons-pd"
    sha3 = _write_dataset_dir(root3, {"img.jpg": b"fake-jpeg-bytes"})

    fake_api = FakeHfApi()
    monkeypatch.setattr(sync, "HfApi", lambda: fake_api)

    inv_path = tmp_path / "inventory.jsonl"
    inv_path.write_text(
        "\n".join([
            _inventory_line(**_eligible_row(str(root1), sha1)),
            _inventory_line(**_eligible_row(str(root2), "0" * 64)),  # row 2 tampered
            _inventory_line(**_eligible_row(str(root3), sha3)),
        ]) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(sync.InventoryRefusal, match="row 2"):
        sync.sync(inv_path, repo_id="wordingone/ember-custody", execute=True)

    assert fake_api.upload_calls == []
    assert fake_api.upload_file_calls == []


def test_missing_local_directory_aborts_whole_run(eligible_dataset, tmp_path, monkeypatch: pytest.MonkeyPatch):
    root, sha = eligible_dataset
    fake_api = FakeHfApi()
    monkeypatch.setattr(sync, "HfApi", lambda: fake_api)

    inv_path = tmp_path / "inventory.jsonl"
    inv_path.write_text(
        "\n".join([
            _inventory_line(**_eligible_row(str(root), sha)),
            _inventory_line(**_eligible_row(str(tmp_path / "does-not-exist"), "a" * 64)),
        ]) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(sync.InventoryRefusal, match="not a directory"):
        sync.sync(inv_path, repo_id="wordingone/ember-custody", execute=True)
    assert fake_api.upload_calls == []


def test_symlink_in_dataset_dir_refuses_verification(tmp_path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "data" / "with-symlink"
    root.mkdir(parents=True)
    (root / "real.txt").write_bytes(b"hello")
    (root / "linked.txt").write_bytes(b"placeholder")  # stand-in; is_symlink() faked below

    original_is_symlink = Path.is_symlink

    def fake_is_symlink(self):
        if self.name == "linked.txt":
            return True
        return original_is_symlink(self)

    monkeypatch.setattr(Path, "is_symlink", fake_is_symlink)

    with pytest.raises(ValueError, match="symlink refused"):
        sync.compute_filelist_manifest(root)


def test_symlinked_dataset_row_aborts_whole_run(eligible_dataset, tmp_path, monkeypatch: pytest.MonkeyPatch):
    root, sha = eligible_dataset
    symlinked_root = tmp_path / "data" / "has-symlink"
    symlinked_root.mkdir(parents=True)
    (symlinked_root / "linked.bin").write_bytes(b"x")

    original_is_symlink = Path.is_symlink

    def fake_is_symlink(self):
        if self.name == "linked.bin":
            return True
        return original_is_symlink(self)

    monkeypatch.setattr(Path, "is_symlink", fake_is_symlink)
    fake_api = FakeHfApi()
    monkeypatch.setattr(sync, "HfApi", lambda: fake_api)

    inv_path = tmp_path / "inventory.jsonl"
    inv_path.write_text(
        "\n".join([
            _inventory_line(**_eligible_row(str(root), sha)),
            _inventory_line(**_eligible_row(str(symlinked_root), "c" * 64)),
        ]) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(sync.InventoryRefusal, match="symlink refused"):
        sync.sync(inv_path, repo_id="wordingone/ember-custody", execute=True)
    assert fake_api.upload_calls == []


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
# m5 — path_in_repo collisions
# ---------------------------------------------------------------------------

def test_path_in_repo_collision_aborts_whole_run(tmp_path, monkeypatch: pytest.MonkeyPatch):
    root_a = tmp_path / "lane-a" / "shared-name"
    root_b = tmp_path / "lane-b" / "shared-name"
    sha_a = _write_dataset_dir(root_a, {"x.txt": b"a"})
    sha_b = _write_dataset_dir(root_b, {"y.txt": b"b"})

    fake_api = FakeHfApi()
    monkeypatch.setattr(sync, "HfApi", lambda: fake_api)

    inv_path = tmp_path / "inventory.jsonl"
    inv_path.write_text(
        "\n".join([
            _inventory_line(**_eligible_row(str(root_a), sha_a)),
            _inventory_line(**_eligible_row(str(root_b), sha_b)),
        ]) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(sync.InventoryRefusal, match="collision"):
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
    inv_path.write_text(_inventory_line(**_eligible_row(str(root), combined_sha)) + "\n", encoding="utf-8")
    outcomes = sync.sync(inv_path, repo_id="wordingone/ember-custody", execute=False)
    assert fake_api.upload_calls == []
    assert outcomes[0].status == "dry_run"
    assert outcomes[0].hf_revision is None
    assert outcomes[0].readme_uploaded is False


def test_execute_true_calls_upload_folder_exactly_once_per_eligible_row(
    eligible_dataset, tmp_path, monkeypatch: pytest.MonkeyPatch
):
    root, combined_sha = eligible_dataset
    fake_api = FakeHfApi()
    monkeypatch.setattr(sync, "HfApi", lambda: fake_api)

    inv_path = tmp_path / "inventory.jsonl"
    inv_path.write_text(_inventory_line(**_eligible_row(str(root), combined_sha)) + "\n", encoding="utf-8")
    outcomes = sync.sync(inv_path, repo_id="wordingone/ember-custody", execute=True)
    assert len(fake_api.upload_calls) == 1
    call = fake_api.upload_calls[0]
    assert call["repo_id"] == "wordingone/ember-custody"
    assert call["repo_type"] == "dataset"
    assert call["folder_path"] == str(root)
    assert outcomes[0].status == "uploaded"
    assert outcomes[0].hf_revision == VALID_REVISION


# ---------------------------------------------------------------------------
# M4b — dotfiles/.git* excluded from upload, but not from verification
# ---------------------------------------------------------------------------

def test_upload_folder_receives_dotfile_ignore_patterns(eligible_dataset, tmp_path, monkeypatch: pytest.MonkeyPatch):
    root, combined_sha = eligible_dataset
    fake_api = FakeHfApi()
    monkeypatch.setattr(sync, "HfApi", lambda: fake_api)

    inv_path = tmp_path / "inventory.jsonl"
    inv_path.write_text(_inventory_line(**_eligible_row(str(root), combined_sha)) + "\n", encoding="utf-8")
    sync.sync(inv_path, repo_id="wordingone/ember-custody", execute=True)

    call = fake_api.upload_calls[0]
    assert call["ignore_patterns"] == sync.UPLOAD_IGNORE_PATTERNS
    assert any(".git" in p or ".*" in p for p in call["ignore_patterns"])


def test_verification_includes_dotfiles_census_identical(tmp_path):
    root = tmp_path / "data" / "with-dotfile"
    combined_sha = _write_dataset_dir(root, {"visible.txt": b"a", ".git": b"gitdir: /elsewhere\n"})
    # Removing the dotfile changes the combined hash -> proves it was included.
    (root / ".git").unlink()
    without_dotfile = sync.compute_filelist_manifest(root)["combined_sha256"]
    assert without_dotfile != combined_sha


# ---------------------------------------------------------------------------
# M2 — receipts appended per-outcome, immediately
# ---------------------------------------------------------------------------

def test_partial_run_receipts_persisted_up_to_the_failing_row(
    eligible_dataset, second_eligible_dataset, tmp_path, monkeypatch: pytest.MonkeyPatch
):
    root1, sha1 = eligible_dataset
    root2, sha2 = second_eligible_dataset

    fake_api = FakeHfApi()
    call_count = {"n": 0}

    def flaky_upload_folder(**kwargs):
        call_count["n"] += 1
        fake_api.upload_calls.append(kwargs)
        if call_count["n"] == 2:
            raise RuntimeError("simulated network blip on row 2")
        return FakeCommitInfo(oid=VALID_REVISION)

    fake_api.upload_folder = flaky_upload_folder
    monkeypatch.setattr(sync, "HfApi", lambda: fake_api)

    inv_path = tmp_path / "inventory.jsonl"
    inv_path.write_text(
        "\n".join([
            _inventory_line(**_eligible_row(str(root1), sha1)),
            _inventory_line(**_eligible_row(str(root2), sha2)),
        ]) + "\n",
        encoding="utf-8",
    )
    receipts_path = tmp_path / "receipts.jsonl"

    def on_outcome(outcome):
        receipts.append_receipt(receipts_path, outcome.to_receipt_dict(ts="20260802T000000Z"))

    with pytest.raises(RuntimeError, match="simulated network blip"):
        sync.sync(inv_path, repo_id="wordingone/ember-custody", execute=True, on_outcome=on_outcome)

    rows = receipts.read_receipts(receipts_path)
    assert len(rows) == 2
    row1 = next(r for r in rows if r["inventory_row_id"] == 1)
    row2 = next(r for r in rows if r["inventory_row_id"] == 2)
    assert row1["status"] == "uploaded"
    assert row1["hf_revision"] == VALID_REVISION
    assert row2["status"] == "error"
    assert "simulated network blip" in row2["reason"]
    assert row2["hf_revision"] is None


def test_cli_main_writes_run_refused_receipt_on_whole_run_refusal(
    eligible_dataset, tmp_path, monkeypatch: pytest.MonkeyPatch, capsys
):
    root, combined_sha = eligible_dataset
    fake_api = FakeHfApi()
    monkeypatch.setattr(sync, "HfApi", lambda: fake_api)

    inv_path = tmp_path / "inventory.jsonl"
    inv_path.write_text(_inventory_line(**_eligible_row(str(root), "0" * 64)) + "\n", encoding="utf-8")
    receipts_path = tmp_path / "receipts.jsonl"

    rc = sync.main([
        "--inventory", str(inv_path),
        "--repo-id", "wordingone/ember-custody",
        "--execute",
        "--receipts-path", str(receipts_path),
    ])
    assert rc == 1
    assert fake_api.upload_calls == []
    rows = receipts.read_receipts(receipts_path)
    assert len(rows) == 1
    assert rows[0]["status"] == "run_refused"
    assert rows[0]["inventory_row_id"] is None


# ---------------------------------------------------------------------------
# M3 — no commit_url fallback; hf_revision is always a real sha
# ---------------------------------------------------------------------------

def test_missing_oid_is_a_hard_error_not_a_commit_url_fallback(
    eligible_dataset, tmp_path, monkeypatch: pytest.MonkeyPatch
):
    root, combined_sha = eligible_dataset
    fake_api = FakeHfApi(oid=None)
    fake_api.upload_folder = lambda **kwargs: (
        fake_api.upload_calls.append(kwargs) or FakeCommitInfo(oid=None, commit_url="https://huggingface.co/x/commit/abc")
    )
    monkeypatch.setattr(sync, "HfApi", lambda: fake_api)

    inv_path = tmp_path / "inventory.jsonl"
    inv_path.write_text(_inventory_line(**_eligible_row(str(root), combined_sha)) + "\n", encoding="utf-8")

    receipts_path = tmp_path / "receipts.jsonl"

    def on_outcome(outcome):
        receipts.append_receipt(receipts_path, outcome.to_receipt_dict(ts="20260802T000000Z"))

    with pytest.raises(RuntimeError, match="no valid commit sha"):
        sync.sync(inv_path, repo_id="wordingone/ember-custody", execute=True, on_outcome=on_outcome)

    rows = receipts.read_receipts(receipts_path)
    assert rows[0]["status"] == "error"
    assert rows[0]["hf_revision"] is None
    assert "commit_url" not in json.dumps(rows[0])  # never leaked into the receipt


def test_invalid_oid_format_is_a_hard_error(eligible_dataset, tmp_path, monkeypatch: pytest.MonkeyPatch):
    root, combined_sha = eligible_dataset
    fake_api = FakeHfApi(oid="not-a-real-sha")
    monkeypatch.setattr(sync, "HfApi", lambda: fake_api)

    inv_path = tmp_path / "inventory.jsonl"
    inv_path.write_text(_inventory_line(**_eligible_row(str(root), combined_sha)) + "\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="no valid commit sha"):
        sync.sync(inv_path, repo_id="wordingone/ember-custody", execute=True)


def test_receipts_append_rejects_uploaded_status_without_valid_revision():
    with pytest.raises(ValueError, match="non-pinned"):
        receipts.append_receipt(
            "unused-path-should-never-be-touched.jsonl",
            {"status": "uploaded", "hf_revision": None, "inventory_row_id": 1},
        )


def test_receipts_append_rejects_uploaded_status_with_url_as_revision(tmp_path):
    path = tmp_path / "receipts.jsonl"
    with pytest.raises(ValueError, match="non-pinned"):
        receipts.append_receipt(
            path,
            {"status": "uploaded", "hf_revision": "https://huggingface.co/x/commit/abc", "inventory_row_id": 1},
        )
    assert not path.exists()


# ---------------------------------------------------------------------------
# M4a — publish_note -> README.md upload
# ---------------------------------------------------------------------------

def test_publish_note_uploads_readme_and_sets_receipt_flag(tmp_path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "data" / "lane-285"
    combined_sha = _write_dataset_dir(root, {"manifest.json": b"{}"})
    note = "code_github_clean source is license-unverified; its bytes are NOT included."

    fake_api = FakeHfApi()
    monkeypatch.setattr(sync, "HfApi", lambda: fake_api)

    inv_path = tmp_path / "inventory.jsonl"
    inv_path.write_text(
        _inventory_line(**_eligible_row(str(root), combined_sha, publish_note=note)) + "\n",
        encoding="utf-8",
    )
    outcomes = sync.sync(inv_path, repo_id="wordingone/ember-custody", execute=True)

    assert len(fake_api.upload_file_calls) == 1
    readme_call = fake_api.upload_file_calls[0]
    assert readme_call["path_in_repo"] == "lane-285/README.md"
    assert note in readme_call["path_or_fileobj"].decode("utf-8")
    assert outcomes[0].readme_uploaded is True


def test_publish_note_not_uploaded_in_dry_run(tmp_path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "data" / "lane-285"
    combined_sha = _write_dataset_dir(root, {"manifest.json": b"{}"})
    fake_api = FakeHfApi()
    monkeypatch.setattr(sync, "HfApi", lambda: fake_api)

    inv_path = tmp_path / "inventory.jsonl"
    inv_path.write_text(
        _inventory_line(**_eligible_row(str(root), combined_sha, publish_note="withheld source note")) + "\n",
        encoding="utf-8",
    )
    outcomes = sync.sync(inv_path, repo_id="wordingone/ember-custody", execute=False)
    assert fake_api.upload_file_calls == []
    assert outcomes[0].readme_uploaded is False


def test_row_without_publish_note_never_calls_upload_file(eligible_dataset, tmp_path, monkeypatch: pytest.MonkeyPatch):
    root, combined_sha = eligible_dataset
    fake_api = FakeHfApi()
    monkeypatch.setattr(sync, "HfApi", lambda: fake_api)

    inv_path = tmp_path / "inventory.jsonl"
    inv_path.write_text(_inventory_line(**_eligible_row(str(root), combined_sha)) + "\n", encoding="utf-8")
    outcomes = sync.sync(inv_path, repo_id="wordingone/ember-custody", execute=True)
    assert fake_api.upload_file_calls == []
    assert outcomes[0].readme_uploaded is False


# ---------------------------------------------------------------------------
# Receipt row shape + revision pin present
# ---------------------------------------------------------------------------

def test_receipt_row_shape(eligible_dataset, tmp_path, monkeypatch: pytest.MonkeyPatch):
    root, combined_sha = eligible_dataset
    fake_api = FakeHfApi()
    monkeypatch.setattr(sync, "HfApi", lambda: fake_api)

    verified = sync.verify_all_eligible_rows([(1, _eligible_row(str(root), combined_sha))])
    outcome = sync.upload_verified_row(fake_api, verified[0], repo_id="wordingone/ember-custody", execute=True)
    receipt = outcome.to_receipt_dict(ts="20260802T000000Z")

    expected_keys = {
        "ts", "inventory_row_id", "local_path", "disposition", "status", "reason",
        "files_count", "bytes", "manifest_sha256", "hf_repo", "hf_revision",
        "commit_message", "path_in_repo", "readme_uploaded", "sha_convention",
    }
    assert set(receipt.keys()) == expected_keys
    assert receipt["status"] == "uploaded"
    assert receipt["hf_revision"] == VALID_REVISION
    assert receipt["hf_repo"] == "wordingone/ember-custody"
    assert receipt["inventory_row_id"] == 1
    assert receipt["manifest_sha256"] == combined_sha
    assert receipt["readme_uploaded"] is False


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
        "hf_revision": VALID_REVISION,
        "status": "uploaded",
    }
    assert pin.pinned_prefix(receipt) == f"hf://datasets/wordingone/ember-custody@{VALID_REVISION}"


def test_pin_rejects_unpinned_receipt():
    for bad in (
        {"hf_repo": "wordingone/ember-custody", "hf_revision": None, "status": "dry_run"},
        {"hf_repo": None, "hf_revision": VALID_REVISION, "status": "uploaded"},
        {"hf_repo": "wordingone/ember-custody", "status": "skipped"},
    ):
        with pytest.raises(ValueError):
            pin.pinned_prefix(bad)


def test_pin_rejects_url_or_short_hash_as_revision():
    for bad_revision in ("https://huggingface.co/x/commit/abc", "abc123", VALID_REVISION.upper(), VALID_REVISION + "x"):
        with pytest.raises(ValueError, match="not a valid pinned commit sha"):
            pin.pinned_prefix({"hf_repo": "wordingone/ember-custody", "hf_revision": bad_revision, "status": "uploaded"})


def test_pin_cli_prints_only_uploaded_rows(tmp_path, capsys):
    receipts_path = tmp_path / "receipts.jsonl"
    receipts.append_receipt(receipts_path, {
        "inventory_row_id": 1, "hf_repo": "wordingone/ember-custody",
        "hf_revision": VALID_REVISION, "status": "uploaded",
    })
    receipts.append_receipt(receipts_path, {
        "inventory_row_id": 2, "hf_repo": None, "hf_revision": None, "status": "skipped",
    })
    rc = pin.main(["--receipts", str(receipts_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert out.strip() == f"hf://datasets/wordingone/ember-custody@{VALID_REVISION}"
