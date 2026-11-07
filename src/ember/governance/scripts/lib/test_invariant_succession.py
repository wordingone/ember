# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Red tests for the public succession (docs/authority/SUCCESSION-2026-11-07.md).

v1 (docs/authority/INVARIANT.md) bytes stay untouched and pre-succession receipts keep verifying against v1;
post-succession records must pin v2; a post-succession record pinned to v1 refuses; no backdating to v2.
"""
import hashlib
import importlib.util
import shutil
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[5]
_spec = importlib.util.spec_from_file_location("_ember_invariant_succession_under_test", Path(__file__).with_name("invariant.py"))
inv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(inv)

PRE = "2026-11-07T10:20:11Z"
POST = "2026-11-07T15:00:00Z"


def test_v1_bytes_untouched_and_v2_pinned():
    assert hashlib.sha256((REPO / "docs/authority/INVARIANT.md").read_bytes()).hexdigest() == inv.INVARIANT_SHA256
    assert inv.verify(str(REPO)) == inv.INVARIANT_SHA256
    assert inv.verify_v2(str(REPO)) == inv.INVARIANT_V2_SHA256
    assert (REPO / inv.SUCCESSION_PATH).is_file()


def test_pre_succession_receipt_still_verifies_against_v1():
    assert inv.verify_record({"ts": PRE, "invariant_sha256": inv.INVARIANT_SHA256}) == inv.INVARIANT_SHA256


def test_post_succession_record_pinned_to_v1_refuses():
    with pytest.raises(ValueError, match="post-succession"):
        inv.verify_record({"ts": POST, "invariant_sha256": inv.INVARIANT_SHA256})


def test_post_succession_record_pinned_to_v2_verifies():
    assert inv.verify_record({"generated_at": POST, "invariant_sha256": inv.INVARIANT_V2_SHA256}) == inv.INVARIANT_V2_SHA256


def test_pre_succession_record_pinned_to_v2_refuses_no_backdating():
    with pytest.raises(ValueError, match="pre-succession"):
        inv.verify_record({"ts": PRE, "invariant_sha256": inv.INVARIANT_V2_SHA256})


@pytest.mark.parametrize("record", [{"invariant_sha256": "x"}, {"ts": "yesterday", "invariant_sha256": "x"}, {"ts": "2026-11-07T15:00:00+09:00", "invariant_sha256": "x"}])
def test_missing_or_unparseable_or_non_utc_timestamp_refuses(record):
    with pytest.raises(ValueError):
        inv.verify_record(record)


def test_succession_boundary_is_v2_at_the_declared_instant():
    assert inv.expected_invariant_for(inv.SUCCESSION_AT_UTC) == inv.INVARIANT_V2_SHA256
    assert inv.expected_invariant_for("2026-11-07T12:49:29Z") == inv.INVARIANT_SHA256


def test_v2_verify_refuses_when_v1_is_edited(tmp_path):
    (tmp_path / "docs/authority").mkdir(parents=True)
    shutil.copyfile(REPO / "docs/authority/INVARIANT-v2.md", tmp_path / "docs/authority/INVARIANT-v2.md")
    (tmp_path / "docs/authority/INVARIANT.md").write_bytes((REPO / "docs/authority/INVARIANT.md").read_bytes() + b"\n")
    with pytest.raises(ValueError, match="INVARIANT.md hash mismatch"):
        inv.verify_v2(str(tmp_path))


def test_stamp_v2_writes_v2_hash():
    assert inv.stamp_v2({"x": 1}, str(REPO))["invariant_sha256"] == inv.INVARIANT_V2_SHA256
