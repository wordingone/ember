#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""test_gen_readme_status_canonical.py -- regression guard for the exact R3
fracture (fspec-R3-1436-20260722T213546Z, section 6): gen_readme_status.py's
old selection rule ("newest lexicographic filename in one glob'd directory")
was location-blind, index-blind, and freshness-blind -- exactly how the two
2026-07-11 twin board receipts (18 minutes apart, different counts, different
locations) produced a README citing the wrong one.

This test proves gen_readme_status.py now derives from
board_index.current_board() instead of that old rule: a fixture deliberately
makes the LEXICOGRAPHICALLY-NEWEST filename in the canonical directory the
SUPERSEDED receipt, and asserts the rendered block still cites the
INDEX-adjudicated current one. It also proves the fail-closed behavior
(a duplicate-epoch RED index raises SystemExit, never a silent fallback) and
the --check exit-code contract, in-process against a fixture repo
(gen_readme_status.README_PATH monkeypatched and restored -- the live repo's
own README.md is never touched).

Follows test_prev_receipt_selection.py's style: plain assert-based test_*
functions, each building its own throwaway tree via
tempfile.TemporaryDirectory, runnable directly or under pytest.

Full rule text: docs/spec/board-canonicality-v1.md
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from scripts.ember_totality import board_index  # noqa: E402
from scripts import gen_readme_status  # noqa: E402


def _receipt_bytes(green, red, unevaluable, pct_green):
    return json.dumps(
        {"summary": {"green": green, "red": red, "unevaluable": unevaluable, "pct_green": pct_green}},
        indent=2,
    ).encode("utf-8") + b"\n"


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if isinstance(data, bytes):
        with open(path, "wb") as fh:
            fh.write(data)
    else:
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(data)


