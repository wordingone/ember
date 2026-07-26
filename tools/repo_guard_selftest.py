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


def run_guard_from_trusted_kernel(
    subject: Path,
    kernel: Path,
    extra_env: dict | None = None,
) -> tuple[int, str]:
    """Run the kernel's guard bytes against a separate subject checkout."""
    import os
    env = dict(os.environ)
    env.pop("REPO_GUARD_NAMES", None)
    env.update(
        {
            "CI": "true",
            "GITHUB_ACTIONS": "true",
            "REPO_GUARD_KERNEL_ROOT": kernel.as_posix(),
            "REPO_GUARD_SUBJECT_ROOT": subject.as_posix(),
        }
    )
    if extra_env:
        env.update(extra_env)
    proc = subprocess.run(
        [GIT_BASH, (kernel / "tools" / "repo-guard.sh").as_posix()],
        cwd=str(subject),
        env=env,
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout + proc.stderr


def make_split_kernel(test_word: str) -> Path:
    """Build the smallest real trusted kernel with a test-only hashed denylist."""
    kernel = Path(tempfile.mkdtemp(prefix="repo-guard-kernel-"))
    for relative in (
        "tools/repo-guard.sh",
        "tools/check_line_endings.py",
        "tools/check_names_hashed.py",
        "scripts/verify_authority_conservation.py",
    ):
        source = REPO_ROOT / relative
        target = kernel / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    (kernel / "tools" / "repo-guard-denylist.sha256").write_text(
        hashlib.sha256(test_word.encode("utf-8")).hexdigest() + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (kernel / "tools" / "repo-guard-names-exclude.txt").write_text(
        "", encoding="utf-8", newline="\n"
    )
    return kernel


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
# RED: a subject cannot replace the guard/helper that judges itself
# ---------------------------------------------------------------------------
def test_trusted_kernel_ignores_subject_guard_and_helpers():
    tmp = make_fixture("fix/selftest-trusted-kernel")
    try:
        (tmp / ".github" / "workflows").mkdir(parents=True)
        (tmp / ".github" / "workflows" / "repo-guard.yml").write_text(
            "name: candidate-bypass\n"
            "on: pull_request\n"
            "jobs:\n"
            "  guard:\n"
            "    runs-on: ubuntu-latest\n"
            "    steps:\n"
            "      - run: exit 0\n",
            encoding="utf-8",
            newline="\n",
        )
        (tmp / "tools" / "repo-guard.sh").write_text(
            "#!/usr/bin/env bash\n"
            "printf 'CANDIDATE_GUARD_EXECUTED\\n'\n"
            "exit 0\n",
            encoding="utf-8",
            newline="\n",
        )
        (tmp / "scripts" / "verify_authority_conservation.py").write_text(
            "from pathlib import Path\n"
            "Path('candidate-helper-ran').write_text('unsafe', encoding='utf-8')\n"
            "raise SystemExit(0)\n",
            encoding="utf-8",
            newline="\n",
        )
        (tmp / "INVARIANT.md").unlink()
        commit_fixture(tmp)

        rc, out = run_guard_from_trusted_kernel(
            tmp,
            REPO_ROOT,
            extra_env={"REPO_GUARD_NAMES": "guardnamethatdoesnotappear"},
        )
        assert rc != 0, f"trusted kernel accepted a subject-bypassed authority failure\n{out}"
        assert "FAIL [authority]" in out, out
        assert "CANDIDATE_GUARD_EXECUTED" not in out, out
        assert not (tmp / "candidate-helper-ran").exists(), (
            "trusted guard executed the subject-authored authority helper"
        )
    finally:
        cleanup(tmp)


def test_split_kernel_scans_subject_guard_for_runtime_names():
    tmp = make_fixture("fix/selftest-split-subject-name")
    try:
        test_word = "subjectguardnametestonly"
        (tmp / "tools" / "repo-guard.sh").write_text(
            "#!/usr/bin/env bash\n"
            f"# candidate-smuggled marker: {test_word}\n"
            "exit 0\n",
            encoding="utf-8",
            newline="\n",
        )
        commit_fixture(tmp)

        rc, out = run_guard_from_trusted_kernel(
            tmp,
            REPO_ROOT,
            extra_env={"REPO_GUARD_NAMES": test_word},
        )
        assert rc != 0, f"trusted split kernel accepted a name in subject guard bytes\n{out}"
        assert "FAIL [names]" in out, out
        assert "tools/repo-guard.sh:2" in out, out
    finally:
        cleanup(tmp)


def test_split_kernel_hashed_scan_covers_every_subject_guard_surface():
    test_word = "subjecthashnametestonly"
    for relative in (
        "tools/repo-guard.sh",
        "tools/check_names_hashed.py",
        "tools/.repo-guard-denylist",
        "tools/.repo-guard-denylist.example",
        "tools/repo-guard-names-exclude.txt",
    ):
        tmp = make_fixture("fix/selftest-split-hashed-surface")
        kernel = make_split_kernel(test_word)
        try:
            commit_fixture(tmp)
            target = tmp / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                f"candidate subject marker {test_word}\n",
                encoding="utf-8",
                newline="\n",
            )
            subprocess.run(
                ["git", "add", "-f", relative],
                cwd=str(tmp),
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                [
                    "git", "-c", "user.email=selftest@example.invalid",
                    "-c", "user.name=selftest", "commit", "-m",
                    f"add split surface {relative}",
                ],
                cwd=str(tmp),
                check=True,
                capture_output=True,
                text=True,
            )

            rc, out = run_guard_from_trusted_kernel(tmp, kernel)
            assert rc != 0, (
                f"trusted split hashed scan accepted marker in {relative}\n{out}"
            )
            assert "FAIL [names-hashed]" in out, out
            assert relative in out, out
        finally:
            cleanup(kernel)
            cleanup(tmp)


def test_split_kernel_accepts_byte_identical_inherited_guard_surfaces():
    tmp = make_fixture("fix/selftest-split-identical-guard")
    try:
        commit_fixture(tmp)

        rc, out = run_guard_from_trusted_kernel(
            tmp,
            REPO_ROOT,
            extra_env={"REPO_GUARD_NAMES": "guardnamethatdoesnotappear"},
        )
        assert rc == 0, (
            "trusted split kernel rejected byte-identical inherited guard surfaces\n"
            + out
        )
        assert "repo-guard: PASS" in out, out
    finally:
        cleanup(tmp)


def test_split_kernel_rejects_absolute_path_in_non_guard_file():
    tmp = make_fixture("fix/selftest-split-non-guard-path")
    try:
        (tmp / "docs").mkdir(exist_ok=True)
        bad_path = "C" + ":" + "/Users/example/private"
        (tmp / "docs" / "note.md").write_text(
            "candidate-smuggled path: " + bad_path + "\n",
            encoding="utf-8",
            newline="\n",
        )
        commit_fixture(tmp)

        rc, out = run_guard_from_trusted_kernel(
            tmp,
            REPO_ROOT,
            extra_env={"REPO_GUARD_NAMES": "guardnamethatdoesnotappear"},
        )
        assert rc != 0, f"trusted split kernel accepted a non-guard path\n{out}"
        assert "FAIL [paths]" in out, out
        assert "docs/note.md:1" in out, out
    finally:
        cleanup(tmp)


def test_split_kernel_rejects_deleted_subject_guard():
    tmp = make_fixture("fix/selftest-split-deleted-guard")
    try:
        (tmp / "tools" / "repo-guard.sh").unlink()
        commit_fixture(tmp)

        rc, out = run_guard_from_trusted_kernel(
            tmp,
            REPO_ROOT,
            extra_env={"REPO_GUARD_NAMES": "guardnamethatdoesnotappear"},
        )
        assert rc != 0, f"trusted split kernel accepted a deleted subject guard\n{out}"
        assert "FAIL [guard-kernel] subject guard surface is missing" in out, out
    finally:
        cleanup(tmp)


def test_split_kernel_scans_subject_guard_for_absolute_paths():
    tmp = make_fixture("fix/selftest-split-subject-path")
    try:
        (tmp / "tools" / "repo-guard.sh").write_text(
            "#!/usr/bin/env bash\n"
            "# candidate-smuggled path: " + "C:" + "/Users/example/private\n"
            "exit 0\n",
            encoding="utf-8",
            newline="\n",
        )
        commit_fixture(tmp)

        rc, out = run_guard_from_trusted_kernel(
            tmp,
            REPO_ROOT,
            extra_env={"REPO_GUARD_NAMES": "guardnamethatdoesnotappear"},
        )
        assert rc != 0, f"trusted split kernel accepted a subject guard path\n{out}"
        assert "FAIL [paths]" in out, out
        assert "tools/repo-guard.sh:2" in out, out
    finally:
        cleanup(tmp)


def test_required_workflow_uses_base_pinned_kernel():
    text = (REPO_ROOT / ".github" / "workflows" / "repo-guard.yml").read_text(
        encoding="utf-8"
    )
    required = (
        "pull_request:",
        "pull_request_target:",
        "path: guard-kernel",
        "path: guard-subject",
        "REPO_GUARD_KERNEL_ROOT:",
        "REPO_GUARD_SUBJECT_ROOT:",
        'bash "${kernel}/tools/repo-guard.sh"',
        'python "${kernel}/scripts/check_pr_authority_binding.py"',
        "persist-credentials: false",
        "permissions:",
        "contents: read",
        "pull-requests: read",
    )
    for marker in required:
        assert marker in text, f"trusted workflow marker missing: {marker}"
    assert (
        "on:\n"
        "  push:\n"
        "  pull_request:\n"
        "    branches: [master]\n"
        "  pull_request_target:\n"
    ) in text, (
        "bootstrap must retain pull_request while restoring unfiltered push coverage"
    )
    assert text.count("persist-credentials: false") == 4
    kernel_checkout = text.split(
        "- name: Checkout trusted guard kernel", 1
    )[1].split("- name: Checkout bootstrap trusted guard kernel", 1)[0]
    assert "ref:" not in kernel_checkout, (
        "trusted kernel must resolve the current protected-base tip, not an event-stale base SHA"
    )
    assert (
        "(github.event_name == 'pull_request_target' || "
        "github.event_name == 'pull_request') && "
        "github.event.pull_request.base.sha || github.event.before"
    ) in text, "push and pull-request events must both bind an explicit changed-range base"
    assert "explicit range base is unavailable; refusing weaker tree-only fallback" in text
    assert "pull_request_target resolves the current" in text
    assert "pull_request is a temporary bootstrap trigger" in text
    assert "push is a same-tree self-check" in text
    assert "pull_request_target is the separated trusted-kernel gate" in text
    assert 'bash "${kernel}/tools/repo-guard.sh" --base "${BASE_SHA}"' in text


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
    test_trusted_kernel_ignores_subject_guard_and_helpers,
    test_split_kernel_scans_subject_guard_for_runtime_names,
    test_split_kernel_hashed_scan_covers_every_subject_guard_surface,
    test_split_kernel_accepts_byte_identical_inherited_guard_surfaces,
    test_split_kernel_rejects_absolute_path_in_non_guard_file,
    test_split_kernel_scans_subject_guard_for_absolute_paths,
    test_split_kernel_rejects_deleted_subject_guard,
    test_required_workflow_uses_base_pinned_kernel,
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
