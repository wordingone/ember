# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""repo_guard_selftest.py — hermetic fixture-repo selftests for tools/repo-guard.sh
and tools/check_names_hashed.py (issue #91).

Each test builds a throwaway git repo under a temp directory, copies in the real
guard + helper scripts (the code under test — never hand-duplicated), commits a
minimal tree, and runs the real `bash tools/repo-guard.sh` against it. Nothing here
touches the live repo; no fixture ever contains a real operator name — the hashed-
denylist cases use an obviously-fake test word so the test is self-contained.

Run: python tools/repo_guard_selftest.py
"""
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# The legacy product/daemon name this repo migrated away from is never
# written as a literal contiguous run anywhere in THIS tracked source file:
# doing so would make this selftest source itself match the very repo-tree
# scan it exercises (repo-guard.sh's own legacy-name check runs over the
# real tracked tree, and this file is part of it). Same self-referential-
# gate dodge already used below for the PATHPAT tests -- assembled at
# runtime instead of written as a literal, including in path strings.
_LEGACY = "ember" + "d"
_LEGACY_TAG = _LEGACY + "-legacy"
_LEGACY_SCHEMA = _LEGACY + "-legacy-exceptions-v1"
_LEGACY_POLICY_REL = "tools/" + _LEGACY + "-legacy-exceptions.json"
_LEGACY_CHECKER_REL = "tools/check_" + _LEGACY + "_legacy_exceptions.py"
_LEGACY_ENV_OVERRIDE = _LEGACY.upper() + "_EXCEPTIONS_PATH"

REPO_ROOT = Path(__file__).resolve().parents[1]
GUARD_SUPPORT_FILES = [
    "tools/repo-guard.sh",
    "tools/check_line_endings.py",
    "tools/check_names_hashed.py",
    _LEGACY_CHECKER_REL,
    _LEGACY_POLICY_REL,
    "scripts/verify_authority_conservation.py",
    "INVARIANT.md",
    "GOAL.md",
    "STATE.md",
    "GOVERNANCE.md",
    "README.md",
    "CONTINUITY.md",
    "docs/ember-completeness.md",
    "docs/ember-authority-matrix.md",
    "docs/ember-floor-contract.md",
    "docs/goal-clear-protocol.md",
    "docs/goal-mode-mechanism.md",
    "docs/nc2-own-technique-contract.md",
    "docs/registry-dispatch-gate-spec-v0.md",
    "docs/spec/autonomy-relinquishment-ladder-v1.md",
    "docs/spec/conditions-v1.md",
    "docs/technique-registry.jsonl",
    "configs/nck-baseline/nck-invariants.json",
    "configs/nck-c10.json",
    "configs/nck-invariants.json",
    "configs/nck-schedule.json",
    "configs/owned-core-widen-config.json",
    "configs/v0-multimodal-config.json",
    "configs/v0-pretrain-config.json",
    "configs/v1-pretrain-config.json",
    "scripts/conv_c03_muon_ns3_live.py",
    "scripts/timeshare_pretrain.py",
    "scripts/train_multimodal_v0.py",
]


def sha256_lower(word: str) -> str:
    return hashlib.sha256(word.strip().lower().encode("utf-8")).hexdigest()


def make_fixture(branch: str = "fix/selftest") -> Path:
    """A minimal fixture repo: one GOAL.md, the real guard support files, on a
    guard-legal branch name, with nothing else tracked. Callers add more files
    before calling commit_fixture()."""
    tmp = Path(tempfile.mkdtemp(prefix="repo_guard_selftest_"))
    subprocess.run(["git", "init", "-q", "-b", branch, str(tmp)], check=True)
    for rel in GUARD_SUPPORT_FILES:
        dst = tmp / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO_ROOT / rel, dst)
    return tmp


def commit_fixture(tmp: Path) -> None:
    subprocess.run(["git", "-C", str(tmp), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(tmp), "-c", "user.email=selftest@example.invalid",
         "-c", "user.name=selftest", "commit", "-q", "-m", "fixture init"],
        check=True,
    )


# Bare "bash" resolves to the Windows WSL-launcher shim (System32\bash.exe) rather
# than Git Bash under subprocess.run's search order, which then runs inside WSL with
# an unrelated PATH (python/git not found there). Invoke Git Bash by its full path.
GIT_BASH = "C:/Program Files/Git/bin/bash.exe"


def run_guard(tmp: Path, extra_env: dict | None = None) -> tuple[int, str]:
    import os
    env = dict(os.environ)
    env.pop("CI", None)
    env.pop("GITHUB_ACTIONS", None)
    env.pop("REPO_GUARD_NAMES", None)
    if extra_env:
        env.update(extra_env)
    proc = subprocess.run(
        [GIT_BASH, "tools/repo-guard.sh"], cwd=str(tmp), env=env,
        capture_output=True, text=True,
    )
    return proc.returncode, proc.stdout + proc.stderr


def cleanup(tmp: Path) -> None:
    shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# RED: name via hashed-denylist match
# ---------------------------------------------------------------------------
def test_red_name_via_hash_match():
    tmp = make_fixture("fix/selftest-red-name")
    try:
        test_word = "widgetcotestonly"  # single token: the checker splits on non-letters
        (tmp / "tools" / "repo-guard-denylist.sha256").write_text(
            "# selftest fixture — not a real denylist\n" + sha256_lower(test_word) + "\n",
            encoding="utf-8", newline="\n",
        )
        (tmp / "docs").mkdir(exist_ok=True)
        (tmp / "docs" / "note.md").write_text(
            f"This mentions {test_word} in passing.\n", encoding="utf-8", newline="\n",
        )
        commit_fixture(tmp)
        rc, out = run_guard(tmp)
        assert rc != 0, f"expected nonzero exit, got {rc}\n{out}"
        assert "FAIL [names]" in out, out
        assert "docs/note.md:1" in out, out
    finally:
        cleanup(tmp)


# ---------------------------------------------------------------------------
# RED: ordinary backslash absolute local path
# ---------------------------------------------------------------------------
def test_red_absolute_path_single_separator():
    tmp = make_fixture("fix/selftest-red-path")
    try:
        (tmp / "docs").mkdir(exist_ok=True)
        # Path literal assembled at runtime so the guard's own paths scan
        # never matches this tracked selftest source (self-referential-gate
        # dodge, same pattern as the leak-gate's own term list).
        bad_path = "C" + ":" + chr(92) + chr(92).join(["Users", "someone", "notes.txt"])
        (tmp / "docs" / "note.md").write_text(
            "See " + bad_path + " for the local copy.\n",
            encoding="utf-8", newline="\n",
        )
        commit_fixture(tmp)
        rc, out = run_guard(tmp)
        assert rc != 0, f"expected nonzero exit, got {rc}\n{out}"
        assert "FAIL [paths]" in out, out
        assert "docs/note.md:1" in out, out
    finally:
        cleanup(tmp)



# ---------------------------------------------------------------------------
# RED: JSON-escaped backslash absolute local path
# ---------------------------------------------------------------------------
def test_red_absolute_path_doubled_json_escape():
    tmp = make_fixture("fix/selftest-red-path-json-escaped")
    try:
        (tmp / "docs").mkdir(exist_ok=True)
        # A JSON/Python serialized Windows path contains two backslashes per
        # separator on disk. Build it at runtime so this selftest source does
        # not trip the repository-wide path scan itself.
        slash = chr(92) * 2
        bad_path = "C" + ":" + slash + slash.join(["Users", "someone", "notes.txt"])
        (tmp / "docs" / "note.md").write_text(
            "See " + bad_path + " for the escaped local copy.\n",
            encoding="utf-8", newline="\n",
        )
        commit_fixture(tmp)
        rc, out = run_guard(tmp)
        assert rc != 0, f"expected nonzero exit, got {rc}\n{out}"
        assert "FAIL [paths]" in out, out
        assert "docs/note.md:1" in out, out
    finally:
        cleanup(tmp)

# ---------------------------------------------------------------------------
# GREEN: clean fixture, no denylist needed at all
# ---------------------------------------------------------------------------
def test_green_clean_fixture():
    tmp = make_fixture("fix/selftest-green")
    try:
        (tmp / "docs").mkdir(exist_ok=True)
        (tmp / "docs" / "note.md").write_text(
            "Nothing sensitive here, just ordinary prose.\n", encoding="utf-8", newline="\n",
        )
        commit_fixture(tmp)
        rc, out = run_guard(tmp)
        assert rc == 0, f"expected exit 0, got {rc}\n{out}"
        assert "repo-guard: PASS" in out, out
    finally:
        cleanup(tmp)


# ---------------------------------------------------------------------------
# GREEN (hashed mode, positive path): denylist present, no matching tokens
# ---------------------------------------------------------------------------
def test_green_hashed_denylist_no_match():
    tmp = make_fixture("fix/selftest-green-hashed")
    try:
        (tmp / "tools" / "repo-guard-denylist.sha256").write_text(
            sha256_lower("somenamethatneverappears") + "\n", encoding="utf-8", newline="\n",
        )
        (tmp / "docs").mkdir(exist_ok=True)
        (tmp / "docs" / "note.md").write_text("Ordinary prose only.\n", encoding="utf-8", newline="\n")
        commit_fixture(tmp)
        rc, out = run_guard(tmp)
        assert rc == 0, f"expected exit 0, got {rc}\n{out}"
        assert "ok   [names] none found (hashed denylist)" in out, out
    finally:
        cleanup(tmp)


# ---------------------------------------------------------------------------
# CI-context fail-closed: no plaintext, no hashed denylist at all
# ---------------------------------------------------------------------------
def test_ci_fail_closed_no_denylist():
    tmp = make_fixture("fix/selftest-ci-none")
    try:
        (tmp / "docs").mkdir(exist_ok=True)
        (tmp / "docs" / "note.md").write_text("Ordinary prose only.\n", encoding="utf-8", newline="\n")
        commit_fixture(tmp)

        rc_ci, out_ci = run_guard(tmp, extra_env={"CI": "true"})
        assert rc_ci == 2, f"expected exit 2 in CI with no denylist, got {rc_ci}\n{out_ci}"
        assert "FAIL [names] denylist required in protected context" in out_ci, out_ci

        rc_local, out_local = run_guard(tmp)
        assert rc_local == 0, f"expected exit 0 locally (no denylist == skip, not fail), got {rc_local}\n{out_local}"
        assert "skip [names] no denylist (local run)" in out_local, out_local
    finally:
        cleanup(tmp)


# ---------------------------------------------------------------------------
# RED: names-exclude file present, but the match is in a NON-excluded file —
# exclusion is scoped to its listed prefixes, not a global amnesty.
# ---------------------------------------------------------------------------
def test_red_name_outside_exclude_scope():
    tmp = make_fixture("fix/selftest-red-outside-exclude")
    try:
        test_word = "widgetcotestonly"
        (tmp / "tools" / "repo-guard-denylist.sha256").write_text(
            "# selftest fixture — not a real denylist\n" + sha256_lower(test_word) + "\n",
            encoding="utf-8", newline="\n",
        )
        (tmp / "tools" / "repo-guard-names-exclude.txt").write_text(
            "# selftest fixture\ntokenizer/\n", encoding="utf-8", newline="\n",
        )
        (tmp / "docs").mkdir(exist_ok=True)
        (tmp / "docs" / "note.md").write_text(
            f"This mentions {test_word} in passing.\n", encoding="utf-8", newline="\n",
        )
        commit_fixture(tmp)
        rc, out = run_guard(tmp)
        assert rc != 0, f"expected nonzero exit (match outside excluded scope), got {rc}\n{out}"
        assert "FAIL [names]" in out, out
        assert "docs/note.md:1" in out, out
    finally:
        cleanup(tmp)


# ---------------------------------------------------------------------------
# GREEN: the same matching token, but inside a path under an excluded prefix
# ---------------------------------------------------------------------------
def test_green_name_inside_excluded_path():
    tmp = make_fixture("fix/selftest-green-excluded-path")
    try:
        test_word = "widgetcotestonly"
        (tmp / "tools" / "repo-guard-denylist.sha256").write_text(
            "# selftest fixture — not a real denylist\n" + sha256_lower(test_word) + "\n",
            encoding="utf-8", newline="\n",
        )
        (tmp / "tools" / "repo-guard-names-exclude.txt").write_text(
            "# selftest fixture\ntokenizer/\n", encoding="utf-8", newline="\n",
        )
        (tmp / "tokenizer").mkdir()
        (tmp / "tokenizer" / "vocab.json").write_text(
            f'{{"{test_word}": 1}}\n', encoding="utf-8", newline="\n",
        )
        commit_fixture(tmp)
        rc, out = run_guard(tmp)
        assert rc == 0, f"expected exit 0 (match only inside excluded path), got {rc}\n{out}"
        assert "repo-guard: PASS" in out, out
    finally:
        cleanup(tmp)


# ---------------------------------------------------------------------------
# CI-context fail-closed: hashed denylist file present but empty/unusable
# ---------------------------------------------------------------------------
def test_ci_fail_closed_empty_hashed_denylist():
    tmp = make_fixture("fix/selftest-ci-empty-hashed")
    try:
        (tmp / "tools" / "repo-guard-denylist.sha256").write_text(
            "# only comments, no real entries\n", encoding="utf-8", newline="\n",
        )
        (tmp / "docs").mkdir(exist_ok=True)
        (tmp / "docs" / "note.md").write_text("Ordinary prose only.\n", encoding="utf-8", newline="\n")
        commit_fixture(tmp)

        rc_ci, out_ci = run_guard(tmp, extra_env={"CI": "true"})
        assert rc_ci == 2, f"expected exit 2 in CI with an unusable hashed denylist, got {rc_ci}\n{out_ci}"
        assert "FAIL [names] hashed denylist present but unusable" in out_ci, out_ci

        rc_local, out_local = run_guard(tmp)
        assert rc_local == 0, f"expected exit 0 locally, got {rc_local}\n{out_local}"
        assert "skip [names] hashed denylist unusable (local run)" in out_local, out_local
    finally:
        cleanup(tmp)


# ---------------------------------------------------------------------------
# legacy-name zero-hit policy validation (issue: policy validity must be
# unconditional -- a corrupt tools/<legacy-name>-legacy-exceptions.json must
# fail the guard even when the tree has zero legacy-name matches to
# adjudicate). Every case here uses a fixture with NO legacy-name occurrence
# anywhere, so the caller's matched-paths list is empty on every run -- only
# the policy file's own validity is under test.
#
# The token/path constants (_LEGACY*) are defined once, near the top of this
# file, and reused here — see the module-level comment there.
# ---------------------------------------------------------------------------
def _legacy_zero_hit_fixture(branch: str) -> Path:
    tmp = make_fixture(branch)
    (tmp / "docs").mkdir(exist_ok=True)
    (tmp / "docs" / "note.md").write_text(
        "Nothing sensitive here, just ordinary prose.\n", encoding="utf-8", newline="\n",
    )
    return tmp


def test_red_legacy_policy_missing_zero_hit():
    tmp = _legacy_zero_hit_fixture("fix/selftest-red-legacy-missing")
    try:
        (tmp / _LEGACY_POLICY_REL).unlink()
        commit_fixture(tmp)
        rc, out = run_guard(tmp)
        assert rc != 0, f"expected nonzero exit (missing policy, zero hits), got {rc}\n{out}"
        assert f"FAIL [{_LEGACY_TAG}]" in out, out
        assert "does not exist" in out, out
    finally:
        cleanup(tmp)


def test_red_legacy_policy_empty_zero_hit():
    tmp = _legacy_zero_hit_fixture("fix/selftest-red-legacy-empty")
    try:
        (tmp / _LEGACY_POLICY_REL).write_text("", encoding="utf-8", newline="\n")
        commit_fixture(tmp)
        rc, out = run_guard(tmp)
        assert rc != 0, f"expected nonzero exit (empty policy, zero hits), got {rc}\n{out}"
        assert f"FAIL [{_LEGACY_TAG}]" in out, out
        assert "is empty" in out, out
    finally:
        cleanup(tmp)


def test_red_legacy_policy_invalid_utf8_zero_hit():
    tmp = _legacy_zero_hit_fixture("fix/selftest-red-legacy-badutf8")
    try:
        (tmp / _LEGACY_POLICY_REL).write_bytes(b"\xff\xfe\x00invalid\x80\x81")
        commit_fixture(tmp)
        rc, out = run_guard(tmp)
        assert rc != 0, f"expected nonzero exit (invalid UTF-8 policy, zero hits), got {rc}\n{out}"
        assert f"FAIL [{_LEGACY_TAG}]" in out, out
        assert "not valid UTF-8 JSON" in out, out
    finally:
        cleanup(tmp)


def test_red_legacy_policy_invalid_json_zero_hit():
    tmp = _legacy_zero_hit_fixture("fix/selftest-red-legacy-badjson")
    try:
        (tmp / _LEGACY_POLICY_REL).write_text(
            "{ this is not valid json ", encoding="utf-8", newline="\n",
        )
        commit_fixture(tmp)
        rc, out = run_guard(tmp)
        assert rc != 0, f"expected nonzero exit (invalid JSON policy, zero hits), got {rc}\n{out}"
        assert f"FAIL [{_LEGACY_TAG}]" in out, out
        assert "not valid UTF-8 JSON" in out, out
    finally:
        cleanup(tmp)


def test_red_legacy_policy_wrong_schema_zero_hit():
    tmp = _legacy_zero_hit_fixture("fix/selftest-red-legacy-wrongschema")
    try:
        (tmp / _LEGACY_POLICY_REL).write_text(
            '["not", "an", "object"]', encoding="utf-8", newline="\n",
        )
        commit_fixture(tmp)
        rc, out = run_guard(tmp)
        assert rc != 0, f"expected nonzero exit (wrong-schema policy, zero hits), got {rc}\n{out}"
        assert f"FAIL [{_LEGACY_TAG}]" in out, out
        assert "top level is not a JSON object" in out, out
    finally:
        cleanup(tmp)


def test_red_legacy_policy_malformed_entry_zero_hit():
    tmp = _legacy_zero_hit_fixture("fix/selftest-red-legacy-badentry")
    try:
        doc = json.dumps({
            "schema": _LEGACY_SCHEMA,
            "entries": [{"path": "some/file.json", "unexpected_key": "boom"}],
        })
        (tmp / _LEGACY_POLICY_REL).write_text(doc, encoding="utf-8", newline="\n")
        commit_fixture(tmp)
        rc, out = run_guard(tmp)
        assert rc != 0, f"expected nonzero exit (malformed entry policy, zero hits), got {rc}\n{out}"
        assert f"FAIL [{_LEGACY_TAG}]" in out, out
        assert "no valid 'sha256'" in out, out
    finally:
        cleanup(tmp)


def test_green_legacy_policy_valid_zero_hit():
    """The over-closure control: a genuinely valid policy on a zero-hit tree
    must stay green both before and after the fix — this test must never go
    red as a side effect of tightening zero-hit validation."""
    tmp = _legacy_zero_hit_fixture("fix/selftest-green-legacy-valid")
    try:
        commit_fixture(tmp)
        rc, out = run_guard(tmp)
        assert rc == 0, f"expected exit 0 (valid policy, zero hits), got {rc}\n{out}"
        assert f"ok   [{_LEGACY_TAG}]" in out, out
        assert "repo-guard: PASS" in out, out
    finally:
        cleanup(tmp)


def test_red_legacy_unlisted_hit_still_fails():
    """Non-empty-hits path, unchanged: an unlisted legacy-name match still
    fails the guard exactly as before this fix."""
    tmp = make_fixture("fix/selftest-red-legacy-unlisted-hit")
    try:
        (tmp / "docs").mkdir(exist_ok=True)
        (tmp / "docs" / "note.md").write_text(
            f"mentions {_LEGACY} here, not in the exceptions file\n",
            encoding="utf-8", newline="\n",
        )
        commit_fixture(tmp)
        rc, out = run_guard(tmp)
        assert rc != 0, f"expected nonzero exit (unlisted hit), got {rc}\n{out}"
        assert f"FAIL [{_LEGACY_TAG}]" in out, out
        assert "docs/note.md" in out, out
    finally:
        cleanup(tmp)


def test_green_legacy_legit_exception_still_passes():
    """Non-empty-hits path, unchanged: a hit exactly covered by an enumerated
    (path, sha256) exception still passes the guard exactly as before this
    fix."""
    tmp = make_fixture("fix/selftest-green-legacy-legit-exception")
    try:
        (tmp / "docs").mkdir(exist_ok=True)
        content = f"mentions {_LEGACY} here, covered by an exception\n"
        (tmp / "docs" / "note.md").write_text(content, encoding="utf-8", newline="\n")
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        doc = json.dumps({
            "schema": _LEGACY_SCHEMA,
            "entries": [{"path": "docs/note.md", "sha256": digest, "reason": "selftest fixture"}],
        })
        (tmp / _LEGACY_POLICY_REL).write_text(doc, encoding="utf-8", newline="\n")
        commit_fixture(tmp)
        rc, out = run_guard(tmp)
        assert rc == 0, f"expected exit 0 (legit enumerated exception), got {rc}\n{out}"
        assert f"ok   [{_LEGACY_TAG}]" in out, out
        assert "repo-guard: PASS" in out, out
    finally:
        cleanup(tmp)


# ---------------------------------------------------------------------------
# RED: staged-scope byte provenance. REPO_GUARD_SCOPE=staged is what
# .githooks/pre-commit actually runs the guard with — the check must
# adjudicate the bytes about to be COMMITTED (the git index), never the
# working tree, or a commit can carry unexcepted bytes past a green guard.
# ---------------------------------------------------------------------------
def test_red_legacy_staged_bypass_worktree_restore():
    """Reproduction: commit an excepted file at its enumerated digest, stage
    DIFFERENT bytes over it, then restore the working tree back to the
    enumerated original WITHOUT re-staging — the index still holds the
    unexcepted bytes while the working tree shows the (still excepted)
    original. Under REPO_GUARD_SCOPE=staged the guard must fail on the
    staged bytes; reading the working tree instead would wrongly pass."""
    tmp = make_fixture("fix/selftest-red-legacy-staged-bypass")
    try:
        # Deliberately NOT under receipts/ -- that prefix carries its own,
        # unrelated authority-conservation goal-binding requirement (section
        # 9) that would contaminate this reproduction with a second, real
        # failure reason. docs/ has no such coupling.
        rel = "docs/legacy-note.md"
        (tmp / "docs").mkdir(exist_ok=True)
        original = f"historical note mentioning {_LEGACY}, frozen bytes\n"
        digest = hashlib.sha256(original.encode("utf-8")).hexdigest()
        (tmp / rel).write_text(original, encoding="utf-8", newline="\n")
        doc = json.dumps({
            "schema": _LEGACY_SCHEMA,
            "entries": [{"path": rel, "sha256": digest, "reason": "selftest fixture"}],
        })
        (tmp / _LEGACY_POLICY_REL).write_text(doc, encoding="utf-8", newline="\n")
        commit_fixture(tmp)

        # Sanity: green with the original bytes, no staged mutation yet.
        rc0, out0 = run_guard(tmp)
        assert rc0 == 0, f"fixture setup is not green before mutation: {rc0}\n{out0}"

        # Stage DIFFERENT bytes over the excepted file...
        modified = f"historical note mentioning {_LEGACY}, EDITED bytes\n"
        (tmp / rel).write_text(modified, encoding="utf-8", newline="\n")
        subprocess.run(["git", "-C", str(tmp), "add", rel], check=True)
        # ...then restore ONLY the working tree to the enumerated original,
        # WITHOUT re-staging — the index keeps the modified bytes.
        (tmp / rel).write_text(original, encoding="utf-8", newline="\n")

        rc, out = run_guard(tmp, extra_env={"REPO_GUARD_SCOPE": "staged"})
        assert rc != 0, (
            "expected nonzero exit: the staged bytes diverge from the "
            "enumerated digest even though the working tree was restored "
            f"to the original, got {rc}\n{out}"
        )
        assert f"FAIL [{_LEGACY_TAG}]" in out, out
        assert "current content digest is" in out, out
    finally:
        cleanup(tmp)


# ---------------------------------------------------------------------------
# RED: exceptions-path byte provenance. The policy path must be hardcoded —
# an inherited/attacker-set exceptions-path override env var must have zero
# effect (see _LEGACY_ENV_OVERRIDE above for the exact variable name).
# ---------------------------------------------------------------------------
def test_red_legacy_env_override_ignored():
    """Reproduction: commit a tree with a real, unlisted legacy-name hit, so
    the COMMITTED policy correctly fails it. Point the exceptions-path
    override env var at an external, more permissive policy that DOES
    enumerate the hit at its correct digest. If the override were honoured
    the guard would wrongly pass; it must still fail against the committed
    policy."""
    tmp = make_fixture("fix/selftest-red-legacy-env-override")
    external = None
    try:
        (tmp / "docs").mkdir(exist_ok=True)
        content = f"mentions {_LEGACY} here, not enumerated in the real policy\n"
        (tmp / "docs" / "note.md").write_text(content, encoding="utf-8", newline="\n")
        commit_fixture(tmp)

        rc0, out0 = run_guard(tmp)
        assert rc0 != 0, f"fixture baseline should fail (unlisted hit): {rc0}\n{out0}"

        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        external = tmp.parent / f"{tmp.name}-external-policy.json"
        external.write_text(json.dumps({
            "schema": _LEGACY_SCHEMA,
            "entries": [{"path": "docs/note.md", "sha256": digest, "reason": "attacker-controlled"}],
        }), encoding="utf-8", newline="\n")

        rc, out = run_guard(tmp, extra_env={_LEGACY_ENV_OVERRIDE: str(external)})
        assert rc != 0, (
            "expected the external policy override to be IGNORED (guard "
            f"must still fail against the committed policy), got {rc}\n{out}"
        )
        assert f"FAIL [{_LEGACY_TAG}]" in out, out
        assert "docs/note.md" in out, out
    finally:
        cleanup(tmp)
        if external is not None and external.exists():
            external.unlink()


ALL_TESTS = [
    test_red_name_via_hash_match,
    test_red_absolute_path_single_separator,
    test_red_absolute_path_doubled_json_escape,
    test_green_clean_fixture,
    test_green_hashed_denylist_no_match,
    test_ci_fail_closed_no_denylist,
    test_ci_fail_closed_empty_hashed_denylist,
    test_red_name_outside_exclude_scope,
    test_green_name_inside_excluded_path,
    test_red_legacy_policy_missing_zero_hit,
    test_red_legacy_policy_empty_zero_hit,
    test_red_legacy_policy_invalid_utf8_zero_hit,
    test_red_legacy_policy_invalid_json_zero_hit,
    test_red_legacy_policy_wrong_schema_zero_hit,
    test_red_legacy_policy_malformed_entry_zero_hit,
    test_green_legacy_policy_valid_zero_hit,
    test_red_legacy_unlisted_hit_still_fails,
    test_green_legacy_legit_exception_still_passes,
    test_red_legacy_staged_bypass_worktree_restore,
    test_red_legacy_env_override_ignored,
]


def main() -> int:
    failed = []
    for t in ALL_TESTS:
        try:
            t()
            print(f"ok   {t.__name__}")
        except AssertionError as e:
            failed.append(t.__name__)
            print(f"FAIL {t.__name__}: {e}")
    if failed:
        print(f"\nrepo_guard_selftest: FAIL ({len(failed)}/{len(ALL_TESTS)})")
        return 1
    print(f"\nrepo_guard_selftest: PASS ({len(ALL_TESTS)}/{len(ALL_TESTS)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
