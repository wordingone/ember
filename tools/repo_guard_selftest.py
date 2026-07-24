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
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
GUARD_SUPPORT_FILES = [
    "tools/repo-guard.sh",
    "tools/check_line_endings.py",
    "tools/check_encoding.py",
    "tools/check_names_hashed.py",
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
# RED: non-UTF-8 tracked text file (issue #247) -- UTF-16LE-with-BOM blind
# spot that the git-grep-based [names]/[paths]/[path-frags] scans below it
# would otherwise silently pass straight through.
# ---------------------------------------------------------------------------
def test_red_utf16_encoding_blind_spot():
    tmp = make_fixture("fix/selftest-red-encoding-utf16")
    try:
        (tmp / "scripts").mkdir(exist_ok=True)
        # Ordinary prose, UTF-16LE with a BOM -- not itself a denylist hit,
        # this proves the [encoding] check fires on the ENCODING alone, not
        # on content the [names] scan would also have caught independently.
        (tmp / "scripts" / "note.py").write_text(
            "# just an ordinary comment, nothing sensitive\nx = 1\n",
            encoding="utf-16",  # emits a BOM by default in Python
        )
        commit_fixture(tmp)
        rc, out = run_guard(tmp)
        assert rc != 0, f"expected nonzero exit, got {rc}\n{out}"
        assert "FAIL [encoding]" in out, out
        assert "scripts/note.py" in out, out
    finally:
        cleanup(tmp)


# ---------------------------------------------------------------------------
# RED: single-byte non-UTF-8 sequence (issue #247 scope extension) -- the
# cp1252-shaped defect class distinct from a UTF-16/32 BOM.
# ---------------------------------------------------------------------------
def test_red_single_byte_encoding_defect():
    tmp = make_fixture("fix/selftest-red-encoding-cp1252")
    try:
        (tmp / "scripts").mkdir(exist_ok=True)
        path = tmp / "scripts" / "note2.py"
        # b"\x97" (a cp1252 em-dash) is not valid as a UTF-8 continuation or
        # lead byte on its own -- an ordinary ASCII comment with exactly one
        # such stray byte, same shape as the live test_c*.py defect.
        path.write_bytes(b"# an em\x97dash snuck in here\nx = 1\n")
        commit_fixture(tmp)
        rc, out = run_guard(tmp)
        assert rc != 0, f"expected nonzero exit, got {rc}\n{out}"
        assert "FAIL [encoding]" in out, out
        assert "scripts/note2.py" in out, out
    finally:
        cleanup(tmp)


# ---------------------------------------------------------------------------
# RED: UTF-32 with a BOM (issue #247 thread amendment -- the acceptance
# clause names UTF-16LE/UTF-32 as DISTINCT required fixtures, not just one
# multi-byte encoding standing in for both; a strict-UTF-8 decode rejects a
# UTF-32 stream for the same reason it rejects UTF-16 -- 3 NUL bytes out of
# every 4 for plain ASCII content -- but that equivalence was asserted, not
# receipted, until this fixture existed).
# ---------------------------------------------------------------------------
def test_red_utf32_encoding_blind_spot():
    tmp = make_fixture("fix/selftest-red-encoding-utf32")
    try:
        (tmp / "scripts").mkdir(exist_ok=True)
        (tmp / "scripts" / "note3.py").write_text(
            "# just an ordinary comment, nothing sensitive\nx = 1\n",
            encoding="utf-32",  # emits a BOM by default in Python
        )
        commit_fixture(tmp)
        rc, out = run_guard(tmp)
        assert rc != 0, f"expected nonzero exit, got {rc}\n{out}"
        assert "FAIL [encoding]" in out, out
        assert "scripts/note3.py" in out, out
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
# GREEN: a genuinely binary tracked file (by extension) is never flagged by
# [encoding] -- the check targets the git-grep blind spot in TEXT files,
# never byte-pinned binary artifacts.
# ---------------------------------------------------------------------------
def test_green_binary_file_not_flagged():
    tmp = make_fixture("fix/selftest-green-binary")
    try:
        (tmp / "scripts").mkdir(exist_ok=True)
        # Arbitrary non-UTF-8 bytes, but a recognized binary extension --
        # must never be scanned as text.
        (tmp / "scripts" / "weights.bin").write_bytes(bytes(range(256)))
        commit_fixture(tmp)
        rc, out = run_guard(tmp)
        assert rc == 0, f"expected exit 0, got {rc}\n{out}"
        assert "repo-guard: PASS" in out, out
        assert "ok   [encoding]" in out, out
    finally:
        cleanup(tmp)


ALL_TESTS = [
    test_red_name_via_hash_match,
    test_red_absolute_path_single_separator,
    test_red_absolute_path_doubled_json_escape,
    test_red_utf16_encoding_blind_spot,
    test_red_utf32_encoding_blind_spot,
    test_red_single_byte_encoding_defect,
    test_green_clean_fixture,
    test_green_binary_file_not_flagged,
    test_green_hashed_denylist_no_match,
    test_ci_fail_closed_no_denylist,
    test_ci_fail_closed_empty_hashed_denylist,
    test_red_name_outside_exclude_scope,
    test_green_name_inside_excluded_path,
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
