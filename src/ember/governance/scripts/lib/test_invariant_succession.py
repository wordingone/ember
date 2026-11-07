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


def test_post_succession_stamp_record_verifies():
    rec = inv.stamp_record({"ts": "2026-11-07T15:00:00Z"}, str(REPO))
    assert rec["invariant_sha256"] == inv.INVARIANT_V2_SHA256
    assert inv.verify_record(rec) == inv.INVARIANT_V2_SHA256


def test_pre_succession_stamp_record_pins_v1_and_verifies():
    rec = inv.stamp_record({"ts": "2026-11-07T12:49:29Z"}, str(REPO))
    assert rec["invariant_sha256"] == inv.INVARIANT_SHA256
    assert inv.verify_record(rec) == inv.INVARIANT_SHA256


def test_stamp_record_without_era_time_refuses():
    with pytest.raises(ValueError):
        inv.stamp_record({"x": 1}, str(REPO))


def test_hour_declared_under_v1_keeps_v1_across_the_instant():
    # An hour declared before the succession and trained across it (H40: 11:41-13:35Z) keeps v1 for its own rows.
    row = {"hour_declared_at_utc": "2026-11-07T10:40:00Z", "ts": "2026-11-07T13:30:00Z"}
    assert inv.stamp_record(dict(row), str(REPO))["invariant_sha256"] == inv.INVARIANT_SHA256
    assert inv.verify_record(dict(row, invariant_sha256=inv.INVARIANT_SHA256)) == inv.INVARIANT_SHA256
    with pytest.raises(ValueError):
        inv.verify_record(dict(row, invariant_sha256=inv.INVARIANT_V2_SHA256))


def test_hour_declared_after_the_instant_takes_v2_even_for_early_rows():
    row = {"hour_declared_at_utc": "2026-11-07T14:00:00Z", "ts": "2026-11-07T12:00:00Z"}
    with pytest.raises(ValueError):
        inv.verify_record(dict(row, invariant_sha256=inv.INVARIANT_SHA256))
