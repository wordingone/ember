# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


def _module():
    import importlib.util

    path = REPO_ROOT / "scripts" / "branch_inventory.py"
    spec = importlib.util.spec_from_file_location("branch_inventory", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def test_parse_worktrees_preserves_detached_and_branch_rows():
    module = _module()
    rows = module.parse_worktree_porcelain(
        "worktree B:/one\nHEAD " + "a" * 40 + "\nbranch refs/heads/topic\n\n"
        "worktree B:/two\nHEAD " + "b" * 40 + "\ndetached\n\n"
    )
    assert rows == [
        {"path": "B:/one", "head_sha": "a" * 40, "branch": "refs/heads/topic", "detached": False},
        {"path": "B:/two", "head_sha": "b" * 40, "branch": None, "detached": True},
    ]


def test_default_nonancestor_files_park_and_empty_branch_retires():
    module = _module()
    rows = module.classify_candidates(
        [
            {
                "identity": "refs/heads/topic",
                "head_sha": "a" * 40,
                "unique_files": ["scripts/new.py"],
                "comparison": "diverged",
                "worktree_path_sha256s": [],
            },
            {
                "identity": "refs/heads/empty",
                "head_sha": "b" * 40,
                "unique_files": [],
                "comparison": "tree_equivalent",
                "worktree_path_sha256s": [],
            },
        ],
        overrides={},
    )
    by_identity = {row["identity"]: row for row in rows}
    assert by_identity["refs/heads/topic"]["disposition"] == "PARK"
    assert by_identity["refs/heads/topic"]["files"][0]["disposition"] == "PARK"
    assert by_identity["refs/heads/topic"]["files"][0]["revisit_condition"]
    assert by_identity["refs/heads/empty"]["disposition"] == "RETIRE"
    assert by_identity["refs/heads/empty"]["files"] == []


def test_land_requires_explicit_complete_override():
    module = _module()
    candidate = {
        "identity": "refs/heads/topic",
        "head_sha": "a" * 40,
        "unique_files": ["scripts/new.py"],
        "comparison": "diverged",
        "worktree_path_sha256s": [],
    }
    with pytest.raises(module.InventoryError):
        module.classify_candidates(
            [candidate],
            overrides={"refs/heads/topic": {"scripts/new.py": {"disposition": "LAND"}}},
        )
    rows = module.classify_candidates(
        [candidate],
        overrides={
            "refs/heads/topic": {
                "scripts/new.py": {
                    "disposition": "LAND",
                    "reason": "reviewed missing implementation",
                    "revisit_condition": "land through PR #1",
                }
            }
        },
    )
    assert rows[0]["disposition"] == "LAND"


def test_receipt_and_continuity_block_are_content_bound(tmp_path):
    module = _module()
    receipt = module.build_receipt(
        repository="wordingone/ember",
        master_sha="c" * 40,
        captured_at="2026-07-28T00:00:00Z",
        rows=[
            {
                "identity": "refs/heads/topic",
                "head_sha": "a" * 40,
                "comparison": "diverged",
                "unlanded_file_count": 1,
                "disposition": "PARK",
                "reason": "unreviewed",
                "revisit_condition": "review",
                "worktree_path_sha256s": [],
                "files": [
                    {
                        "path": "scripts/new.py",
                        "disposition": "PARK",
                        "reason": "unreviewed",
                        "revisit_condition": "review",
                    }
                ],
            }
        ],
        ignored_artifacts=[],
    )
    assert receipt["ticket"] == "EMBER-BRANCH-INVENTORY"
    assert receipt["ts"] == receipt["captured_at"]
    assert "receipt_sha256" in receipt["sha_convention"]
    assert receipt["invariant_sha256"] == module.INVARIANT_SHA256
    manifest = tmp_path / "receipts" / "branch-inventory" / "current.json"
    manifest.parent.mkdir(parents=True)
    module._write_json(manifest, receipt)
    block = module.render_continuity_block(receipt, "receipts/branch-inventory/current.json")
    assert "refs/heads/topic" not in block
    assert "identity" not in receipt["rows"][0]
    assert receipt["rows"][0]["identity_sha256"] == module.sha256_bytes(b"refs/heads/topic")
    assert receipt["rows"][0]["identity_sha256"] in block
    assert "scripts/new.py" not in json.dumps(receipt)
    assert module.sha256_bytes(b"scripts/new.py") in receipt["path_dictionary"]
    continuity = tmp_path / "CONTINUITY.md"
    continuity.write_text(f"before\n{block}\nafter\n", encoding="utf-8")
    module.check_inventory(
        manifest_path=manifest,
        continuity_path=continuity,
        now=datetime(2026, 7, 28, tzinfo=timezone.utc),
        max_age_days=7,
    )
    continuity.write_text(continuity.read_text(encoding="utf-8").replace("PARK", "LAND", 1), encoding="utf-8")
    with pytest.raises(module.InventoryError):
        module.check_inventory(
            manifest_path=manifest,
            continuity_path=continuity,
            now=datetime(2026, 7, 28, tzinfo=timezone.utc),
            max_age_days=7,
        )


def test_stale_inventory_fails_closed(tmp_path):
    module = _module()
    receipt = module.build_receipt(
        repository="wordingone/ember",
        master_sha="c" * 40,
        captured_at="2026-07-01T00:00:00Z",
        rows=[],
        ignored_artifacts=[],
    )
    manifest = tmp_path / "receipts" / "branch-inventory" / "current.json"
    manifest.parent.mkdir(parents=True)
    module._write_json(manifest, receipt)
    continuity = tmp_path / "CONTINUITY.md"
    continuity.write_text(
        module.render_continuity_block(receipt, "receipts/branch-inventory/current.json"),
        encoding="utf-8",
    )
    with pytest.raises(module.InventoryError, match="stale"):
        module.check_inventory(
            manifest_path=manifest,
            continuity_path=continuity,
            now=datetime(2026, 7, 28, tzinfo=timezone.utc),
            max_age_days=7,
        )



def test_master_binding_allows_only_capture_or_introducing_commit(tmp_path, monkeypatch):
    module = _module()
    receipt = module.build_receipt(
        repository="wordingone/ember",
        master_sha="c" * 40,
        captured_at="2026-07-28T00:00:00Z",
        rows=[],
        ignored_artifacts=[],
    )
    manifest = tmp_path / "receipts" / "branch-inventory" / "current.json"
    manifest.parent.mkdir(parents=True)
    module._write_json(manifest, receipt)
    continuity = tmp_path / "CONTINUITY.md"
    continuity.write_text(module.render_continuity_block(receipt, "receipts/branch-inventory/current.json"), encoding="utf-8")

    def introducing_commit(_repo, *args):
        if args[0] == "rev-parse":
            return SimpleNamespace(stdout="d" * 40 + "\n")
        if args[0] == "merge-base":
            return SimpleNamespace(stdout="c" * 40 + "\n")
        return SimpleNamespace(stdout="3\n")

    monkeypatch.setattr(module, "_run_git", introducing_commit)
    module.check_inventory(
        manifest_path=manifest,
        continuity_path=continuity,
        repo_path=tmp_path,
        now=datetime(2026, 7, 28, tzinfo=timezone.utc),
    )

    def later_commit(_repo, *args):
        if args[0] == "rev-parse":
            return SimpleNamespace(stdout="d" * 40 + "\n")
        if args[0] == "merge-base":
            return SimpleNamespace(stdout="c" * 40 + "\n")
        return SimpleNamespace(stdout="4\n")

    monkeypatch.setattr(module, "_run_git", later_commit)
    with pytest.raises(module.InventoryError, match="master binding is stale"):
        module.check_inventory(
            manifest_path=manifest,
            continuity_path=continuity,
            repo_path=tmp_path,
            now=datetime(2026, 7, 28, tzinfo=timezone.utc),
        )
def test_continuity_refresh_invokes_inventory_gate():
    source = (REPO_ROOT / "scripts" / "gen_readme_status.py").read_text(encoding="utf-8")
    assert "check_inventory(" in source
    assert "--branch-inventory-max-age-days" in source

def test_file_set_content_hash_tamper_fails():
    module = _module()
    classified = module.classify_candidates(
        [{"identity": "refs/heads/topic", "head_sha": "a" * 40, "unique_files": ["a.txt"], "comparison": "diverged", "worktree_path_sha256s": []}],
        overrides={},
    )
    receipt = module.build_receipt(repository="wordingone/ember", master_sha="c" * 40, captured_at="2026-07-28T00:00:00Z", rows=classified, ignored_artifacts=[])
    digest = next(iter(receipt["file_sets"]))
    receipt["path_dictionary"][0] = module.sha256_bytes(b"other.txt")
    unsigned = dict(receipt)
    unsigned.pop("receipt_sha256")
    receipt["receipt_sha256"] = module.sha256_bytes(module.canonical_json(unsigned))
    with pytest.raises(module.InventoryError, match="file_set content hash mismatch"):
        module.verify_receipt(receipt)


def test_file_identity_dictionary_is_hash_sorted_and_private():
    module = _module()
    classified = module.classify_candidates(
        [{"identity": "refs/heads/topic", "head_sha": "a" * 40, "unique_files": ["z.txt", "a.txt"], "comparison": "diverged", "worktree_path_sha256s": []}],
        overrides={},
    )
    receipt = module.build_receipt(repository="wordingone/ember", master_sha="c" * 40, captured_at="2026-07-28T00:00:00Z", rows=classified, ignored_artifacts=[])
    expected = sorted([module.sha256_bytes(b"a.txt"), module.sha256_bytes(b"z.txt")])
    assert receipt["path_dictionary"] == expected
    assert list(receipt["file_sets"].values()) == [[0, 1]]
    encoded = json.dumps(receipt)
    assert "a.txt" not in encoded and "z.txt" not in encoded
def test_closed_schema_and_disposition_tamper_fail():
    module = _module()
    classified = module.classify_candidates(
        [{"identity": "refs/heads/topic", "head_sha": "a" * 40, "unique_files": ["a.txt"], "comparison": "diverged", "worktree_path_sha256s": []}],
        overrides={},
    )
    original = module.build_receipt(repository="wordingone/ember", master_sha="c" * 40, captured_at="2026-07-28T00:00:00Z", rows=classified, ignored_artifacts=[])

    def resign(candidate):
        unsigned = dict(candidate)
        unsigned.pop("receipt_sha256", None)
        candidate["receipt_sha256"] = module.sha256_bytes(module.canonical_json(unsigned))
        return candidate

    extra = json.loads(json.dumps(original))
    extra["unexpected"] = True
    with pytest.raises(module.InventoryError, match="fields are not closed"):
        module.verify_receipt(resign(extra))

    mismatch = json.loads(json.dumps(original))
    mismatch["rows"][0]["disposition"] = "LAND"
    with pytest.raises(module.InventoryError, match="does not match file dispositions"):
        module.verify_receipt(resign(mismatch))

    orphan = json.loads(json.dumps(original))
    orphan_digest = module.sha256_bytes(module.canonical_json([]))
    orphan["file_sets"][orphan_digest] = []
    with pytest.raises(module.InventoryError, match="unreferenced"):
        module.verify_receipt(resign(orphan))