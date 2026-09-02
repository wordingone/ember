# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Fail-closed properties of the CONTINUITY board-status generator.

Each test here was RED against the generator as it stood at master
1619621a8aeacb70b45887c52040f18b54618f04, where an unbound receipt rendered as
LEGACY_UNBOUND and no code path hashed a receipt's bytes at all. They exercise
render_block -- the function main() itself calls -- rather than a helper fixture.
"""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


REPO_ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
GENERATOR = REPO_ROOT / "src" / "ember" / "governance" / "scripts" / "gen_readme_status.py"


def load_generator():
    spec = importlib.util.spec_from_file_location("gen_readme_status_failclosed", GENERATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def clean_provenance() -> dict:
    """A run-tree binding that tree_provenance accepts as CURRENT_CLEAN.

    The chain tests bind their fixtures properly so they exercise the same render
    path production uses, rather than passing an opt-out that would mask the
    behavior under test.
    """
    sha = "1" * 40
    return {
        "run_tree_sha": sha,
        "remote_master_sha": sha,
        "remote_master_source": "LS_REMOTE",
        "tree_is_stale": False,
        "behind_by": 0,
        "tree_dirty": [],
        "stale_tree_override": False,
        "provenance_status": "CURRENT_CLEAN",
        "publishable_as_current": True,
    }


def write_receipt(directory: Path, ts: str, *, bound: bool = True, **extra) -> Path:
    path = directory / f"ember-totality-{ts}.json"
    payload = {"ts": ts, "summary": {"green": 1, "total": 1}}
    if bound:
        payload["run_tree_provenance"] = clean_provenance()
    payload.update(extra)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --- P3: an unverifiable provenance basis must refuse, not render -------------


def test_receipt_without_tree_provenance_is_refused_by_default(tmp_path: Path) -> None:
    module = load_generator()
    receipt = write_receipt(tmp_path, "20260801T052815Z", bound=False)

    with pytest.raises(ValueError, match="no run-tree provenance"):
        module.render_block(receipt)


def test_unbound_receipt_renders_only_under_explicit_optout(tmp_path: Path) -> None:
    module = load_generator()
    receipt = write_receipt(tmp_path, "20260801T052815Z", bound=False)

    block = module.render_block(receipt, allow_unbound_tree=True)

    assert "LEGACY_UNBOUND" in block


# --- P2: the on-disk sha must equal the declared sha --------------------------


def test_declared_predecessor_sha_must_match_on_disk_bytes(tmp_path: Path) -> None:
    module = load_generator()
    write_receipt(tmp_path, "20260731T000000Z")
    receipt = write_receipt(
        tmp_path,
        "20260801T000000Z",
        prev_totality_receipt_sha256="0" * 64,
        chain_verification={"chain_ok": True, "chain_break": None},
    )

    with pytest.raises(ValueError, match="chain is broken"):
        module.render_block(receipt)


def test_self_reported_chain_ok_does_not_substitute_for_the_computed_digest(
    tmp_path: Path,
) -> None:
    module = load_generator()
    predecessor = write_receipt(tmp_path, "20260731T000000Z")
    receipt = write_receipt(
        tmp_path,
        "20260801T000000Z",
        prev_totality_receipt_sha256="f" * 64,
        chain_verification={"chain_ok": True, "chain_break": None, "note": "trust me"},
    )

    with pytest.raises(ValueError) as excinfo:
        module.render_block(receipt)

    # The verdict must quote the digest hashed from disk, not echo the self-report.
    assert sha256_of(predecessor) in str(excinfo.value)


def test_matching_predecessor_sha_renders(tmp_path: Path) -> None:
    module = load_generator()
    predecessor = write_receipt(tmp_path, "20260731T000000Z")
    receipt = write_receipt(
        tmp_path,
        "20260801T000000Z",
        prev_totality_receipt_sha256=sha256_of(predecessor),
    )

    block = module.render_block(receipt)

    assert "ember-totality-20260801T000000Z" in block


def test_missing_predecessor_sha_is_refused_when_a_predecessor_exists(
    tmp_path: Path,
) -> None:
    module = load_generator()
    write_receipt(tmp_path, "20260731T000000Z")
    receipt = write_receipt(tmp_path, "20260801T000000Z")

    with pytest.raises(ValueError, match="omits prev_totality_receipt_sha256"):
        module.render_block(receipt)


def test_malformed_predecessor_sha_is_refused(tmp_path: Path) -> None:
    module = load_generator()
    write_receipt(tmp_path, "20260731T000000Z")
    receipt = write_receipt(
        tmp_path, "20260801T000000Z", prev_totality_receipt_sha256="NOT-A-SHA"
    )

    with pytest.raises(ValueError, match="lowercase SHA-256"):
        module.render_block(receipt)


# --- P4: supersession must bind the exact predecessor ------------------------


def test_receipt_chain_gap_is_refused(tmp_path: Path) -> None:
    """A chain that skips a receipt is broken even though the declared sha is real."""
    module = load_generator()
    oldest = write_receipt(tmp_path, "20260730T000000Z")
    middle = write_receipt(tmp_path, "20260731T000000Z")
    receipt = write_receipt(
        tmp_path,
        "20260801T000000Z",
        prev_totality_receipt_sha256=sha256_of(oldest),
    )

    with pytest.raises(ValueError, match="chain is broken") as excinfo:
        module.render_block(receipt)

    assert middle.name in str(excinfo.value)


def test_predecessor_is_the_immediate_one_in_selection_order(tmp_path: Path) -> None:
    module = load_generator()
    write_receipt(tmp_path, "20260730T000000Z")
    middle = write_receipt(tmp_path, "20260731T000000Z")
    newest = write_receipt(tmp_path, "20260801T000000Z")

    found = module.receipt_chain_predecessor(newest)

    assert found is not None
    assert Path(found).resolve() == middle.resolve()


def test_first_receipt_has_no_predecessor_and_still_renders(tmp_path: Path) -> None:
    module = load_generator()
    receipt = write_receipt(tmp_path, "20260801T000000Z")

    assert module.receipt_chain_predecessor(receipt) is None
    assert "ember-totality-20260801T000000Z" in module.render_block(receipt)


def test_unchained_receipt_renders_only_under_explicit_optout(tmp_path: Path) -> None:
    module = load_generator()
    write_receipt(tmp_path, "20260731T000000Z")
    receipt = write_receipt(tmp_path, "20260801T000000Z")

    block = module.render_block(receipt, allow_unchained=True)

    assert "ember-totality-20260801T000000Z" in block
