# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Offline coverage for ember.data.hf_custody (issue #1308).

Fully offline: huggingface_hub.HfApi is monkeypatched to a fake that never
touches the network. No test in this file may pass if a real HTTP call is made.

Covers the PR #1311 review fixes:
  M1 — whole-run verify-then-upload (a single mismatch/collision/symlink
       aborts the ENTIRE run before the first create_commit call).
  M2 — receipts are appended per-outcome, immediately, so a mid-run failure
       still leaves earlier rows' receipts on disk.
  M3 — hf_revision is always None or a real 40-hex commit sha; no commit_url
       fallback, enforced both at upload time and at receipt-write time.
  M4 — publish_note -> README.md upload + readme_uploaded receipt flag (a);
       dotfiles/.git* excluded from the upload fileset via UPLOAD_IGNORE_
       PATTERNS filtering, while verification still hashes them (b).
  m5 — path_in_repo basename collisions are a hard, whole-run refusal.

Also covers issue #1313 (PR #1311 re-review nits N1/N4):
  N1 — a row's README.md (from publish_note) is one more operation in the
       SAME create_commit call as its data files, never a second, trailing
       commit — see the "N1" tests near the M4a section.
  N4 — with N1 fixed there is only one commit per row, so its oid
       (hf_revision) already covers the README whenever readme_uploaded is
       true; there is no separate README-commit revision left unrecorded.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

from ember.data.hf_custody import pin, receipts, sync

VALID_REVISION = "a" * 40
OTHER_VALID_REVISION = "b" * 40
SEPARATE_ROOT_REFUSAL = "HF_CUSTODY_SEPARATE_ROOT_REFUSED"


def _assert_single_declared_root(root: Path) -> None:
    declared = root / "src" / "ember" / "data" / "hf_custody"
    legacy = root / "scripts" / "hf_custody"
    declared_present = (declared / "__init__.py").is_file()
    legacy_present = (legacy / "__init__.py").is_file()
    if not declared_present or legacy_present:
        failure_class = (
            "declared_and_legacy_python_packages_present"
            if declared_present and legacy_present
            else "declared_python_package_missing"
        )
        raise AssertionError(f"{SEPARATE_ROOT_REFUSAL}: {failure_class}")


def test_hf_custody_has_one_declared_root_and_refuses_two(tmp_path: Path):
    _assert_single_declared_root(ROOT)
    declared = tmp_path / "src" / "ember" / "data" / "hf_custody"
    legacy = tmp_path / "scripts" / "hf_custody"
    shutil.copytree(ROOT / "src" / "ember" / "data" / "hf_custody", declared)
    shutil.copytree(declared, legacy)

    with pytest.raises(AssertionError, match=SEPARATE_ROOT_REFUSAL):
        _assert_single_declared_root(tmp_path)


def test_hf_custody_import_resolves_to_declared_root():
    assert Path(sync.__file__).resolve().parent == (
        ROOT / "src" / "ember" / "data" / "hf_custody"
    ).resolve()


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
        "hash_method": sync.SUPPORTED_HASH_METHOD,
        "hash_status": "complete",
        **extra,
    }


class FakeCommitInfo:
    def __init__(self, oid: str | None = VALID_REVISION, commit_url: str | None = None):
        self.oid = oid
        self.commit_url = commit_url


class FakeHfApi:
    """Records calls; never touches the network.

    N1 fix: sync.py issues exactly ONE `create_commit` call per row — data
    files and, when present, the row's README.md as operations in the SAME
    commit — instead of an `upload_folder` call followed by a separate,
    trailing `upload_file` call.
    """

    def __init__(self, oid: str | None = VALID_REVISION):
        self.create_commit_calls: list[dict] = []
        self._oid = oid

    def create_commit(self, **kwargs):
        self.create_commit_calls.append(kwargs)
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

    assert fake_api.create_commit_calls == []


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
    assert fake_api.create_commit_calls == []


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
    assert fake_api.create_commit_calls == []


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
    assert fake_api.create_commit_calls == []


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
    assert fake_api.create_commit_calls == []


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
    assert fake_api.create_commit_calls == []
    assert outcomes[0].status == "dry_run"
    assert outcomes[0].hf_revision is None
    assert outcomes[0].readme_uploaded is False


