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
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# The retired daemon name is assembled to avoid self-matching the guard.
_LEGACY = "ember" + "d"
_LEGACY_TAG = _LEGACY + "-legacy"
_LEGACY_SCHEMA = _LEGACY + "-legacy-exceptions-v1"
_LEGACY_POLICY_REL = "tools/" + _LEGACY + "-legacy-exceptions.json"
_LEGACY_CHECKER_REL = "tools/check_" + _LEGACY + "_legacy_exceptions.py"
_LEGACY_ENV_OVERRIDE = _LEGACY.upper() + "_EXCEPTIONS_PATH"

# Assemble the local-path fragment for adversarial fixtures without self-matching.
_AVIR_FRAG = "/M" + "/avir"

REPO_ROOT = Path(__file__).resolve().parents[1]
GUARD_SUPPORT_FILES = [
    ".gitattributes",
    "tools/repo-guard.sh",
    "tools/powershell-launcher-shape-guard.ps1",
    "tools/run-python-hidden.sh",
    "tools/check_line_endings.py",
    "tools/check_text_encoding.py",
    "tools/check_executable_redaction_placeholders.py",
    "tools/check_names_hashed.py",
    "tools/check_governed_entry_exceptions.py",
    "tools/governed-entry-exceptions.json",
    "tools/launcher-shape-exceptions.json",
    _LEGACY_CHECKER_REL,
    _LEGACY_POLICY_REL,
    "scripts/verify_authority_conservation.py",
    "scripts/check_changed_receipts.py",
    "scripts/gate_provenance.py",
    "scripts/authority_supersession_gate.py",
    "scripts/verify_authority_supersession_crosswalk.py",
    "scripts/oldest_issue_disposition.py",
    "scripts/receipt_check.py",
    "tools/frozen-receipt-exceptions.json",
    "docs/authority/INVARIANT.md",
    "docs/authority/GOAL.md",
    "docs/authority/STATE.md",
    "docs/authority/GOVERNANCE.md",
    "README.md",
    "docs/authority/CONTINUITY.md",
    "docs/authority/REDACTIONS.md",
    "docs/contracts/ember-completeness.md",
    "docs/authority/ember-authority-matrix.md",
    "docs/contracts/ember-floor-contract.md",
    "docs/contracts/goal-clear-protocol.md",
    "docs/contracts/goal-mode-mechanism.md",
    "docs/contracts/nc2-own-technique-contract.md",
    "docs/contracts/registry-dispatch-gate-spec-v0.md",
    "docs/spec/autonomy-relinquishment-ladder-v1.md",
    "docs/spec/conditions-v1.md",
    "docs/ledgers/technique-registry.jsonl",
    "configs/nck-baseline/nck-invariants.json",
    "configs/nck-baseline/nck-invariants.authority.json",
    "configs/nck-c10.json",
    "configs/nck-invariants.json",
    "configs/nck-invariants.authority.json",
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
    """A minimal fixture repo: one docs/authority/GOAL.md, the real guard support files, on a
    guard-legal branch name, with nothing else tracked. Callers add more files
    before calling commit_fixture()."""
    tmp = Path(tempfile.mkdtemp(prefix="repo_guard_selftest_"))
    subprocess.run(["git", "init", "-q", "-b", branch, str(tmp)], check=True)
    for rel in GUARD_SUPPORT_FILES:
        dst = tmp / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO_ROOT / rel, dst)
    for rel in (
        "scripts/conv_c03_muon_ns3_live.py",
        "scripts/timeshare_pretrain.py",
        "scripts/train_multimodal_v0.py",
    ):
        (tmp / rel).write_text(
            "# EMBER_ARTIFACT_CLASS=historical_only\n"
            "raise SystemExit('historical_only: fixture')\n",
            encoding="utf-8",
            newline="\n",
        )
    write_fixture_crosswalk(tmp)
    return tmp


