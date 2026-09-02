#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""TDD test suite for C-CUSTODY probe (issue #381).

Tests the three failure shapes:
  (a) untracked-in-canonical
  (b) unparseable JSON
  (c) cited-path-missing

Plus a clean GREEN case.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# Keep the test runner reproducible on default Windows CP1252 consoles.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def run_probe(root_dir):
    """Run test_c_custody.py with EMBER_TOTALITY_ROOT set to root_dir.
    Returns (stdout_line, returncode)."""
    probe_path = os.path.join(
        os.path.dirname(__file__), "..", "ember_totality", "test_c_custody.py"
    )
    try:
        result = subprocess.run(
            [sys.executable, probe_path],
            cwd=root_dir,
            capture_output=True,
            text=True,
            timeout=30,
            env={**os.environ, "EMBER_TOTALITY_ROOT": root_dir},
        )
        lines = result.stdout.strip().split("\n")
        first_line = lines[0] if lines else ""
        return first_line, result.returncode
    except Exception as e:
        return f"ERROR: {e}", 1


def run_probe_full(root_dir):
    """Same as run_probe but also returns stderr -- needed to assert on the
    disclosed-rejection line the pattern validator prints there.
    Returns (stdout_first_line, stderr_text, returncode)."""
    probe_path = os.path.join(
        os.path.dirname(__file__), "..", "ember_totality", "test_c_custody.py"
    )
    try:
        result = subprocess.run(
            [sys.executable, probe_path],
            cwd=root_dir,
            capture_output=True,
            text=True,
            timeout=30,
            env={**os.environ, "EMBER_TOTALITY_ROOT": root_dir},
        )
        lines = result.stdout.strip().split("\n")
        first_line = lines[0] if lines else ""
        return first_line, result.stderr, result.returncode
    except Exception as e:
        return f"ERROR: {e}", "", 1


def test_shape_a_untracked():
    """Shape (a): untracked-in-canonical — untracked file in receipts/."""
    with tempfile.TemporaryDirectory() as tmpdir:
        receipts_dir = os.path.join(tmpdir, "receipts")
        os.makedirs(receipts_dir)

        # Create an untracked receipt file
        receipt_file = os.path.join(receipts_dir, "untracked-file.json")
        receipt_data = {
            "ticket": "TEST-UNTRACKED",
            "ts": "20260707T000000Z",
            "status": "test",
        }
        with open(receipt_file, "w", encoding="utf-8") as f:
            json.dump(receipt_data, f)

        # Initialize a git repo and DON'T track this file
        subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=tmpdir,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmpdir,
            capture_output=True,
        )

        # Create a tracked dummy file so we have something in the index
        dummy = os.path.join(tmpdir, ".gitkeep")
        Path(dummy).touch()
        subprocess.run(["git", "add", ".gitkeep"], cwd=tmpdir, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=tmpdir,
            capture_output=True,
        )

        output, _ = run_probe(tmpdir)
        assert "RED" in output, f"Expected RED for untracked file, got: {output}"
        assert "UNTRACKED" in output or "custody" in output.lower(), (
            f"Expected UNTRACKED/custody mention, got: {output}"
        )
        print("✓ Shape (a) untracked: PASS")


def test_post_landing_untracked_is_red():
    """A new untracked receipt after a receipt landing is still a RED violation."""
    with tempfile.TemporaryDirectory() as tmpdir:
        receipts_dir = os.path.join(tmpdir, "receipts")
        os.makedirs(receipts_dir)

        landed = os.path.join(receipts_dir, "landed-receipt.json")
        with open(landed, "w", encoding="utf-8") as f:
            json.dump({"ticket": "TEST-LANDED", "status": "success"}, f)

        subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmpdir, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=tmpdir, capture_output=True)
        subprocess.run(["git", "add", "receipts/"], cwd=tmpdir, capture_output=True)
        subprocess.run(["git", "commit", "-m", "land receipt"], cwd=tmpdir, capture_output=True)

        silent = os.path.join(receipts_dir, "silent-after-landing.json")
        with open(silent, "w", encoding="utf-8") as f:
            json.dump({"ticket": "TEST-SILENT", "status": "success"}, f)
        landing_ts = int(subprocess.run(
            ["git", "log", "-1", "--format=%ct"],
            cwd=tmpdir, capture_output=True, text=True, check=True,
        ).stdout.strip())
        os.utime(silent, (landing_ts + 60, landing_ts + 60))

        output, _ = run_probe(tmpdir)
        assert "RED" in output, (
            "A post-landing silent untracked receipt must be RED, got: "
            f"{output}"
        )
        assert "untracked=1" in output, f"Expected untracked=1 in output, got: {output}"