def test_execute_true_calls_create_commit_exactly_once_per_eligible_row(
    eligible_dataset, tmp_path, monkeypatch: pytest.MonkeyPatch
):
    root, combined_sha = eligible_dataset
    fake_api = FakeHfApi()
    monkeypatch.setattr(sync, "HfApi", lambda: fake_api)

    inv_path = tmp_path / "inventory.jsonl"
    inv_path.write_text(_inventory_line(**_eligible_row(str(root), combined_sha)) + "\n", encoding="utf-8")
    outcomes = sync.sync(inv_path, repo_id="wordingone/ember-custody", execute=True)
    assert len(fake_api.create_commit_calls) == 1
    call = fake_api.create_commit_calls[0]
    assert call["repo_id"] == "wordingone/ember-custody"
    assert call["repo_type"] == "dataset"
    operation_paths = {op.path_in_repo for op in call["operations"]}
    assert operation_paths == {f"{root.name}/a.jsonl", f"{root.name}/b.jsonl"}
    assert outcomes[0].status == "uploaded"
    assert outcomes[0].hf_revision == VALID_REVISION


# ---------------------------------------------------------------------------
# M4b — dotfiles/.git* excluded from upload, but not from verification
# ---------------------------------------------------------------------------

def test_create_commit_operations_exclude_dotfiles_and_git(tmp_path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "data" / "with-dotfile"
    combined_sha = _write_dataset_dir(root, {"visible.txt": b"a", ".git": b"gitdir: /elsewhere\n"})
    fake_api = FakeHfApi()
    monkeypatch.setattr(sync, "HfApi", lambda: fake_api)

    inv_path = tmp_path / "inventory.jsonl"
    inv_path.write_text(_inventory_line(**_eligible_row(str(root), combined_sha)) + "\n", encoding="utf-8")
    sync.sync(inv_path, repo_id="wordingone/ember-custody", execute=True)

    call = fake_api.create_commit_calls[0]
    operation_paths = {op.path_in_repo for op in call["operations"]}
    assert operation_paths == {f"{root.name}/visible.txt"}
    assert not any(".git" in p for p in operation_paths)


def test_create_commit_operations_exclude_hf_cache_dir(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Review rework (issue #1313): huggingface_hub's `upload_folder` always
    excludes `.cache/huggingface/**` on top of any caller-supplied
    `ignore_patterns` — the old implementation got that for free. The N1
    fix's `create_commit` path has no such implicit behavior, so
    UPLOAD_IGNORE_PATTERNS now unions in
    HF_UPLOAD_FOLDER_DEFAULT_IGNORE_PATTERNS explicitly. This fixtures a row
    with a `.cache/huggingface` directory and proves: (a) verification still
    hashes it (census-identical, M4b), (b) the create_commit operations for
    the row do NOT include it."""
    root = tmp_path / "data" / "with-hf-cache"
    combined_sha = _write_dataset_dir(
        root,
        {
            "visible.txt": b"a",
            ".cache/huggingface/token": b"should-never-publish",
            ".cache/huggingface/download/blob.lock": b"lockfile-content",
        },
    )

    manifest = sync.compute_filelist_manifest(root)
    manifest_names = {f["name"] for f in manifest["files"]}
    assert ".cache/huggingface/token" in manifest_names
    assert ".cache/huggingface/download/blob.lock" in manifest_names

    fake_api = FakeHfApi()
    monkeypatch.setattr(sync, "HfApi", lambda: fake_api)

    inv_path = tmp_path / "inventory.jsonl"
    inv_path.write_text(_inventory_line(**_eligible_row(str(root), combined_sha)) + "\n", encoding="utf-8")
    sync.sync(inv_path, repo_id="wordingone/ember-custody", execute=True)

    call = fake_api.create_commit_calls[0]
    operation_paths = {op.path_in_repo for op in call["operations"]}
    assert operation_paths == {f"{root.name}/visible.txt"}
    assert not any(".cache" in p for p in operation_paths)


def test_hf_default_ignore_patterns_is_subset_of_installed_library():
    """Pin sync.HF_UPLOAD_FOLDER_DEFAULT_IGNORE_PATTERNS (inlined, not
    imported, because it names an internal huggingface_hub module
    attribute that could move or change without notice) against whatever
    the ACTUALLY INSTALLED huggingface_hub version enforces. If a future
    hub version widens `upload_folder`'s always-applied denylist beyond
    what's inlined here, this test fails loudly instead of this tool
    silently under-filtering relative to what upload_folder used to
    guarantee."""
    try:
        from huggingface_hub.hf_api import DEFAULT_IGNORE_PATTERNS as installed_default_ignore_patterns
    except ImportError:
        pytest.skip(
            "huggingface_hub.hf_api.DEFAULT_IGNORE_PATTERNS is not importable "
            "in this installed huggingface_hub version — nothing to pin against"
        )
    assert set(installed_default_ignore_patterns) <= set(sync.HF_UPLOAD_FOLDER_DEFAULT_IGNORE_PATTERNS)


def test_verification_includes_dotfiles_census_identical(tmp_path):
    root = tmp_path / "data" / "with-dotfile"
    combined_sha = _write_dataset_dir(root, {"visible.txt": b"a", ".git": b"gitdir: /elsewhere\n"})
    # Removing the dotfile changes the combined hash -> proves it was included.
    (root / ".git").unlink()
    without_dotfile = sync.compute_filelist_manifest(root)["combined_sha256"]
    assert without_dotfile != combined_sha


# ---------------------------------------------------------------------------
# Regression fixture: both manifest constructions, pinned to hand-verified
# golden digests (2026-08-02 root-cause fix). This is the "future drift"
# guard requested by the review — if either compute_filelist_manifest or
# compute_sizeonly_manifest's byte-level construction ever changes by
# accident, this test catches it even though every other test in this file
# only checks internal self-consistency (recompute == recompute), never an
# externally-fixed value.
#
# The fixture's expected digests were independently computed (see the git
# history for the one-off script used) and cross-validated against the real
# Workstream A inventory: compute_sizeonly_manifest reproduces the census's
# original content_hash for rows 13 and 17 exactly, and compute_
# filelist_manifest is the construction inventory-v1.jsonl's UPLOAD_ALLOWED
# rows were re-minted to on 2026-08-02 (remint_hashes.py).
# ---------------------------------------------------------------------------

GOLDEN_SIZEONLY_SHA256 = "a84448abeb672764a00e843d0322d6732d0f3c42c3bc1e2eba261ff603466ab3"
GOLDEN_CONTENT_SHA256 = "6b7be1e36636d41bc678c3fd39da3c416a6696eb627f39b9ee8cdd201908cde2"


@pytest.fixture
def golden_fixture_dir(tmp_path: Path):
    root = tmp_path / "golden-fixture"
    root.mkdir()
    (root / "a.txt").write_bytes(b"hello\n")
    sub = root / "sub"
    sub.mkdir()
    (sub / "b.bin").write_bytes(b"\x00\x01\x02")
    return root


def test_compute_sizeonly_manifest_matches_golden_digest(golden_fixture_dir):
    assert sync.compute_sizeonly_manifest(golden_fixture_dir) == GOLDEN_SIZEONLY_SHA256


def test_compute_filelist_manifest_matches_golden_digest(golden_fixture_dir):
    manifest = sync.compute_filelist_manifest(golden_fixture_dir)
    assert manifest["combined_sha256"] == GOLDEN_CONTENT_SHA256


def test_sizeonly_and_content_constructions_diverge_on_same_size_tamper(tmp_path):
    """The whole point of the M4/root-cause fix: a same-size content change
    must be INVISIBLE to compute_sizeonly_manifest (it never reads bytes)
    but MUST be caught by compute_filelist_manifest (it hashes bytes)."""
    root = tmp_path / "tamper-fixture"
    root.mkdir()
    (root / "a.txt").write_bytes(b"hello\n")  # 6 bytes

    sizeonly_before = sync.compute_sizeonly_manifest(root)
    content_before = sync.compute_filelist_manifest(root)["combined_sha256"]

    (root / "a.txt").write_bytes(b"AAAAAA")  # same 6 bytes, different content

    sizeonly_after = sync.compute_sizeonly_manifest(root)
    content_after = sync.compute_filelist_manifest(root)["combined_sha256"]

    assert sizeonly_after == sizeonly_before  # size-only is blind to this
    assert content_after != content_before  # content-based catches it


def test_sizeonly_manifest_includes_dotfiles_and_uses_posix_relpath(tmp_path):
    root = tmp_path / "sizeonly-dotfile-fixture"
    root.mkdir()
    (root / "visible.txt").write_bytes(b"x")
    (root / ".git").write_bytes(b"gitdir: /elsewhere\n")
    with_dotfile = sync.compute_sizeonly_manifest(root)
    (root / ".git").unlink()
    without_dotfile = sync.compute_sizeonly_manifest(root)
    assert with_dotfile != without_dotfile


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

    def flaky_create_commit(**kwargs):
        call_count["n"] += 1
        fake_api.create_commit_calls.append(kwargs)
        if call_count["n"] == 2:
            raise RuntimeError("simulated network blip on row 2")
        return FakeCommitInfo(oid=VALID_REVISION)

    fake_api.create_commit = flaky_create_commit
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
    assert fake_api.create_commit_calls == []
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
    fake_api.create_commit = lambda **kwargs: (
        fake_api.create_commit_calls.append(kwargs) or FakeCommitInfo(oid=None, commit_url="https://huggingface.co/x/commit/abc")
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
# M4a / N1 (issue #1313) — publish_note -> README.md folded into the SAME
# commit as the row's data files, never a second, trailing commit.
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

    # N1: exactly ONE create_commit call for the row — no second, trailing
    # commit for the README.
    assert len(fake_api.create_commit_calls) == 1
    operations = fake_api.create_commit_calls[0]["operations"]
    readme_ops = [op for op in operations if op.path_in_repo == "lane-285/README.md"]
    data_ops = [op for op in operations if op.path_in_repo == "lane-285/manifest.json"]
    assert len(readme_ops) == 1
    assert len(data_ops) == 1
    assert note in readme_ops[0].path_or_fileobj.decode("utf-8")
    assert outcomes[0].readme_uploaded is True

    # N4: with one commit, the README's revision IS the row's hf_revision —
    # nothing left unrecorded.
    assert outcomes[0].hf_revision == VALID_REVISION


def test_publish_note_readme_and_data_share_one_commit_operations_list(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """N1, explicit atomicity pin: the README operation is APPENDED to the
    exact same `operations` list passed to `create_commit` as the data
    files — not a second call, not a second commit_message, not a second
    oid. A single create_commit failure (e.g. the fake below raising) means
    NEITHER the data nor the README lands, which is the atomicity N1 asked
    for (a README failure can no longer leave data published unlabeled)."""
    root = tmp_path / "data" / "lane-285"
    combined_sha = _write_dataset_dir(root, {"manifest.json": b"{}"})
    note = "withheld source note"

    fake_api = FakeHfApi()

    def failing_create_commit(**kwargs):
        fake_api.create_commit_calls.append(kwargs)
        raise RuntimeError("simulated commit failure")

    fake_api.create_commit = failing_create_commit
    monkeypatch.setattr(sync, "HfApi", lambda: fake_api)

    inv_path = tmp_path / "inventory.jsonl"
    inv_path.write_text(
        _inventory_line(**_eligible_row(str(root), combined_sha, publish_note=note)) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="simulated commit failure"):
        sync.sync(inv_path, repo_id="wordingone/ember-custody", execute=True)

    # The one (failed) create_commit call already carried the README
    # operation alongside the data — proof there was never a second,
    # separate README commit that could "succeed" after a data failure.
    assert len(fake_api.create_commit_calls) == 1
    operations = fake_api.create_commit_calls[0]["operations"]
    assert any(op.path_in_repo == "lane-285/README.md" for op in operations)
    assert any(op.path_in_repo == "lane-285/manifest.json" for op in operations)


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
    assert fake_api.create_commit_calls == []
    assert outcomes[0].readme_uploaded is False


def test_row_without_publish_note_never_adds_readme_operation(eligible_dataset, tmp_path, monkeypatch: pytest.MonkeyPatch):
    root, combined_sha = eligible_dataset
    fake_api = FakeHfApi()
    monkeypatch.setattr(sync, "HfApi", lambda: fake_api)

    inv_path = tmp_path / "inventory.jsonl"
    inv_path.write_text(_inventory_line(**_eligible_row(str(root), combined_sha)) + "\n", encoding="utf-8")
    outcomes = sync.sync(inv_path, repo_id="wordingone/ember-custody", execute=True)
    operations = fake_api.create_commit_calls[0]["operations"]
    assert not any(op.path_in_repo.endswith("README.md") for op in operations)
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
