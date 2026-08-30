#!/usr/bin/env python3
"""
Unit tests for build_claims_index.py against synthetic receipt fixtures.

No real receipts/ tree is touched — every test builds its own tmp_path
receipts directory so the suite stays fast and independent of corpus size.
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "src" / "ember" / "governance" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))
from build_claims_index import build_index, render_claims_md, write_outputs  # noqa: E402


def _write(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _make_fixture_tree(root: Path) -> Path:
    """Layout: 5 files under root/receipts/ — 2 real receipts (one nested),
    1 non-informative data dump, 1 unparseable file, 1 non-dict JSON list."""
    receipts = root / "receipts"

    _write(
        receipts / "foo-bar-20260101T000000Z.json",
        json.dumps(
            {
                "ticket": "FOO-BAR",
                "ts": "20260101T000000Z",
                "issue": 123,
                "verdict": "PASS",
                "pass": True,
            }
        ),
    )

    _write(
        receipts / "nested" / "baz-1-20260102T000000Z.json",
        json.dumps(
            {
                "ticket": "BAZ-1",
                "ts": "20260102T000000Z",
                "issue": "#456",
                "candidate_claim": "beats baseline by 2x",
                "pass_condition": True,
            }
        ),
    )

    # Raw data dump: no ticket/issue/verdict/pass/*claim*/*condition* keys.
    _write(
        receipts / "raw-rows-20260103T000000Z.json",
        json.dumps({"rows": [1, 2, 3], "source_url": "https://example.test"}),
    )

    # Malformed JSON — must be skipped, never crash the scan.
    _write(receipts / "broken-20260104T000000Z.json", "{not valid json")

    # Top-level JSON list (not a dict) — also must be skipped cleanly.
    _write(receipts / "list-shaped-20260105T000000Z.json", json.dumps([1, 2, 3]))

    return receipts


def test_build_index_counts_and_rows(tmp_path):
    receipts_dir = _make_fixture_tree(tmp_path)
    rows, stats = build_index(receipts_dir)

    assert stats["scanned"] == 5
    assert stats["indexed"] == 2
    assert stats["unparseable"] == 1
    assert stats["non_dict"] == 1
    assert stats["non_informative"] == 1

    paths = sorted(r["path"] for r in rows)
    assert paths == [
        "receipts/foo-bar-20260101T000000Z.json",
        "receipts/nested/baz-1-20260102T000000Z.json",
    ]


def test_build_index_extracts_expected_fields(tmp_path):
    receipts_dir = _make_fixture_tree(tmp_path)
    rows, _ = build_index(receipts_dir)
    by_path = {r["path"]: r for r in rows}

    foo = by_path["receipts/foo-bar-20260101T000000Z.json"]
    assert foo["ticket"] == "FOO-BAR"
    assert foo["ts"] == "20260101T000000Z"
    assert foo["issue"] == "123"
    assert foo["verdict"] == "PASS"
    assert foo["pass"] is True
    assert "claim_fields" not in foo

    baz = by_path["receipts/nested/baz-1-20260102T000000Z.json"]
    assert baz["ticket"] == "BAZ-1"
    assert baz["issue"] == "456"  # leading '#' stripped
    assert baz["claim_fields"]["candidate_claim"] == "beats baseline by 2x"
    assert baz["claim_fields"]["pass_condition"] == "true"


def test_rows_sorted_by_path_for_deterministic_output(tmp_path):
    receipts_dir = _make_fixture_tree(tmp_path)
    rows, _ = build_index(receipts_dir)
    paths = [r["path"] for r in rows]
    assert paths == sorted(paths)


def test_write_outputs_is_deterministic(tmp_path):
    receipts_dir = _make_fixture_tree(tmp_path)
    rows, stats = build_index(receipts_dir)
    write_outputs(receipts_dir, rows)

    index_path = receipts_dir / "INDEX.jsonl"
    claims_path = receipts_dir / "CLAIMS.md"
    assert index_path.exists()
    assert claims_path.exists()

    first_index = index_path.read_bytes()
    first_claims = claims_path.read_bytes()

    # Re-run against the same fixtures (skip the two files we just wrote
    # ourselves) and confirm byte-identical regeneration.
    rows2, _ = build_index(receipts_dir)
    write_outputs(receipts_dir, rows2)

    assert index_path.read_bytes() == first_index
    assert claims_path.read_bytes() == first_claims

    lines = first_index.decode("utf-8").splitlines()
    assert len(lines) == 2
    for line in lines:
        parsed = json.loads(line)
        assert "path" in parsed


def test_index_jsonl_ignores_its_own_prior_output(tmp_path):
    """INDEX.jsonl itself must never be re-ingested as a receipt on rebuild."""
    receipts_dir = _make_fixture_tree(tmp_path)
    rows, _ = build_index(receipts_dir)
    write_outputs(receipts_dir, rows)

    rows2, stats2 = build_index(receipts_dir)
    assert stats2["scanned"] == 5  # INDEX.jsonl is .jsonl, not .json — excluded by glob
    assert len(rows2) == 2


def test_claims_md_groups_by_issue_and_ticket(tmp_path):
    receipts_dir = _make_fixture_tree(tmp_path)
    rows, _ = build_index(receipts_dir)
    md = render_claims_md(rows)

    assert "### #123" in md
    assert "### #456" in md
    assert "### FOO-BAR" in md
    assert "### BAZ-1" in md
    assert "receipts/foo-bar-20260101T000000Z.json" in md
    assert "receipts/nested/baz-1-20260102T000000Z.json" in md


def test_unparseable_and_non_informative_files_never_crash_scan(tmp_path):
    receipts_dir = _make_fixture_tree(tmp_path)
    # Should not raise despite broken JSON and a non-dict top-level file.
    rows, stats = build_index(receipts_dir)
    assert stats["unparseable"] + stats["non_dict"] + stats["non_informative"] == 3