def test_self_allowlist_cannot_authorize_itself():
    """An untracked receipt cannot make itself trusted via __allowlist_untracked."""
    with tempfile.TemporaryDirectory() as tmpdir:
        receipts_dir = os.path.join(tmpdir, "receipts")
        os.makedirs(receipts_dir)
        receipt_file = os.path.join(receipts_dir, "self-whitelist.json")
        with open(receipt_file, "w", encoding="utf-8") as f:
            json.dump({"__allowlist_untracked": ["self-whitelist.json"], "status": "ok"}, f)

        subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmpdir, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=tmpdir, capture_output=True)
        Path(os.path.join(tmpdir, ".gitkeep")).touch()
        subprocess.run(["git", "add", ".gitkeep"], cwd=tmpdir, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=tmpdir, capture_output=True)

        output, _ = run_probe(tmpdir)
        assert "RED" in output, f"A receipt must not self-authorize its untracked status, got: {output}"
        assert "untracked=1" in output, f"Expected explicit untracked failure, got: {output}"
        print("self-allowlist negative: PASS")

def test_allowlist_wrong_workstream_not_honored():
    """An allowlist authority file bound to a DIFFERENT goal/workstream must
    grant no authority here -- a copied/mismatched allowlist should never
    silently launder an untracked receipt into GREEN (round-2 repair, PR951)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        receipts_dir = os.path.join(tmpdir, "receipts")
        os.makedirs(receipts_dir)

        # Untracked receipt whose basename the (wrong-workstream) allowlist claims to permit.
        receipt_file = os.path.join(receipts_dir, "staging-untracked.json")
        with open(receipt_file, "w", encoding="utf-8") as f:
            json.dump({"ticket": "TEST-WRONG-WORKSTREAM", "status": "test"}, f)

        allowlist_dir = os.path.join(tmpdir, "scripts", "ember_totality")
        os.makedirs(allowlist_dir, exist_ok=True)
        allowlist_path = os.path.join(allowlist_dir, "custody-allowlist.json")
        with open(allowlist_path, "w", encoding="utf-8") as f:
            json.dump({
                "goal_id": "OTHER-99",
                "workstream_id": "OTHER-99Z",
                "next_executed_outcome": "unrelated outcome string",
                "schema_version": "ember-c-custody-allowlist-v1",
                "allowed_receipt_basenames": ["staging-untracked.json"],
            }, f)

        subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmpdir, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=tmpdir, capture_output=True)
        subprocess.run(["git", "add", "scripts/"], cwd=tmpdir, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init wrong-workstream allowlist"], cwd=tmpdir, capture_output=True)

        output, rc = run_probe(tmpdir)
        assert rc == 0, f"Probe must never crash, got rc={rc}: {output}"
        assert "RED" in output, (
            "A wrong-workstream allowlist must not authorize the untracked "
            f"receipt, got: {output}"
        )
        print("wrong-workstream allowlist negative: PASS")


def test_allowlist_missing_identity_field_not_honored():
    """An allowlist missing one of the three bound identity fields is
    schema-invalid and grants no authority, even with a correct schema_version
    and a pattern that would otherwise match (round-2 repair, PR951)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        receipts_dir = os.path.join(tmpdir, "receipts")
        os.makedirs(receipts_dir)

        receipt_file = os.path.join(receipts_dir, "staging-untracked2.json")
        with open(receipt_file, "w", encoding="utf-8") as f:
            json.dump({"ticket": "TEST-MISSING-FIELD", "status": "test"}, f)

        allowlist_dir = os.path.join(tmpdir, "scripts", "ember_totality")
        os.makedirs(allowlist_dir, exist_ok=True)
        allowlist_path = os.path.join(allowlist_dir, "custody-allowlist.json")
        with open(allowlist_path, "w", encoding="utf-8") as f:
            # workstream_id missing entirely -- goal_id/next_executed_outcome/
            # schema_version all correct.
            json.dump({
                "goal_id": "EMBER-02",
                "next_executed_outcome": "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember",
                "schema_version": "ember-c-custody-allowlist-v1",
                "allowed_receipt_basenames": ["staging-untracked2.json"],
            }, f)

        subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmpdir, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=tmpdir, capture_output=True)
        subprocess.run(["git", "add", "scripts/"], cwd=tmpdir, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init missing-field allowlist"], cwd=tmpdir, capture_output=True)

        output, rc = run_probe(tmpdir)
        assert rc == 0, f"Probe must never crash, got rc={rc}: {output}"
        assert "RED" in output, (
            "An allowlist missing a required identity field must not "
            f"authorize the untracked receipt, got: {output}"
        )
        print("missing-identity-field allowlist negative: PASS")


def test_allowlist_malformed_pattern_no_crash():
    """A malformed allowlist pattern (invalid regex metacharacters, e.g. an
    unbalanced bracket) must never crash the probe and must never silently
    authorize an unrelated untracked receipt (round-2 repair, PR951)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        receipts_dir = os.path.join(tmpdir, "receipts")
        os.makedirs(receipts_dir)

        # Untracked receipt that does NOT match the malformed pattern below.
        receipt_file = os.path.join(receipts_dir, "not-matching-anything.json")
        with open(receipt_file, "w", encoding="utf-8") as f:
            json.dump({"ticket": "TEST-MALFORMED-PATTERN", "status": "test"}, f)

        allowlist_dir = os.path.join(tmpdir, "scripts", "ember_totality")
        os.makedirs(allowlist_dir, exist_ok=True)
        allowlist_path = os.path.join(allowlist_dir, "custody-allowlist.json")
        with open(allowlist_path, "w", encoding="utf-8") as f:
            json.dump({
                "goal_id": "EMBER-02",
                "workstream_id": "EMBER-02A",
                "next_executed_outcome": "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember",
                "schema_version": "ember-c-custody-allowlist-v1",
                # Unbalanced bracket combined with a wildcard -- invalid
                # regex when naively translated by string substitution (the
                # pre-repair matcher only regex-compiles patterns containing
                # "*" or "?").
                "allowed_receipt_basenames": ["staging-[unbalanced*.json"],
            }, f)

        subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmpdir, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=tmpdir, capture_output=True)
        subprocess.run(["git", "add", "scripts/"], cwd=tmpdir, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init malformed-pattern allowlist"], cwd=tmpdir, capture_output=True)

        output, rc = run_probe(tmpdir)
        assert rc == 0, f"A malformed allowlist pattern must never crash the probe, got rc={rc}: {output}"
        assert "RED" in output, (
            "The unrelated untracked receipt must still be flagged; a "
            f"malformed pattern must never silently authorize it, got: {output}"
        )
        print("malformed-pattern allowlist negative: PASS")


def test_authority_file_untracked_not_honored():
    """An untracked custody-allowlist.json file (present on disk but never
    git-added) must grant no authority -- only a git-tracked, committed
    authority surface can waive custody (round-2 repair, PR951 clause 1)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        receipts_dir = os.path.join(tmpdir, "receipts")
        os.makedirs(receipts_dir)
        receipt_file = os.path.join(receipts_dir, "staging-untracked3.json")
        with open(receipt_file, "w", encoding="utf-8") as f:
            json.dump({"ticket": "TEST-UNTRACKED-AUTHORITY", "status": "test"}, f)

        allowlist_dir = os.path.join(tmpdir, "scripts", "ember_totality")
        os.makedirs(allowlist_dir, exist_ok=True)
        allowlist_path = os.path.join(allowlist_dir, "custody-allowlist.json")
        with open(allowlist_path, "w", encoding="utf-8") as f:
            json.dump({
                "goal_id": "EMBER-02",
                "workstream_id": "EMBER-02A",
                "next_executed_outcome": "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember",
                "schema_version": "ember-c-custody-allowlist-v1",
                "allowed_receipt_basenames": ["staging-untracked3.json"],
            }, f)
        # allowlist_path is deliberately never `git add`ed -- stays untracked.

        subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmpdir, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=tmpdir, capture_output=True)
        Path(os.path.join(tmpdir, ".gitkeep")).touch()
        subprocess.run(["git", "add", ".gitkeep"], cwd=tmpdir, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init, no allowlist tracked"], cwd=tmpdir, capture_output=True)

        output, rc = run_probe(tmpdir)
        assert rc == 0, f"Probe must never crash, got rc={rc}: {output}"
        assert "RED" in output, f"An untracked authority file must not authorize, got: {output}"
        print("untracked authority file negative: PASS")


def test_dirty_authority_file_committed_content_governs():
    """A tracked custody-allowlist.json committed with a NON-permissive
    pattern set, then modified in the working tree to a permissive version
    that WOULD authorize the untracked receipt -- the uncommitted edit must
    never grant authority; only the committed HEAD blob governs (round-2
    repair, PR951 clause 1)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        receipts_dir = os.path.join(tmpdir, "receipts")
        os.makedirs(receipts_dir)
        receipt_file = os.path.join(receipts_dir, "staging-untracked4.json")
        with open(receipt_file, "w", encoding="utf-8") as f:
            json.dump({"ticket": "TEST-DIRTY-AUTHORITY", "status": "test"}, f)

        allowlist_dir = os.path.join(tmpdir, "scripts", "ember_totality")
        os.makedirs(allowlist_dir, exist_ok=True)
        allowlist_path = os.path.join(allowlist_dir, "custody-allowlist.json")

        committed_allowlist = {
            "goal_id": "EMBER-02",
            "workstream_id": "EMBER-02A",
            "next_executed_outcome": "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember",
            "schema_version": "ember-c-custody-allowlist-v1",
            "allowed_receipt_basenames": [],  # committed version authorizes nothing
        }
        with open(allowlist_path, "w", encoding="utf-8") as f:
            json.dump(committed_allowlist, f)

        subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmpdir, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=tmpdir, capture_output=True)
        subprocess.run(["git", "add", "scripts/"], cwd=tmpdir, capture_output=True)
        subprocess.run(["git", "commit", "-m", "commit non-permissive allowlist"], cwd=tmpdir, capture_output=True)

        # Dirty edit: working tree now grants the exact permissive pattern.
        permissive_allowlist = dict(committed_allowlist)
        permissive_allowlist["allowed_receipt_basenames"] = ["staging-untracked4.json"]
        with open(allowlist_path, "w", encoding="utf-8") as f:
            json.dump(permissive_allowlist, f)

        status = subprocess.run(
            ["git", "status", "--porcelain", "--", "src/ember/governance/scripts/ember_totality/custody-allowlist.json"],
            cwd=tmpdir, capture_output=True, text=True,
        ).stdout
        assert status.strip(), "test setup bug: authority file is not actually dirty"

        output, rc = run_probe(tmpdir)
        assert rc == 0, f"Probe must never crash, got rc={rc}: {output}"
        assert "RED" in output, (
            "The uncommitted permissive edit to the authority file must not "
            f"authorize the untracked receipt; committed content must govern, got: {output}"
        )
        print("dirty authority file negative: PASS")


def test_bracket_and_regex_patterns_bounded_red_no_crash():
    """A '[*'-style unbalanced-bracket pattern and a regex-active '(.*)'
    pattern must both be bounded to RED (no crash, no authorization) --
    neither construct is supported basename-glob syntax here (round-2
    repair, PR951 clause 2)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        receipts_dir = os.path.join(tmpdir, "receipts")
        os.makedirs(receipts_dir)
        receipt_file = os.path.join(receipts_dir, "not-matching-anything2.json")
        with open(receipt_file, "w", encoding="utf-8") as f:
            json.dump({"ticket": "TEST-BRACKET-REGEX", "status": "test"}, f)

        allowlist_dir = os.path.join(tmpdir, "scripts", "ember_totality")
        os.makedirs(allowlist_dir, exist_ok=True)
        allowlist_path = os.path.join(allowlist_dir, "custody-allowlist.json")
        with open(allowlist_path, "w", encoding="utf-8") as f:
            json.dump({
                "goal_id": "EMBER-02",
                "workstream_id": "EMBER-02A",
                "next_executed_outcome": "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember",
                "schema_version": "ember-c-custody-allowlist-v1",
                "allowed_receipt_basenames": ["staging-[unbalanced*.json", "(.*)"],
            }, f)

        subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmpdir, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=tmpdir, capture_output=True)
        subprocess.run(["git", "add", "scripts/"], cwd=tmpdir, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init bracket+regex allowlist"], cwd=tmpdir, capture_output=True)

        output, rc = run_probe(tmpdir)
        assert rc == 0, f"Bracket/regex patterns must never crash the probe, got rc={rc}: {output}"
        assert "RED" in output, (
            "Neither the unbalanced-bracket nor the regex-active pattern "
            f"must authorize the unrelated untracked receipt, got: {output}"
        )
        print("bracket+regex pattern negative: PASS")


def test_separator_pattern_not_honored():
    """A pattern containing a path separator (e.g. 'a/b*') is not a basename
    glob -- reject it outright, granting no authority (round-2 repair,
    PR951 clause 2)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        receipts_dir = os.path.join(tmpdir, "receipts")
        os.makedirs(receipts_dir)
        receipt_file = os.path.join(receipts_dir, "a-something.json")
        with open(receipt_file, "w", encoding="utf-8") as f:
            json.dump({"ticket": "TEST-SEPARATOR-PATTERN", "status": "test"}, f)

        allowlist_dir = os.path.join(tmpdir, "scripts", "ember_totality")
        os.makedirs(allowlist_dir, exist_ok=True)
        allowlist_path = os.path.join(allowlist_dir, "custody-allowlist.json")
        with open(allowlist_path, "w", encoding="utf-8") as f:
            json.dump({
                "goal_id": "EMBER-02",
                "workstream_id": "EMBER-02A",
                "next_executed_outcome": "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember",
                "schema_version": "ember-c-custody-allowlist-v1",
                "allowed_receipt_basenames": ["a/b*"],
            }, f)

        subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmpdir, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=tmpdir, capture_output=True)
        subprocess.run(["git", "add", "scripts/"], cwd=tmpdir, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init separator-pattern allowlist"], cwd=tmpdir, capture_output=True)

        output, stderr, rc = run_probe_full(tmpdir)
        assert rc == 0, f"Probe must never crash, got rc={rc}: {output}"
        assert "RED" in output, (
            "A path-separator pattern must not authorize the untracked "
            f"receipt, got: {output}"
        )
        assert "rejecting unsafe allowlist pattern" in stderr and "a/b*" in stderr, (
            "Expected the validator's disclosed-rejection line for the "
            f"separator pattern on stderr, got stderr: {stderr!r}"
        )
        print("separator-pattern negative: PASS")


def test_matching_committed_authority_grants_authority_sibling_stays_red():
    """Discriminating GREEN-direction test: a correctly bound, COMMITTED,
    non-empty authority fixture (right goal_id/workstream_id/
    next_executed_outcome, one valid safe pattern) actually grants
    authority for the ONE untracked receipt whose basename matches --
    while a sibling untracked receipt in the SAME run, whose basename does
    NOT match, stays RED. This is the positive-authority-path test: every
    other authority test in this suite is RED-only, so a `return set()`
    stub for _get_allowlist_from_tracked_authority would satisfy them all
    without actually granting anything. This test fails against that stub
    (see RED evidence) and only passes when authority is genuinely honored
    for the matching basename."""
    with tempfile.TemporaryDirectory() as tmpdir:
        receipts_dir = os.path.join(tmpdir, "receipts")
        os.makedirs(receipts_dir)

        # Permitted: basename matches the committed allowlist pattern exactly.
        permitted_file = os.path.join(receipts_dir, "staging-permitted-001.json")
        with open(permitted_file, "w", encoding="utf-8") as f:
            json.dump({"ticket": "TEST-PERMITTED", "status": "test"}, f)

        # Sibling, same run, untracked, but basename does NOT match the
        # allowlist pattern -- must stay a custody violation.
        unrelated_file = os.path.join(receipts_dir, "unrelated-not-allowlisted.json")
        with open(unrelated_file, "w", encoding="utf-8") as f:
            json.dump({"ticket": "TEST-UNRELATED", "status": "test"}, f)

        allowlist_dir = os.path.join(tmpdir, "scripts", "ember_totality")
        os.makedirs(allowlist_dir, exist_ok=True)
        allowlist_path = os.path.join(allowlist_dir, "custody-allowlist.json")
        with open(allowlist_path, "w", encoding="utf-8") as f:
            json.dump({
                "goal_id": "EMBER-02",
                "workstream_id": "EMBER-02A",
                "next_executed_outcome": "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember",
                "schema_version": "ember-c-custody-allowlist-v1",
                "allowed_receipt_basenames": ["staging-permitted-*.json"],
            }, f)

        subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmpdir, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=tmpdir, capture_output=True)
        # Commit the allowlist authority file (and nothing else) so it is
        # tracked at HEAD -- the two receipts stay deliberately untracked.
        subprocess.run(["git", "add", "scripts/"], cwd=tmpdir, capture_output=True)
        subprocess.run(["git", "commit", "-m", "commit permissive, correctly-bound allowlist"], cwd=tmpdir, capture_output=True)

        output, rc = run_probe(tmpdir)
        assert rc == 0, f"Probe must never crash, got rc={rc}: {output}"
        assert "RED" in output, (
            "The sibling non-matching untracked receipt must still be a "
            f"custody violation, got: {output}"
        )
        assert "untracked=1" in output, (
            "Exactly one untracked violation expected (the non-matching "
            f"sibling); the matching receipt must be authorized, got: {output}"
        )
        print("matching-committed-authority positive grant: PASS")


def test_shape_b_unparseable():
    """Shape (b): unparseable — file with invalid JSON."""
    with tempfile.TemporaryDirectory() as tmpdir:
        receipts_dir = os.path.join(tmpdir, "receipts")
        os.makedirs(receipts_dir)

        # Create a file with invalid JSON
        receipt_file = os.path.join(receipts_dir, "truncated-corpus.json")
        with open(receipt_file, "w", encoding="utf-8") as f:
            f.write('{"ticket": "TEST-TRUNC", "ts": "20260707')  # Missing closing

        # Initialize git and track this file (so shape (a) doesn't trigger)
        subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=tmpdir,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmpdir,
            capture_output=True,
        )
        subprocess.run(["git", "add", "receipts/"], cwd=tmpdir, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=tmpdir,
            capture_output=True,
        )

        output, _ = run_probe(tmpdir)
        assert "RED" in output, f"Expected RED for unparseable JSON, got: {output}"
        assert "UNPARSEABLE" in output or "custody" in output.lower(), (
            f"Expected UNPARSEABLE/custody mention, got: {output}"
        )
        print("✓ Shape (b) unparseable: PASS")


def test_shape_c_cited_missing():
    """Shape (c): cited-path-missing — receipt references a missing receipt."""
    with tempfile.TemporaryDirectory() as tmpdir:
        receipts_dir = os.path.join(tmpdir, "receipts")
        os.makedirs(receipts_dir)

        # Create a receipt that cites another receipts/ path that doesn't exist
        receipt_file = os.path.join(receipts_dir, "board-with-citation.json")
        receipt_data = {
            "ticket": "TEST-CITE",
            "ts": "20260707T000000Z",
            "cited_receipt": "receipts/missing-evidence-20260707T000000Z.json",
            "status": "test",
        }
        with open(receipt_file, "w", encoding="utf-8") as f:
            json.dump(receipt_data, f)

        # Initialize git and track this file
        subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=tmpdir,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmpdir,
            capture_output=True,
        )
        subprocess.run(["git", "add", "receipts/"], cwd=tmpdir, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=tmpdir,
            capture_output=True,
        )

        output, _ = run_probe(tmpdir)
        assert "RED" in output, f"Expected RED for cited-missing, got: {output}"
        assert "CITED-MISSING" in output or "custody" in output.lower(), (
            f"Expected CITED-MISSING/custody mention, got: {output}"
        )
        print("✓ Shape (c) cited-missing: PASS")


def test_clean_pass():
    """Clean pass: tracked, parseable, no broken citations."""
    with tempfile.TemporaryDirectory() as tmpdir:
        receipts_dir = os.path.join(tmpdir, "receipts")
        os.makedirs(receipts_dir)

        # Create a clean, tracked, parseable receipt
        receipt_file = os.path.join(receipts_dir, "clean-receipt.json")
        receipt_data = {
            "ticket": "TEST-CLEAN",
            "ts": "20260707T000000Z",
            "status": "success",
        }
        with open(receipt_file, "w", encoding="utf-8") as f:
            json.dump(receipt_data, f)

        # Initialize git and track
        subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=tmpdir,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmpdir,
            capture_output=True,
        )
        subprocess.run(["git", "add", "receipts/"], cwd=tmpdir, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=tmpdir,
            capture_output=True,
        )

        output, _ = run_probe(tmpdir)
        assert "GREEN" in output, f"Expected GREEN for clean pass, got: {output}"
        assert "0 violations" in output or "custody" in output.lower(), (
            f"Expected success message, got: {output}"
        )
        print("✓ Clean pass: PASS")


def test_empty_receipts():
    """Edge case: receipts/ directory is empty or missing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create an empty git repo with an empty receipts directory.
        receipts_dir = os.path.join(tmpdir, "receipts")
        os.makedirs(receipts_dir)
        subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=tmpdir,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmpdir,
            capture_output=True,
        )

        # Create and commit a dummy file
        dummy = os.path.join(tmpdir, ".gitkeep")
        Path(dummy).touch()
        subprocess.run(["git", "add", ".gitkeep"], cwd=tmpdir, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=tmpdir,
            capture_output=True,
        )

        output, _ = run_probe(tmpdir)
        # Could be GREEN (empty is fine) or UNEVALUABLE (no receipts/ to check)
        assert "GREEN" in output, f"Empty receipts should be GREEN, got: {output}"
        print("✓ Empty receipts: PASS")


def main():
    print("\nC-CUSTODY TDD Test Suite")
    print("=" * 50)

    try:
        test_shape_a_untracked()
        test_post_landing_untracked_is_red()
        test_self_allowlist_cannot_authorize_itself()
        test_allowlist_wrong_workstream_not_honored()
        test_allowlist_missing_identity_field_not_honored()
        test_allowlist_malformed_pattern_no_crash()
        test_authority_file_untracked_not_honored()
        test_dirty_authority_file_committed_content_governs()
        test_bracket_and_regex_patterns_bounded_red_no_crash()
        test_separator_pattern_not_honored()
        test_matching_committed_authority_grants_authority_sibling_stays_red()
        test_shape_b_unparseable()
        test_shape_c_cited_missing()
        test_clean_pass()
        test_empty_receipts()

        print("\n" + "=" * 50)
        print("All tests PASSED ✓")
        return 0
    except AssertionError as e:
        print(f"\nTest FAILED ✗: {e}")
        return 1
    except Exception as e:
        print(f"\nUnexpected error ✗: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