def write_fixture_crosswalk(root: Path) -> None:
    matrix = root / "docs" / "authority" / "ember-authority-matrix.md"
    matrix_sha = hashlib.sha256(matrix.read_bytes()).hexdigest()
    discrepancy_ids = sorted(
        set(re.findall(r"\|\s*(D-\d{3})\s*\|", matrix.read_text(encoding="utf-8")))
    )
    milestone = root / "docs" / "roadmap" / "milestones" / "EMBER-02.md"
    milestone.parent.mkdir(parents=True, exist_ok=True)
    milestone.write_text("# EMBER-02\n\nFixture milestone.\n", encoding="utf-8", newline="\n")
    evidence = [{"path": "docs/authority/ember-authority-matrix.md", "sha256": matrix_sha}]
    payload = {
        "schema_version": "ember-authority-supersession-crosswalk-v1",
        "repository": "wordingone/ember",
        "source_commit": "0" * 40,
        "current_authority": {
            "matrix_path": "docs/authority/ember-authority-matrix.md",
            "matrix_sha256": matrix_sha,
            "discrepancy_ids": discrepancy_ids,
            "milestone_ids": ["EMBER-02"],
            "historical_terminal": "HISTORICAL_ORPHANED",
        },
        "source_registries": [{
            "registry_id": "fixture-registry",
            "expected_source_ids": ["fixture-source"],
            "evidence": evidence,
        }],
        "rows": [{
            "source_registry": "fixture-registry",
            "source_id": "fixture-source",
            "source_kind": "legacy_condition",
            "statement": "fixture obligation",
            "disposition": "SUPERSEDED",
            "targets": [discrepancy_ids[0], "EMBER-02"],
            "evidence": evidence,
            "completion_credit": False,
        }],
    }
    payload["crosswalk_sha256"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    target = root / "manifests" / "authority" / "issue-35-authority-supersession-crosswalk-v1.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


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


def run_guard(
    tmp: Path,
    extra_env: dict | None = None,
    args: tuple[str, ...] = (),
) -> tuple[int, str]:
    import os
    env = dict(os.environ)
    env.pop("CI", None)
    env.pop("GITHUB_ACTIONS", None)
    env.pop("REPO_GUARD_NAMES", None)
    if extra_env:
        env.update(extra_env)
    proc = subprocess.run(
        [GIT_BASH, "tools/repo-guard.sh", *args], cwd=str(tmp), env=env,
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
        "tools/run-python-hidden.sh",
        "tools/check_line_endings.py",
        "tools/check_text_encoding.py",
        "tools/check_executable_redaction_placeholders.py",
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
# RED: text-attributed files must be checked regardless of filename extension.
# ---------------------------------------------------------------------------
def test_red_text_attributed_binary_extension_utf16le():
    tmp = make_fixture("fix/selftest-red-text-attributed-bin")
    try:
        with (tmp / ".gitattributes").open("a", encoding="utf-8", newline="\n") as attrs:
            attrs.write("payload.bin text\n")
        (tmp / "payload.bin").write_bytes(
            b"\xff\xfe" + "hidden text\n".encode("utf-16-le")
        )
        commit_fixture(tmp)
        rc, out = run_guard(tmp)
        assert rc != 0, f"expected nonzero exit, got {rc}\n{out}"
        assert "FAIL [encoding]" in out, out
        assert "payload.bin" in out, out
        assert "UTF-16LE BOM" in out, out
    finally:
        cleanup(tmp)


# ---------------------------------------------------------------------------
# RED/GREEN matrix required by #247: BOM variants and strict UTF-8 decoding.
# ---------------------------------------------------------------------------
def test_red_utf16le_bom():
    tmp = make_fixture("fix/selftest-red-utf16le")
    try:
        (tmp / "scripts").mkdir(exist_ok=True)
        (tmp / "scripts" / "note.py").write_bytes(
            b"\xff\xfe" + "print('hi')\n".encode("utf-16-le")
        )
        commit_fixture(tmp)
        rc, out = run_guard(tmp)
        assert rc != 0, f"expected nonzero exit, got {rc}\n{out}"
        assert "FAIL [encoding]" in out, out
        assert "scripts/note.py" in out, out
        assert "UTF-16LE BOM" in out, out
    finally:
        cleanup(tmp)


def test_red_utf32le_bom():
    tmp = make_fixture("fix/selftest-red-utf32le")
    try:
        (tmp / "scripts").mkdir(exist_ok=True)
        (tmp / "scripts" / "note.py").write_bytes(
            b"\xff\xfe\x00\x00" + "print('hi')\n".encode("utf-32-le")
        )
        commit_fixture(tmp)
        rc, out = run_guard(tmp)
        assert rc != 0, f"expected nonzero exit, got {rc}\n{out}"
        assert "FAIL [encoding]" in out, out
        assert "UTF-32LE BOM" in out, out
    finally:
        cleanup(tmp)


def test_red_invalid_single_byte_utf8():
    tmp = make_fixture("fix/selftest-red-invalid-byte")
    try:
        (tmp / "scripts").mkdir(exist_ok=True)
        (tmp / "scripts" / "note.py").write_bytes(
            b"# invalid cp1252-shaped byte: \x97\n"
        )
        commit_fixture(tmp)
        rc, out = run_guard(tmp)
        assert rc != 0, f"expected nonzero exit, got {rc}\n{out}"
        assert "FAIL [encoding]" in out, out
        assert "invalid UTF-8" in out, out
    finally:
        cleanup(tmp)


def test_green_valid_utf8_non_ascii():
    tmp = make_fixture("fix/selftest-green-utf8-nonascii")
    try:
        (tmp / "docs").mkdir(exist_ok=True)
        (tmp / "docs" / "note.md").write_text(
            "Ordinary UTF-8: café, über, em dash —.\n",
            encoding="utf-8",
            newline="\n",
        )
        commit_fixture(tmp)
        rc, out = run_guard(tmp)
        assert rc == 0, f"expected exit 0, got {rc}\n{out}"
        assert "ok   [encoding]" in out, out
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


def test_green_canonical_authority_paths():
    tmp = make_fixture("fix/selftest-migrated-authority")
    try:
        for name in ("GOAL.md", "INVARIANT.md", "GOVERNANCE.md", "CONTINUITY.md", "REDACTIONS.md", "STATE.md"):
            assert not (tmp / name).exists()
            assert (tmp / "docs" / "authority" / name).is_file()
        commit_fixture(tmp)
        rc, output = run_guard(tmp)
        assert rc == 0, output
        assert "ok   [authority-paths]" in output, output
        staged_rc, staged_output = run_guard(
            tmp, extra_env={"REPO_GUARD_SCOPE": "staged"}
        )
        assert staged_rc == 0, staged_output
        assert "ok   [authority-paths]" in staged_output, staged_output
    finally:
        cleanup(tmp)


def test_red_duplicate_authority_path():
    tmp = make_fixture("fix/selftest-duplicate-authority")
    try:
        authority = tmp / "docs" / "authority"
        authority.mkdir(parents=True, exist_ok=True)
        for name in (
            "GOAL.md",
            "INVARIANT.md",
            "GOVERNANCE.md",
            "CONTINUITY.md",
            "REDACTIONS.md",
            "STATE.md",
        ):
            shutil.copyfile(authority / name, tmp / name)
        commit_fixture(tmp)
        rc, output = run_guard(tmp)
        assert rc != 0, output
        assert "FAIL [authority-paths]" in output, output
        for name in ("GOAL.md", "INVARIANT.md", "GOVERNANCE.md", "CONTINUITY.md", "REDACTIONS.md", "STATE.md"):
            assert name in output, output
    finally:
        cleanup(tmp)


# ---------------------------------------------------------------------------
# RED/GREEN: cockpit state must never reside inside the certified tree (#1330).
# The completion verifier's census is total, so a resident writer reds the run;
# the guard refuses the directory rather than the census excluding it.
# ---------------------------------------------------------------------------
def test_red_resident_cockpit_state_dir():
    tmp = make_fixture("fix/selftest-cockpit-state")
    try:
        commit_fixture(tmp)
        state = tmp / ".ember"
        state.mkdir()
        (state / "root-bindings.json").write_text("{}\n", encoding="utf-8", newline="\n")
        rc, out = run_guard(tmp)
        assert rc != 0, f"expected failure for a resident cockpit state dir\n{out}"
        assert "cockpit-state" in out, out
        assert "root-bindings.json" in out, out
    finally:
        cleanup(tmp)


def test_red_cockpit_state_as_a_file():
    # Any SHAPE is refused, not just a populated directory — otherwise the check has a
    # blind spot exactly where a shim would sit.
    tmp = make_fixture("fix/selftest-cockpit-file")
    try:
        commit_fixture(tmp)
        (tmp / ".ember").write_text("not a directory\n", encoding="utf-8", newline="\n")
        rc, out = run_guard(tmp)
        assert rc != 0, f"expected failure for a '.ember' file\n{out}"
        assert "cockpit-state" in out, out
        assert "as a file" in out, out
    finally:
        cleanup(tmp)


def test_green_empty_cockpit_state_dir():
    # Emptiness is the bar, not absence: an empty leftover writes nothing.
    tmp = make_fixture("fix/selftest-cockpit-empty")
    try:
        commit_fixture(tmp)
        (tmp / ".ember").mkdir()
        _, out = run_guard(tmp)
        # Assert this check's own verdict rather than the guard's overall exit code: the
        # fixture repo carries only the subset of the tree the guard needs for the checks
        # under test, so unrelated checks may report on their own.
        assert "ok   [cockpit-state]" in out, out
        assert "FAIL [cockpit-state]" not in out, out
    finally:
        cleanup(tmp)


# ---------------------------------------------------------------------------
# RED/GREEN: an invalid pre-existing branch must not prompt an unsafe rename.
# ---------------------------------------------------------------------------
def test_red_invalid_branch_names_safe_recovery():
    tmp = make_fixture("legacy-preexisting-branch")
    try:
        (tmp / "docs").mkdir(exist_ok=True)
        (tmp / "docs" / "note.md").write_text(
            "Ordinary prose only.\n", encoding="utf-8", newline="\n",
        )
        commit_fixture(tmp)
        rc, out = run_guard(
            tmp,
            extra_env={"GITHUB_EVENT_NAME": "pull_request", "GITHUB_HEAD_REF": "legacy-preexisting-branch"},
        )
        assert rc != 0, f"expected nonzero exit, got {rc}\n{out}"
        assert "FAIL [branch]" in out, out
        assert "never rename a branch that has an open pull request" in out, out
        assert "detach HEAD and push to the existing ref" in out, out
    finally:
        cleanup(tmp)


def test_green_invalid_branch_is_advisory_for_exact_open_pr_head():
    branch = "legacy-preexisting-branch"
    tmp = make_fixture(branch)
    try:
        (tmp / "docs").mkdir(exist_ok=True)
        (tmp / "docs" / "note.md").write_text(
            "Ordinary prose only.\n", encoding="utf-8", newline="\n",
        )
        commit_fixture(tmp)
        rc, out = run_guard(
            tmp,
            extra_env={"GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "pull_request", "GITHUB_HEAD_REF": branch, "REPO_GUARD_NAMES": "selftestnomatch"},
        )
        assert "FAIL [branch]" not in out, out
        assert "ok   [branch]" in out, out
        assert "pre-existing open-PR head; naming is advisory only" in out, out
        assert "never rename the live ref" in out, out
        # The minimal fixture can still fail a separate authority leg; this
        # test adjudicates only the branch-name boundary.
        assert rc in (0, 1), rc
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
        (tmp / "docs/authority/INVARIANT.md").unlink()
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
    text = (REPO_ROOT / ".github" / "workflows" / "repo-policy-gate.yml").read_text(
        encoding="utf-8"
    )
    required = (
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
    assert "\n  pull_request:\n" not in text, (
        "candidate-authored pull_request workflow cannot be the required trust gate"
    )
    assert text.count("persist-credentials: false") == 3
    kernel_checkout = text.split(
        "- name: Checkout trusted guard kernel", 1
    )[1].split("- name: Checkout pull-request merge subject", 1)[0]
    assert (
        "ref: ${{ github.event.pull_request.base.sha || github.sha }}"
        in kernel_checkout
    ), (
        "trusted kernel must resolve the exact event base or protected push commit"
    )
    assert "ref: refs/pull/${{ github.event.pull_request.number }}/merge" in text
    assert "ref: ${{ github.sha }}" in text
    assert (
        "github.event_name == 'pull_request_target' && "
        "github.event.pull_request.base.sha || github.event.before"
    ) in text, "push and pull-request events must both bind an explicit changed-range base"
    assert 'git cat-file -e "${BASE_SHA}^{commit}"' in text
    assert "explicit range base unavailable; refusing fallback" in text
    assert 'bash "${kernel}/tools/repo-guard.sh" --base "${BASE_SHA}"' in text
    assert "gh api --paginate --slurp" in text
    assert "python -m scripts.github.live_pr_policy" in text
    assert "--event-base-sha" in text
    assert "--event-head-sha" in text
    assert '--changed-range "${range_base}..HEAD"' in text, (
        "the workflow already resolves range_base, so authority verification must use "
        "the verifier-supported two-dot range"
    )
    assert '--changed-range "${range_base}...HEAD"' not in text, (
        "a triple-dot range is invalid after range_base has already been resolved"
    )


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


# ---------------------------------------------------------------------------
# RED: the same staged-scope byte-provenance seam as the legacy-name check,
# reproduced against the other three checks that read tracked-file content
# unconditionally: names (plaintext/env mode), names (hashed mode), and
# path-frags. Each follows the identical shape -- commit clean content,
# stage a violation, restore the working tree to clean WITHOUT re-staging,
# confirm REPO_GUARD_SCOPE=staged still fails on the staged bytes.
# ---------------------------------------------------------------------------
def test_red_names_staged_bypass_worktree_restore():
    """Plaintext/env-var operator-name mode (repo-guard.sh's own `git grep`,
    REPO_GUARD_NAMES set). Priority case: this is the standing rule about
    what may never enter git history."""
    tmp = make_fixture("fix/selftest-red-names-staged-bypass")
    try:
        test_word = "widgetcotestonly"
        (tmp / "docs").mkdir(exist_ok=True)
        clean = "Nothing sensitive here, just ordinary prose.\n"
        (tmp / "docs" / "note.md").write_text(clean, encoding="utf-8", newline="\n")
        commit_fixture(tmp)

        rc0, out0 = run_guard(tmp, extra_env={"REPO_GUARD_NAMES": test_word})
        assert rc0 == 0, f"fixture setup is not green before mutation: {rc0}\n{out0}"

        tainted = f"This mentions {test_word} in passing.\n"
        (tmp / "docs" / "note.md").write_text(tainted, encoding="utf-8", newline="\n")
        subprocess.run(["git", "-C", str(tmp), "add", "docs/note.md"], check=True)
        (tmp / "docs" / "note.md").write_text(clean, encoding="utf-8", newline="\n")

        rc, out = run_guard(tmp, extra_env={"REPO_GUARD_SCOPE": "staged", "REPO_GUARD_NAMES": test_word})
        assert rc != 0, (
            "expected nonzero exit: the staged name-bearing bytes diverge "
            f"from the restored clean working tree, got {rc}\n{out}"
        )
        assert "FAIL [names]" in out, out
    finally:
        cleanup(tmp)


def test_red_names_hashed_staged_bypass_worktree_restore():
    """Same reproduction, hashed-denylist mode (check_names_hashed.py, the
    path taken when REPO_GUARD_NAMES is unset and a committed .sha256
    denylist exists)."""
    tmp = make_fixture("fix/selftest-red-names-hashed-staged-bypass")
    try:
        test_word = "widgetcotestonly"
        (tmp / "tools" / "repo-guard-denylist.sha256").write_text(
            "# selftest fixture — not a real denylist\n" + sha256_lower(test_word) + "\n",
            encoding="utf-8", newline="\n",
        )
        (tmp / "docs").mkdir(exist_ok=True)
        clean = "Nothing sensitive here, just ordinary prose.\n"
        (tmp / "docs" / "note.md").write_text(clean, encoding="utf-8", newline="\n")
        commit_fixture(tmp)

        rc0, out0 = run_guard(tmp)
        assert rc0 == 0, f"fixture setup is not green before mutation: {rc0}\n{out0}"

        tainted = f"This mentions {test_word} in passing.\n"
        (tmp / "docs" / "note.md").write_text(tainted, encoding="utf-8", newline="\n")
        subprocess.run(["git", "-C", str(tmp), "add", "docs/note.md"], check=True)
        (tmp / "docs" / "note.md").write_text(clean, encoding="utf-8", newline="\n")

        rc, out = run_guard(tmp, extra_env={"REPO_GUARD_SCOPE": "staged"})
        assert rc != 0, (
            "expected nonzero exit (hashed-denylist mode): the staged "
            f"name-bearing bytes diverge from the restored clean working "
            f"tree, got {rc}\n{out}"
        )
        assert "FAIL [names]" in out, out
    finally:
        cleanup(tmp)


def test_red_pathfrags_staged_bypass_worktree_restore():
    """Local WSL/mount path-fragment check (repo-guard.sh section 2b)."""
    tmp = make_fixture("fix/selftest-red-pathfrags-staged-bypass")
    try:
        (tmp / "docs").mkdir(exist_ok=True)
        clean = "Nothing sensitive here, just ordinary prose.\n"
        (tmp / "docs" / "note.md").write_text(clean, encoding="utf-8", newline="\n")
        commit_fixture(tmp)

        rc0, out0 = run_guard(tmp)
        assert rc0 == 0, f"fixture setup is not green before mutation: {rc0}\n{out0}"

        tainted = f"See {_AVIR_FRAG} for the local copy.\n"
        (tmp / "docs" / "note.md").write_text(tainted, encoding="utf-8", newline="\n")
        subprocess.run(["git", "-C", str(tmp), "add", "docs/note.md"], check=True)
        (tmp / "docs" / "note.md").write_text(clean, encoding="utf-8", newline="\n")

        rc, out = run_guard(tmp, extra_env={"REPO_GUARD_SCOPE": "staged"})
        assert rc != 0, (
            "expected nonzero exit: the staged path-fragment bytes diverge "
            f"from the restored clean working tree, got {rc}\n{out}"
        )
        assert "FAIL [path-frags]" in out, out
    finally:
        cleanup(tmp)


def test_red_line_endings_staged_bypass_worktree_restore():
    """The index must be inspected even if it contains CRLF bytes installed
    without Git clean-filter normalization. A normal ``git add`` is not a valid
    RED fixture because ``eol=lf`` converts CRLF to LF before the index write."""
    tmp = make_fixture("fix/selftest-red-line-endings-staged-bypass")
    try:
        (tmp / "docs").mkdir(exist_ok=True)
        clean = b"ordinary LF-only prose\n"
        (tmp / "docs" / "note.md").write_bytes(clean)
        commit_fixture(tmp)

        rc0, out0 = run_guard(tmp)
        assert rc0 == 0, f"fixture setup is not green before mutation: {rc0}\n{out0}"

        tainted = b"ordinary CRLF prose\r\n"
        blob = subprocess.run(
            ["git", "-C", str(tmp), "hash-object", "-w", "--stdin"],
            input=tainted, capture_output=True, check=True,
        ).stdout.decode("ascii").strip()
        subprocess.run(
            ["git", "-C", str(tmp), "update-index", "--cacheinfo",
             f"100644,{blob},docs/note.md"],
            check=True,
        )
        assert (tmp / "docs" / "note.md").read_bytes() == clean

        rc, out = run_guard(tmp, extra_env={"REPO_GUARD_SCOPE": "staged"})
        assert rc != 0, (
            "expected nonzero exit: the staged CRLF blob diverges from the "
            f"restored LF-only working tree, got {rc}\n{out}"
        )
        assert "FAIL [line-endings]" in out, out
    finally:
        cleanup(tmp)


def test_green_pr_merge_excludes_live_base_squash_commit():
    tmp = make_fixture("master")
    try:
        def git(*args: str) -> str:
            return subprocess.run(
                ["git", "-C", str(tmp), *args], check=True,
                capture_output=True, text=True,
            ).stdout.strip()

        def commit(message: str) -> str:
            git("add", "-A")
            git("-c", "user.email=selftest@example.invalid", "-c",
                "user.name=selftest", "commit", "-q", "-m", message)
            return git("rev-parse", "HEAD")

        commit_fixture(tmp)
        stale_event_base = git("rev-parse", "HEAD")
        git("checkout", "-q", "-b", "fix/pr-safe")
        (tmp / "docs" / "pr-note.md").write_bytes(b"branch-authored change\n")
        commit("safe branch change")

        git("checkout", "-q", "master")
        (tmp / "docs/authority/GOAL.md").write_bytes(b"live-base authority update\n")
        (tmp / "receipts").mkdir(exist_ok=True)
        (tmp / "receipts" / "live-base-note.md").write_bytes(
            b"already reviewed before squash\n"
        )
        commit("squashed live-base goal and evidence")
        git("checkout", stale_event_base, "--", "docs/authority/GOAL.md")
        commit("restore frozen goal authority")
        git("-c", "user.email=selftest@example.invalid", "-c",
            "user.name=selftest", "merge", "-q", "--no-ff", "fix/pr-safe",
            "-m", "synthetic pull-request merge")

        _rc, output = run_guard(
            tmp,
            extra_env={"REPO_GUARD_PR_MERGE_SUBJECT": "true"},
            args=("--base", stale_event_base),
        )
        assert "ok   [goal/evidence]" in output, output
        assert "FAIL [goal/evidence]" not in output, output
    finally:
        cleanup(tmp)


def test_red_pr_merge_still_rejects_branch_goal_evidence_commit():
    tmp = make_fixture("master")
    try:
        def git(*args: str) -> str:
            return subprocess.run(
                ["git", "-C", str(tmp), *args], check=True,
                capture_output=True, text=True,
            ).stdout.strip()

        def commit(message: str) -> str:
            git("add", "-A")
            git("-c", "user.email=selftest@example.invalid", "-c",
                "user.name=selftest", "commit", "-q", "-m", message)
            return git("rev-parse", "HEAD")

        commit_fixture(tmp)
        stale_event_base = git("rev-parse", "HEAD")
        git("checkout", "-q", "-b", "fix/pr-bad")
        (tmp / "docs/authority/GOAL.md").write_bytes(b"branch authority update\n")
        (tmp / "receipts").mkdir(exist_ok=True)
        (tmp / "receipts" / "branch-note.md").write_bytes(
            b"branch evidence update\n"
        )
        bad_commit = commit("bad branch goal and evidence")

        git("checkout", "-q", "master")
        (tmp / "README.md").write_bytes(b"new live-base prose\n")
        commit("advance live base")
        git("-c", "user.email=selftest@example.invalid", "-c",
            "user.name=selftest", "merge", "-q", "--no-ff", "fix/pr-bad",
            "-m", "synthetic pull-request merge")

        rc, output = run_guard(
            tmp,
            extra_env={"REPO_GUARD_PR_MERGE_SUBJECT": "true"},
            args=("--base", stale_event_base),
        )
        assert rc != 0, output
        assert "FAIL [goal/evidence]" in output, output
        assert bad_commit in output, output
    finally:
        cleanup(tmp)


def test_red_powershell_launcher_shape():
    tmp = make_fixture("fix/selftest-red-powershell-launcher")
    try:
        (tmp / "scripts" / "operator-resident.ps1").write_text(
            "Start-Process -FilePath 'train.py'\n",
            encoding="utf-8",
            newline="\n",
        )
        commit_fixture(tmp)
        rc, out = run_guard(tmp)
        assert rc != 0, f"expected nonzero exit, got {rc}\n{out}"
        assert "FAIL [launcher-shape]" in out, out
        assert "scripts/operator-resident.ps1" in out, out
    finally:
        cleanup(tmp)


def test_red_powershell_launcher_shape_preceding_assignment():
    tmp = make_fixture("fix/selftest-red-powershell-launcher-preceding")
    try:
        (tmp / "scripts" / "operator-daemon.ps1").write_text(
            "$script = 'train.py'\nStart-Process -FilePath $script\n",
            encoding="utf-8",
            newline="\n",
        )
        commit_fixture(tmp)
        rc, out = run_guard(tmp)
        assert rc != 0, f"expected nonzero exit, got {rc}\n{out}"
        assert "FAIL [launcher-shape]" in out, out
        assert "scripts/operator-daemon.ps1" in out, out
    finally:
        cleanup(tmp)


def test_red_powershell_named_launcher_shape():
    tmp = make_fixture("fix/selftest-red-powershell-named-launcher")
    try:
        (tmp / "scripts" / "operator-launch.ps1").write_text(
            "Start-Process -FilePath 'notepad.exe'\n",
            encoding="utf-8",
            newline="\n",
        )
        commit_fixture(tmp)
        rc, out = run_guard(tmp)
        assert rc != 0, f"expected nonzero exit, got {rc}\n{out}"
        assert "FAIL [launcher-shape]" in out, out
        assert "scripts/operator-launch.ps1" in out, out
    finally:
        cleanup(tmp)


def test_red_powershell_direct_invocation_launcher_shape():
    tmp = make_fixture("fix/selftest-red-powershell-direct-launcher")
    try:
        (tmp / "scripts" / "operator-direct-launch.ps1").write_text(
            r"C:\Tools\ordinary-worker.exe --quiet" "\n",
            encoding="utf-8",
            newline="\n",
        )
        commit_fixture(tmp)
        rc, out = run_guard(tmp)
        assert rc != 0, f"expected nonzero exit, got {rc}\n{out}"
        assert "FAIL [launcher-shape]" in out, out
        assert "scripts/operator-direct-launch.ps1" in out, out
    finally:
        cleanup(tmp)


def test_red_powershell_direct_invocation_training_shape():
    tmp = make_fixture("fix/selftest-red-powershell-direct-training")
    try:
        (tmp / "scripts" / "operator-direct.ps1").write_text(
            r"C:\Python310\python.exe scripts/certified_train_launch.py --execute" "\n",
            encoding="utf-8",
            newline="\n",
        )
        commit_fixture(tmp)
        rc, out = run_guard(tmp)
        assert rc != 0, f"expected nonzero exit, got {rc}\n{out}"
        assert "FAIL [launcher-shape]" in out, out
        assert "scripts/operator-direct.ps1" in out, out
    finally:
        cleanup(tmp)


def test_green_powershell_direct_invocation_tokens_in_data():
    tmp = make_fixture("fix/selftest-green-powershell-direct-data")
    try:
        (tmp / "scripts" / "operator-document-launch.ps1").write_text(
            r"# C:\Tools\commented.exe is documentation only" "\n"
            r"$example = 'C:\Tools\string-literal.exe'" "\n"
            r"Write-Host 'C:\Tools\displayed.exe'" "\n",
            encoding="utf-8",
            newline="\n",
        )
        commit_fixture(tmp)
        rc, out = run_guard(tmp)
        assert rc == 0, f"expected zero exit, got {rc}\n{out}"
        assert "ok   [launcher-shape]" in out, out
        assert "FAIL [launcher-shape]" not in out, out
    finally:
        cleanup(tmp)


def test_red_powershell_assignment_capture_launcher_shape():
    tmp = make_fixture("fix/selftest-known-gap-powershell-assignment-capture")
    try:
        (tmp / "scripts" / "operator-capture-launch.ps1").write_text(
            "$out = python scripts/certified_train_launch.py --repo $repo\n",
            encoding="utf-8",
            newline="\n",
        )
        commit_fixture(tmp)
        rc, out = run_guard(tmp)
        assert rc != 0, f"expected nonzero exit, got {rc}\n{out}"
        assert "FAIL [launcher-shape]" in out, out
        assert "scripts/operator-capture-launch.ps1" in out, out
    finally:
        cleanup(tmp)


def test_red_powershell_dynamic_call_operator_launcher_shape():
    tmp = make_fixture("fix/selftest-red-powershell-dynamic-call")
    try:
        (tmp / "scripts" / "operator-dynamic.ps1").write_text(
            "$cmd = 'python'\n& $cmd scripts/certified_train_launch.py\n",
            encoding="utf-8",
            newline="\n",
        )
        commit_fixture(tmp)
        rc, out = run_guard(tmp)
        assert rc != 0, f"expected nonzero exit, got {rc}\n{out}"
        assert "FAIL [launcher-shape]" in out, out
        assert "scripts/operator-dynamic.ps1" in out, out
    finally:
        cleanup(tmp)


def test_red_powershell_opaque_dynamic_command_target():
    tmp = make_fixture("fix/selftest-red-powershell-opaque-dynamic")
    try:
        (tmp / "scripts" / "operator-policy.ps1").write_text(
            "param([string]$cmd, [string]$args)\n& $cmd $args\n",
            encoding="utf-8",
            newline="\n",
        )
        commit_fixture(tmp)
        rc, out = run_guard(tmp)
        assert rc != 0, f"expected nonzero exit, got {rc}\n{out}"
        assert "FAIL [launcher-shape]" in out, out
        assert "scripts/operator-policy.ps1" in out, out
        # A launcher failure must accumulate rather than enabling shell-wide
        # errexit: the load-bearing authority leg still has to execute.
        assert "ok   [authority]" in out, out
    finally:
        cleanup(tmp)


def test_red_powershell_script_root_target_must_exist_in_tree():
    tmp = make_fixture("fix/selftest-red-powershell-missing-script-root-target")
    try:
        (tmp / "scripts" / "operator-policy.ps1").write_text(
            '& (Join-Path $PSScriptRoot "missing-launch.ps1")\n',
            encoding="utf-8",
            newline="\n",
        )
        commit_fixture(tmp)
        rc, out = run_guard(tmp)
        assert rc != 0, f"expected nonzero exit, got {rc}\n{out}"
        assert "FAIL [launcher-shape]" in out, out
        assert "scripts/operator-policy.ps1" in out, out
    finally:
        cleanup(tmp)


def test_red_powershell_ast_engine_absence_refuses():
    """The no-engine branch bypasses scanner execution entirely.

    It proves fail-closed engine selection, but intentionally does not stand in
    for the dynamic-target red above, which exercises a nonzero scanner result
    and proves later guard legs still run.
    """
    tmp = make_fixture("fix/selftest-red-powershell-no-ast-engine")
    try:
        (tmp / "scripts" / "operator-policy.ps1").write_text(
            "Write-Output 'no child launch here'\n",
            encoding="utf-8",
            newline="\n",
        )
        commit_fixture(tmp)
        rc, out = run_guard(
            tmp,
            extra_env={"REPO_GUARD_DISABLE_POWERSHELL_AST_ENGINE": "1"},
        )
        assert rc != 0, f"expected nonzero exit, got {rc}\n{out}"
        assert "FAIL [launcher-shape]" in out, out
        assert "REFUSED: no PowerShell AST engine is available" in out, out
    finally:
        cleanup(tmp)


def test_green_powershell_script_root_target_is_digest_adjudicated():
    tmp = make_fixture("fix/selftest-green-powershell-script-root-target")
    try:
        target = tmp / "scripts" / "prepare-ember-cockpit.ps1"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO_ROOT / "scripts" / "prepare-ember-cockpit.ps1", target)
        (tmp / "scripts" / "operator-policy.ps1").write_text(
            '& (Join-Path (Split-Path $PSCommandPath) "prepare-ember-cockpit.ps1")\n',
            encoding="utf-8",
            newline="\n",
        )
        commit_fixture(tmp)
        rc, out = run_guard(tmp)
        assert rc == 0, f"expected zero exit, got {rc}\n{out}"
        assert "ok   [launcher-shape]" in out, out
        assert "FAIL [launcher-shape]" not in out, out
    finally:
        cleanup(tmp)


def test_red_powershell_process_start_member_launcher_shape():
    tmp = make_fixture("fix/selftest-red-powershell-process-start-member")
    try:
        (tmp / "scripts" / "operator-member.ps1").write_text(
            "[System.Diagnostics.Process]::Start('python.exe', 'train.py')\n",
            encoding="utf-8",
            newline="\n",
        )
        commit_fixture(tmp)
        rc, out = run_guard(tmp)
        assert rc != 0, f"expected nonzero exit, got {rc}\n{out}"
        assert "FAIL [launcher-shape]" in out, out
        assert "scripts/operator-member.ps1" in out, out
    finally:
        cleanup(tmp)


def test_red_powershell_launcher_shape_cannot_hide_behind_selftest_name():
    tmp = make_fixture("fix/selftest-red-powershell-hidden-by-name")
    try:
        hidden = tmp / "scripts" / "operator-launch-selftest.ps1"
        hidden.write_text(
            "& python.exe tools/ember-restart-3b/run_vertical_slice.py governed-vertical\n",
            encoding="utf-8",
            newline="\n",
        )
        commit_fixture(tmp)
        rc, out = run_guard(tmp)
        assert rc != 0, f"expected nonzero exit, got {rc}\n{out}"
        assert "FAIL [launcher-shape]" in out, out
        assert "scripts/operator-launch-selftest.ps1" in out, out
    finally:
        cleanup(tmp)


def test_red_powershell_malformed_source_refuses_even_when_not_named_launcher():
    tmp = make_fixture("fix/selftest-red-powershell-malformed")
    try:
        (tmp / "scripts" / "operator-policy.ps1").write_text(
            "if ($true) {\n",
            encoding="utf-8",
            newline="\n",
        )
        commit_fixture(tmp)
        rc, out = run_guard(tmp)
        assert rc != 0, f"expected nonzero exit, got {rc}\n{out}"
        assert "PowerShell source could not be safely parsed" in out, out
        assert "scripts/operator-policy.ps1" in out, out
    finally:
        cleanup(tmp)


ALL_TESTS = [
    test_red_name_via_hash_match,
    test_red_absolute_path_single_separator,
    test_red_absolute_path_doubled_json_escape,
    test_red_text_attributed_binary_extension_utf16le,
    test_red_utf16le_bom,
    test_red_utf32le_bom,
    test_red_invalid_single_byte_utf8,
    test_green_valid_utf8_non_ascii,
    test_green_clean_fixture,
    test_green_canonical_authority_paths,
    test_red_duplicate_authority_path,
    test_red_invalid_branch_names_safe_recovery,
    test_green_invalid_branch_is_advisory_for_exact_open_pr_head,
    test_green_hashed_denylist_no_match,
    test_ci_fail_closed_no_denylist,
    test_ci_fail_closed_empty_hashed_denylist,
    test_red_name_outside_exclude_scope,
    test_green_name_inside_excluded_path,
    test_trusted_kernel_ignores_subject_guard_and_helpers,
    test_split_kernel_scans_subject_guard_for_runtime_names,
    test_split_kernel_hashed_scan_covers_every_subject_guard_surface,
    test_split_kernel_scans_subject_guard_for_absolute_paths,
    test_required_workflow_uses_base_pinned_kernel,
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
    test_red_names_staged_bypass_worktree_restore,
    test_red_names_hashed_staged_bypass_worktree_restore,
    test_red_resident_cockpit_state_dir,
    test_red_cockpit_state_as_a_file,
    test_green_empty_cockpit_state_dir,
    test_red_pathfrags_staged_bypass_worktree_restore,
    test_green_pr_merge_excludes_live_base_squash_commit,
    test_red_pr_merge_still_rejects_branch_goal_evidence_commit,
    test_red_line_endings_staged_bypass_worktree_restore,
    test_red_powershell_launcher_shape,
    test_red_powershell_launcher_shape_preceding_assignment,
    test_red_powershell_named_launcher_shape,
    test_red_powershell_direct_invocation_launcher_shape,
    test_red_powershell_direct_invocation_training_shape,
    test_green_powershell_direct_invocation_tokens_in_data,
    test_red_powershell_assignment_capture_launcher_shape,
    test_red_powershell_dynamic_call_operator_launcher_shape,
    test_red_powershell_opaque_dynamic_command_target,
    test_red_powershell_script_root_target_must_exist_in_tree,
    test_red_powershell_ast_engine_absence_refuses,
    test_green_powershell_script_root_target_is_digest_adjudicated,
    test_red_powershell_process_start_member_launcher_shape,
    test_red_powershell_launcher_shape_cannot_hide_behind_selftest_name,
    test_red_powershell_malformed_source_refuses_even_when_not_named_launcher,
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