def _write_index(index_path, rows):
    with open(index_path, "w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row))
            fh.write("\n")


def _board_row(rel, sha, ts, basis, green, red, unevaluable, pct_green):
    return {
        "row_type": "board", "ts": ts, "path": rel, "sha256": sha,
        "indexed_ts": ts, "basis": basis,
        "summary": {"green": green, "red": red, "unevaluable": unevaluable, "pct_green": pct_green},
    }


def test_render_cites_index_current_not_lexicographic_newest():
    """The exact R3 fracture, reproduced as a fixture: two board receipts in
    the same canonical directory, where the LEXICOGRAPHICALLY-NEWEST filename
    is the one an explicit supersession row retires (mirrors
    board_twin_adjudication_test.py's "old side never current even when
    newest-ts"). The rendered block must cite the INDEX-current receipt,
    never the newest-named one."""
    with tempfile.TemporaryDirectory() as tmpdir:
        data_root = os.path.join(tmpdir, "scripts", "ember_totality", "receipts-totality")
        os.makedirs(data_root, exist_ok=True)

        name_current = "ember-totality-20260101T000000Z.json"     # older ts -- the TRUE survivor
        name_superseded = "ember-totality-20260102T000000Z.json"  # newer ts, lexicographically greater
        assert name_superseded > name_current, "fixture must place the superseded row lexicographically newest"
        rel_current = "scripts/ember_totality/receipts-totality/" + name_current
        rel_superseded = "scripts/ember_totality/receipts-totality/" + name_superseded

        data_current = _receipt_bytes(9, 3, 0, 75.0)
        data_superseded = _receipt_bytes(4, 8, 0, 33.3)
        _write(os.path.join(data_root, name_current), data_current)
        _write(os.path.join(data_root, name_superseded), data_superseded)

        sha_current = hashlib.sha256(data_current).hexdigest()
        sha_superseded = hashlib.sha256(data_superseded).hexdigest()

        index_path = os.path.join(data_root, "BOARD-INDEX.jsonl")
        _write_index(index_path, [
            _board_row(rel_superseded, sha_superseded, "20260102T000000Z",
                       board_index._unknown_basis(), 4, 8, 0, 33.3),
            _board_row(rel_current, sha_current, "20260101T000000Z",
                       board_index._unknown_basis(), 9, 3, 0, 75.0),
            {
                "row_type": "supersession",
                "old": {"path": rel_superseded, "sha256": sha_superseded},
                "new": {"path": rel_current, "sha256": sha_current},
                "reason": "test: the newest-named run was a botched re-run; the earlier run is the true record",
                "ts": "2026-01-02T00:30:00Z",
                "authority": "test",
            },
        ])

        row, receipt_path, repo_root = gen_readme_status._resolve_current(data_root)
        assert os.path.basename(receipt_path) == name_current, receipt_path

        fresh = board_index.freshness(row, repo_root)
        block = gen_readme_status.render_block(receipt_path, row, fresh)

        assert name_current[: -len(".json")] in block, block
        assert name_superseded[: -len(".json")] not in block, block
        assert "**Binding:**" in block, block
        assert "**Freshness:**" in block, block
        print("PASS: rendered block cites index-current, not the lexicographically-newest filename")


def test_duplicate_red_index_raises_systemexit():
    """A duplicate-epoch RED (D3: two board rows sharing identical
    non-UNKNOWN basis, no covering supersession row) makes
    gen_readme_status._resolve_current raise SystemExit -- fail-closed,
    never a silent fallback to the old newest-glob selection rule."""
    with tempfile.TemporaryDirectory() as tmpdir:
        data_root = os.path.join(tmpdir, "scripts", "ember_totality", "receipts-totality")
        os.makedirs(data_root, exist_ok=True)

        name_a = "ember-totality-20260103T000000Z.json"
        name_b = "ember-totality-20260103T010000Z.json"
        rel_a = "scripts/ember_totality/receipts-totality/" + name_a
        rel_b = "scripts/ember_totality/receipts-totality/" + name_b
        data_a = _receipt_bytes(5, 3, 0, 62.5)
        data_b = _receipt_bytes(5, 3, 0, 62.5)
        _write(os.path.join(data_root, name_a), data_a)
        _write(os.path.join(data_root, name_b), data_b)

        same_basis = {
            "governing_commit": "deadbeef", "goal_sha256": "a" * 64,
            "conditions_spec_sha256": "b" * 64, "probe_set_sha256": "c" * 64,
            "receipts_head_commit": "cafef00d", "subject_identity_sha256": None,
            "subject_identity_source": "test",
        }
        index_path = os.path.join(data_root, "BOARD-INDEX.jsonl")
        _write_index(index_path, [
            _board_row(rel_a, hashlib.sha256(data_a).hexdigest(), "20260103T000000Z", same_basis, 5, 3, 0, 62.5),
            _board_row(rel_b, hashlib.sha256(data_b).hexdigest(), "20260103T010000Z", same_basis, 5, 3, 0, 62.5),
        ])

        try:
            gen_readme_status._resolve_current(data_root)
            raise AssertionError("expected SystemExit on a duplicate-epoch RED index")
        except SystemExit as exc:
            msg = str(exc)
            assert "duplicate-epoch" in msg, msg
            assert "D3" in msg, msg
        print("PASS: duplicate-epoch RED index raises SystemExit, fail-closed")


def test_check_exit_codes_and_rendered_block_fields():
    """--check exit codes (0 when README's block is already current, 1 when
    it would change) plus the required Binding + Freshness lines --
    exercised in-process against a fixture repo. gen_readme_status.README_PATH
    is monkeypatched to a temp file and restored in finally; the live repo's
    own README.md is never opened by this test."""
    with tempfile.TemporaryDirectory() as tmpdir:
        data_root = os.path.join(tmpdir, "scripts", "ember_totality", "receipts-totality")
        os.makedirs(data_root, exist_ok=True)

        name = "ember-totality-20260104T000000Z.json"
        rel = "scripts/ember_totality/receipts-totality/" + name
        data = _receipt_bytes(7, 5, 0, 58.3)
        _write(os.path.join(data_root, name), data)
        sha = hashlib.sha256(data).hexdigest()
        index_path = os.path.join(data_root, "BOARD-INDEX.jsonl")
        _write_index(index_path, [
            _board_row(rel, sha, "20260104T000000Z", board_index._unknown_basis(), 7, 5, 0, 58.3),
        ])

        # Post-#1010 (R2), gen_readme_status.main() manages BOTH the board-status
        # block and the current-subject block. Supply a hermetic fixture for the
        # subject machinery: the real manifest (validate_current_subject_evidence
        # passes against ROOT), rendered into the fixture README + a fixture
        # CONTINUITY.md, seeded already-current so the subject surface never
        # perturbs the board --check assertions. R3 owns board selection only.
        _nl = chr(10)
        subject = gen_readme_status.load_current_subject(gen_readme_status.CURRENT_SUBJECT_PATH)
        subject_block = gen_readme_status.render_current_subject_block(subject)
        continuity_path = os.path.join(tmpdir, "CONTINUITY.md")
        _write(continuity_path, "continuity-preamble" + _nl + subject_block + _nl + "tail" + _nl)

        readme_path = os.path.join(tmpdir, "README.md")
        _write(
            readme_path,
            "before\n" + gen_readme_status.BEGIN_MARKER + "\nstub\n" + gen_readme_status.END_MARKER + _nl + subject_block + "\nafter\n",
        )

        real_readme_path = gen_readme_status.README_PATH
        real_argv = sys.argv
        try:
            gen_readme_status.README_PATH = readme_path

            sys.argv = ["gen_readme_status.py", "--data-root", data_root, "--continuity", continuity_path]
            rc = gen_readme_status.main()
            assert rc == 0, rc
            with open(readme_path, "r", encoding="utf-8") as fh:
                rendered = fh.read()
            assert "**Binding:**" in rendered, rendered
            assert "**Freshness:**" in rendered, rendered
            assert name[: -len(".json")] in rendered, rendered

            sys.argv = ["gen_readme_status.py", "--data-root", data_root, "--continuity", continuity_path, "--check"]
            rc = gen_readme_status.main()
            assert rc == 0, "README already current -- --check must exit 0"

            # Manually revert the rendered receipt id (mirrors acceptance #3's
            # scratch-copy revert-to-the-wrong-receipt check).
            doctored = rendered.replace(name[: -len(".json")], "ember-totality-20260101T000000Z")
            _write(readme_path, doctored)

            sys.argv = ["gen_readme_status.py", "--data-root", data_root, "--continuity", continuity_path, "--check"]
            rc = gen_readme_status.main()
            assert rc == 1, "a reverted README block must make --check exit 1"
        finally:
            gen_readme_status.README_PATH = real_readme_path
            sys.argv = real_argv
        print("PASS: --check exit codes correct; rendered block carries Binding + Freshness lines")


if __name__ == "__main__":
    tests = [
        test_render_cites_index_current_not_lexicographic_newest,
        test_duplicate_red_index_raises_systemexit,
        test_check_exit_codes_and_rendered_block_fields,
    ]
    failures = []
    for t in tests:
        try:
            t()
        except AssertionError as e:
            failures.append((t.__name__, str(e)))
            print("FAIL: " + t.__name__ + ": " + str(e))
    print()
    if failures:
        print("FAIL: " + str(len(failures)) + "/" + str(len(tests)) + " tests failed")
        sys.exit(1)
    print("PASS: All " + str(len(tests)) + " tests passed")
