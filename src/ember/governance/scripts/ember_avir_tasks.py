#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""ember_avir_tasks.py — Task corpus loader for the C14 [REDACTED]-cli resident.

Loads train/heldout splits from:
  data/ember_avir_tasks/train.jsonl
  data/ember_avir_tasks/heldout.jsonl

Exposes each task's verifier assertions to the harness via run_assertions().
All execution is CPU-only. No GPU, no daemon, no [REDACTED].exe invocation here —
this module defines tasks and validates assertion results deterministically.

Usage:
  from ember_avir_tasks import load_split, run_assertions

  tasks = load_split("train")         # list[dict]
  tasks = load_split("heldout")       # list[dict]

  # After the resident drives [REDACTED].exe for task t:
  result = run_assertions(task=t, sandbox_dir="/path/to/sandbox")
  # result: {"pass": bool, "details": list[dict]}

Schema fields (each task dict):
  id                  str   unique task identifier (t001..t016 train; h001..h008 heldout)
  split               str   "train" | "heldout"
  goal_prompt         str   text to inject into [REDACTED].exe via POST /input
  sandbox_setup       dict  {files: {relpath: content_str}, cwd_sentinel: str}
  verifier_assertions list  assertion dicts (see ASSERTION_TYPES below)
  difficulty          str   "easy" | "medium" | "hard"
  notes               str   design rationale (non-load-bearing)
  structural_difference str optional; heldout tasks carry a structural-diff label

ASSERTION_TYPES (file-system, session-JSONL, and corpus-specific):
  file_exists          path: str
  file_not_exists      path: str
  file_contains        path: str, text: str
  file_not_contains    path: str, text: str
  file_min_lines       path: str, min_lines: int
  file_max_lines       path: str, max_lines: int
  file_valid_html      path: str           (checks for <html> or DOCTYPE)
  file_valid_json      path: str           (json.loads succeeds)
  file_valid_xml       path: str           (xml.etree.ElementTree.parse succeeds)
  file_order_asc       path: str, lines_must_be_sorted: bool
  jsonl_no_api_error   (checks session JSONL for isApiErrorMessage: true)
  jsonl_stop_reason_eq value: str          (final stop_reason in session JSONL)
  jsonl_tool_call_count_gte count: int     (number of tool_use blocks in session JSONL)

The harness caller is responsible for:
  1. Setting up the sandbox directory from task["sandbox_setup"]["files"].
  2. Launching [REDACTED].exe with the sandbox as cwd.
  3. Injecting task["goal_prompt"] via POST /input.
  4. Awaiting turn completion (JSONL stop_reason = end_turn).
  5. Passing the sandbox_dir and session_jsonl_path to run_assertions().

Do NOT edit timeshare_pretrain.py, c04_design_bench.py, ember_avir_harness.py,
or ember_resident_igrpo.py. This file is a standalone corpus loader.

STATISTICAL POWER CAVEAT (n=20 heldout tasks):
  McNemar's test on n=20 held-out tasks has limited statistical power.
  The test requires >=5 discordant pairs for adequate sensitivity; with n=20 this
  threshold is only reachable at moderate-to-large effect sizes. Concretely:
    - At Cohen's h ~0.5 (medium effect), power is approximately 0.35-0.45 for a
      two-sided McNemar at alpha=0.05 — well below the conventional 0.80 threshold.
    - Differences of fewer than 4-5 discordant pairs should not be reported as
      statistically significant transfers.
    - Transfer claims MUST disaggregate heldout performance by difficulty level
      (easy/medium/hard) and by structural_difference class, not reported as a
      single aggregate number.
    - Any paper table reporting heldout accuracy should include this n=20 power
      caveat and confidence intervals alongside the point estimate.
  These caveats do NOT invalidate the corpus for qualitative analysis or for
  ablation studies where the comparison is within-corpus (same n).
"""
from __future__ import annotations

import json
import os
import pathlib
import xml.etree.ElementTree as ET
from typing import Any

# ---------------------------------------------------------------------------
# Corpus paths (resolved relative to this script's directory)
# ---------------------------------------------------------------------------

_SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
_DATA_DIR = _SCRIPT_DIR.parent / "data" / "ember_avir_tasks"

TRAIN_PATH = _DATA_DIR / "train.jsonl"
HELDOUT_PATH = _DATA_DIR / "heldout.jsonl"


def load_split(split: str) -> list[dict]:
    """Load all tasks for a given split.

    Args:
        split: "train" or "heldout"

    Returns:
        List of task dicts. Each dict contains at minimum the schema fields:
        id, split, goal_prompt, sandbox_setup, verifier_assertions, difficulty.

    Raises:
        ValueError: if split is not "train" or "heldout"
        FileNotFoundError: if the JSONL file is missing
    """
    if split not in ("train", "heldout"):
        raise ValueError(f"split must be 'train' or 'heldout', got {split!r}")
    path = TRAIN_PATH if split == "train" else HELDOUT_PATH
    if not path.exists():
        raise FileNotFoundError(f"Corpus file not found: {path}")
    tasks = []
    with open(path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                task = json.loads(line)
            except json.JSONDecodeError as e:
                raise ValueError(f"JSON parse error at {path}:{lineno}: {e}") from e
            _validate_task_schema(task, lineno)
            tasks.append(task)
    return tasks


def _validate_task_schema(task: dict, lineno: int) -> None:
    """Raise ValueError if required fields are missing."""
    required = ["id", "split", "goal_prompt", "sandbox_setup", "verifier_assertions", "difficulty"]
    for field in required:
        if field not in task:
            raise ValueError(f"Task at line {lineno} missing required field: {field!r}")
    if not isinstance(task["verifier_assertions"], list):
        raise ValueError(f"Task {task.get('id')} verifier_assertions must be a list")
    if not isinstance(task["sandbox_setup"], dict):
        raise ValueError(f"Task {task.get('id')} sandbox_setup must be a dict")
    if "files" not in task["sandbox_setup"]:
        raise ValueError(f"Task {task.get('id')} sandbox_setup must have 'files' key")


# ---------------------------------------------------------------------------
# Sandbox setup helpers
# ---------------------------------------------------------------------------

def setup_sandbox(task: dict, sandbox_dir: str | os.PathLike) -> pathlib.Path:
    """Write the task's pre-seeded files into sandbox_dir.

    Creates sandbox_dir and any subdirectories. Returns the sandbox Path.
    Idempotent: existing files are overwritten.

    Args:
        task: a task dict from load_split()
        sandbox_dir: directory to use as the [REDACTED].exe cwd

    Returns:
        Resolved sandbox_dir as a pathlib.Path
    """
    sandbox = pathlib.Path(sandbox_dir).resolve()
    sandbox.mkdir(parents=True, exist_ok=True)
    files: dict[str, str] = task["sandbox_setup"].get("files", {})
    for relpath, content in files.items():
        target = sandbox / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return sandbox


# ---------------------------------------------------------------------------
# Assertion runner
# ---------------------------------------------------------------------------

AssertionResult = dict[str, Any]  # {type, pass, detail}


def run_assertions(
    task: dict,
    sandbox_dir: str | os.PathLike,
    session_jsonl_path: str | os.PathLike | None = None,
) -> dict[str, Any]:
    """Execute all verifier assertions for a task after [REDACTED].exe has run.

    File-system assertions are evaluated against sandbox_dir.
    JSONL assertions are evaluated against session_jsonl_path (optional).
    If session_jsonl_path is None, JSONL assertions are marked as SKIPPED.

    Returns:
        {
          "pass": bool,           # True iff all assertions pass (or skip)
          "r": float,             # 1.0 if pass, 0.0 otherwise (C14 binary reward)
          "details": list[dict],  # one entry per assertion
          "task_id": str,
        }
    """
    sandbox = pathlib.Path(sandbox_dir).resolve()
    details: list[AssertionResult] = []
    all_pass = True

    for assertion in task["verifier_assertions"]:
        atype = assertion.get("type", "unknown")
        result = _run_one_assertion(atype, assertion, sandbox, session_jsonl_path)
        details.append({"type": atype, **result})
        if result.get("status") == "FAIL":
            all_pass = False

    return {
        "pass": all_pass,
        "r": 1.0 if all_pass else 0.0,
        "details": details,
        "task_id": task.get("id", "unknown"),
    }


def _run_one_assertion(
    atype: str,
    assertion: dict,
    sandbox: pathlib.Path,
    session_jsonl_path: Any,
) -> AssertionResult:
    """Dispatch a single assertion. Returns {status, detail}."""
    try:
        if atype == "file_exists":
            return _assert_file_exists(sandbox / assertion["path"])
        elif atype == "file_not_exists":
            return _assert_file_not_exists(sandbox / assertion["path"])
        elif atype == "file_contains":
            return _assert_file_contains(sandbox / assertion["path"], assertion["text"])
        elif atype == "file_not_contains":
            return _assert_file_not_contains(sandbox / assertion["path"], assertion["text"])
        elif atype == "file_min_lines":
            return _assert_file_min_lines(sandbox / assertion["path"], assertion["min_lines"])
        elif atype == "file_max_lines":
            return _assert_file_max_lines(sandbox / assertion["path"], assertion["max_lines"])
        elif atype == "file_valid_html":
            return _assert_file_valid_html(sandbox / assertion["path"])
        elif atype == "file_valid_json":
            return _assert_file_valid_json(sandbox / assertion["path"])
        elif atype == "file_valid_xml":
            return _assert_file_valid_xml(sandbox / assertion["path"])
        elif atype == "file_order_asc":
            return _assert_file_order_asc(sandbox / assertion["path"])
        elif atype in ("jsonl_no_api_error", "jsonl_stop_reason_eq", "jsonl_tool_call_count_gte"):
            if session_jsonl_path is None:
                return {"status": "SKIP", "detail": "session_jsonl_path not provided"}
            return _run_jsonl_assertion(atype, assertion, pathlib.Path(session_jsonl_path))
        else:
            return {"status": "SKIP", "detail": f"unrecognised assertion type: {atype!r}"}
    except Exception as exc:
        return {"status": "FAIL", "detail": f"assertion error: {exc}"}


# ---------------------------------------------------------------------------
# File-system assertion implementations
# ---------------------------------------------------------------------------

def _assert_file_exists(path: pathlib.Path) -> AssertionResult:
    if path.exists() and path.is_file():
        return {"status": "PASS", "detail": str(path)}
    return {"status": "FAIL", "detail": f"file not found: {path}"}


def _assert_file_not_exists(path: pathlib.Path) -> AssertionResult:
    if not path.exists():
        return {"status": "PASS", "detail": f"correctly absent: {path}"}
    return {"status": "FAIL", "detail": f"file unexpectedly exists: {path}"}


def _assert_file_not_contains(path: pathlib.Path, text: str) -> AssertionResult:
    if not path.exists():
        return {"status": "FAIL", "detail": f"file not found: {path}"}
    content = path.read_text(encoding="utf-8", errors="replace")
    if text not in content:
        return {"status": "PASS", "detail": f"correctly absent {text!r} in {path.name}"}
    return {"status": "FAIL", "detail": f"forbidden text {text!r} found in {path.name}"}


def _assert_file_contains(path: pathlib.Path, text: str) -> AssertionResult:
    if not path.exists():
        return {"status": "FAIL", "detail": f"file not found: {path}"}
    content = path.read_text(encoding="utf-8", errors="replace")
    if text in content:
        return {"status": "PASS", "detail": f"found {text!r} in {path.name}"}
    return {"status": "FAIL", "detail": f"{text!r} not found in {path.name}"}


def _assert_file_min_lines(path: pathlib.Path, min_lines: int) -> AssertionResult:
    if not path.exists():
        return {"status": "FAIL", "detail": f"file not found: {path}"}
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    n = len(lines)
    if n >= min_lines:
        return {"status": "PASS", "detail": f"{n} lines >= {min_lines}"}
    return {"status": "FAIL", "detail": f"{n} lines < required {min_lines}"}


def _assert_file_max_lines(path: pathlib.Path, max_lines: int) -> AssertionResult:
    if not path.exists():
        return {"status": "FAIL", "detail": f"file not found: {path}"}
    lines = [l for l in path.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()]
    n = len(lines)
    if n <= max_lines:
        return {"status": "PASS", "detail": f"{n} non-empty lines <= {max_lines}"}
    return {"status": "FAIL", "detail": f"{n} non-empty lines > allowed {max_lines}"}


def _assert_file_valid_html(path: pathlib.Path) -> AssertionResult:
    if not path.exists():
        return {"status": "FAIL", "detail": f"file not found: {path}"}
    content = path.read_text(encoding="utf-8", errors="replace").lower()
    if "<html" in content or "<!doctype html" in content or "<head" in content or "<body" in content:
        return {"status": "PASS", "detail": "HTML markers present"}
    return {"status": "FAIL", "detail": "no HTML structural markers found (<html>, <!doctype>, <head>, <body>)"}


def _assert_file_valid_json(path: pathlib.Path) -> AssertionResult:
    if not path.exists():
        return {"status": "FAIL", "detail": f"file not found: {path}"}
    try:
        json.loads(path.read_text(encoding="utf-8", errors="replace"))
        return {"status": "PASS", "detail": "valid JSON"}
    except json.JSONDecodeError as e:
        return {"status": "FAIL", "detail": f"JSON parse error: {e}"}


def _assert_file_valid_xml(path: pathlib.Path) -> AssertionResult:
    if not path.exists():
        return {"status": "FAIL", "detail": f"file not found: {path}"}
    try:
        ET.parse(str(path))
        return {"status": "PASS", "detail": "valid XML"}
    except ET.ParseError as e:
        return {"status": "FAIL", "detail": f"XML parse error: {e}"}


def _assert_file_order_asc(path: pathlib.Path) -> AssertionResult:
    """Assert all non-empty lines are in non-decreasing lexicographic order."""
    if not path.exists():
        return {"status": "FAIL", "detail": f"file not found: {path}"}
    lines = [l for l in path.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()]
    if lines == sorted(lines):
        return {"status": "PASS", "detail": f"{len(lines)} lines are sorted"}
    return {"status": "FAIL", "detail": "lines are not in ascending order"}


# ---------------------------------------------------------------------------
# JSONL assertion implementations
# ---------------------------------------------------------------------------

def _load_session_jsonl(session_jsonl_path: pathlib.Path) -> list[dict]:
    """Parse all JSON lines from the session JSONL. Skips malformed lines."""
    records = []
    if not session_jsonl_path.exists():
        return records
    with open(session_jsonl_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return records


def _run_jsonl_assertion(
    atype: str,
    assertion: dict,
    session_jsonl_path: pathlib.Path,
) -> AssertionResult:
    records = _load_session_jsonl(session_jsonl_path)

    if atype == "jsonl_no_api_error":
        errors = [r for r in records if r.get("isApiErrorMessage")]
        if not errors:
            return {"status": "PASS", "detail": "no API error messages in session"}
        return {"status": "FAIL", "detail": f"{len(errors)} API error(s) in session"}

    elif atype == "jsonl_stop_reason_eq":
        expected = assertion.get("value", "end_turn")
        # Find the last assistant record with a stop_reason
        stop_reasons = []
        for r in records:
            msg = r.get("message", {})
            sr = msg.get("stop_reason") if isinstance(msg, dict) else None
            if sr is not None:
                stop_reasons.append(sr)
        if stop_reasons and stop_reasons[-1] == expected:
            return {"status": "PASS", "detail": f"final stop_reason={stop_reasons[-1]!r}"}
        last = stop_reasons[-1] if stop_reasons else None
        return {"status": "FAIL", "detail": f"expected stop_reason={expected!r}, got {last!r}"}

    elif atype == "jsonl_tool_call_count_gte":
        required = assertion.get("count", 1)
        tool_uses = 0
        for r in records:
            msg = r.get("message", {})
            content = msg.get("content", []) if isinstance(msg, dict) else []
            if isinstance(content, list):
                tool_uses += sum(1 for blk in content if isinstance(blk, dict) and blk.get("type") == "tool_use")
        if tool_uses >= required:
            return {"status": "PASS", "detail": f"{tool_uses} tool calls >= {required}"}
        return {"status": "FAIL", "detail": f"{tool_uses} tool calls < required {required}"}

    return {"status": "SKIP", "detail": f"unhandled JSONL assertion: {atype!r}"}


# ---------------------------------------------------------------------------
# Corpus statistics helper
# ---------------------------------------------------------------------------

def corpus_stats(tasks: list[dict]) -> dict:
    """Return counts useful for validating the corpus size and assertion coverage."""
    assertion_type_counts: dict[str, int] = {}
    for task in tasks:
        for a in task.get("verifier_assertions", []):
            t = a.get("type", "unknown")
            assertion_type_counts[t] = assertion_type_counts.get(t, 0) + 1
    difficulties = {}
    for task in tasks:
        d = task.get("difficulty", "unknown")
        difficulties[d] = difficulties.get(d, 0) + 1
    return {
        "n_tasks": len(tasks),
        "difficulties": difficulties,
        "assertion_type_counts": assertion_type_counts,
        "total_assertions": sum(assertion_type_counts.values()),
    }


# ---------------------------------------------------------------------------
# Self-test (CPU-only — validates parsing, no [REDACTED].exe required)
# ---------------------------------------------------------------------------

def _anti_echo_selftest(tasks: list[dict], tmpdir_base: str) -> tuple[bool, list[str]]:
    """Anti-echo selftest: for every task simulate three attacks.

    Attack 1 — PROMPT ECHO: write the entire goal_prompt text into every expected output file.
    Attack 2 — SEED CONCAT ECHO: write all pre-seeded file contents concatenated into every
                output file.
    Attack 3 — INDIVIDUAL SEED FILE COPY: for each seed file individually, copy that file's
                content verbatim into EVERY expected output path, then assert at least one
                file-system assertion FAILS. This catches tasks where a single seed file
                happens to satisfy all assertions (the h013 class of vulnerability).

    All three attacks must score R=0 (at least one file-system assertion fails per attack).
    This is CPU-only. No [REDACTED].exe, no GPU, no daemon.

    The mechanism: for each task we identify output files (those referenced in
    verifier_assertions but NOT in sandbox_setup["files"]), simulate the attack writes, run
    run_assertions() with session_jsonl_path=None (JSONL assertions skipped), and assert
    the result is R=0 on file-system assertions.

    Returns:
        (all_passed: bool, failure_messages: list[str])
    """
    import tempfile as _tempfile
    failures: list[str] = []

    _FS_ASSERTION_TYPES = (
        "file_contains", "file_not_contains", "file_exists", "file_not_exists",
        "file_min_lines", "file_max_lines",
        "file_valid_html", "file_valid_json", "file_valid_xml", "file_order_asc",
    )

    for task in tasks:
        tid = task["id"]
        seed_files: dict[str, str] = task["sandbox_setup"].get("files", {})

        # Identify output paths from verifier assertions (targets NOT in sandbox seed)
        output_paths: set[str] = set()
        for a in task["verifier_assertions"]:
            if a.get("type") in _FS_ASSERTION_TYPES:
                p = a.get("path", "")
                if p and p not in seed_files:
                    output_paths.add(p)

        if not output_paths:
            # No output file assertions — skip echo test (JSONL-only task)
            continue

        # Collect the text that an echo attacker has access to
        prompt_text: str = task["goal_prompt"]
        seed_text: str = "\n".join(seed_files.values())

        # Attack 1 + 2: prompt echo and concatenated seed echo
        echo_payloads: dict[str, str] = {
            "prompt_echo": prompt_text,
            "seed_concat_echo": seed_text if seed_text.strip() else prompt_text,
        }

        # Attack 3: individual seed file copies (one per seed file)
        for seed_rel, seed_content in seed_files.items():
            echo_payloads[f"individual_seed_copy:{seed_rel}"] = seed_content

        for attack_name, payload in echo_payloads.items():
            with _tempfile.TemporaryDirectory(dir=tmpdir_base) as tmpdir:
                sb = setup_sandbox(task, tmpdir)
                # Write the echo payload into every output file
                for rel in output_paths:
                    target = sb / rel
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(payload, encoding="utf-8")
                result = run_assertions(task, sb, session_jsonl_path=None)
                # Only evaluate file-system assertions (JSONL are SKIP without session)
                fs_fails = [
                    d for d in result["details"]
                    if not d["type"].startswith("jsonl_") and d["status"] == "FAIL"
                ]
                fs_passes = [
                    d for d in result["details"]
                    if not d["type"].startswith("jsonl_") and d["status"] == "PASS"
                ]
                # Echo attack MUST fail at least one file assertion
                if fs_fails:
                    # At least one assertion correctly rejected the echo — good
                    pass
                elif not fs_passes:
                    # No file assertions to evaluate — skip
                    pass
                else:
                    # All file assertions passed on an echo payload — echo-gameable!
                    failures.append(
                        f"{tid} ECHO-GAMEABLE [{attack_name}]: all {len(fs_passes)} "
                        f"file assertions passed on echo payload"
                    )

    return (len(failures) == 0, failures)


# Correct answers for the positive selftest (computed values per task).
# These are the values the verifier checks; they do NOT appear in goal_prompts.
_POSITIVE_SELFTEST_ANSWERS: dict[str, dict[str, str]] = {
    # train
    "t001": {"output.txt": "101\n"},
    "t002": {"count.txt": "5\n"},
    "t003": {"max.txt": "max: 87\n"},
    "t004": {"sorted.txt": "apricot\nblueberry\nkiwi\nmango\npeach\n"},
    "t005": {"split.txt": "north\nsouth\neast\nwest\n"},
    "t006": {"total.txt": "14\n"},
    "t007": {"inverted.txt": "red=color\nlarge=size\nheavy=weight\n"},
    "t008": {"winner.txt": "winner: bob\n"},
    "t009": {"vowel_count.txt": "vowel_count: 4\n"},
    "t010": {"word_count.txt": "9\n"},
    "t011": {"row_sums.txt": "6\n15\n24\n"},
    "t012": {"char_counts.txt": "3\n8\n2\n"},
    "t013": {"dedup_stats.txt": "unique_count: 4\n"},
    "t014": {"diffs.txt": "35\n16\n33\n"},
    "t015": {"freq.txt": "bird:1\ncat:3\ndog:2\n"},
    "t016": {"products.txt": "42\n33\n32\n"},
    "t017": {"error_count.txt": "3\n"},
    "t018": {"stock_report.txt": "low_stock_count: 3\n"},
    "t019": {"line_tally.txt": "total_lines: 5\n"},
    "t020": {"average.txt": "25.0\n"},
    "t021": {"reversed.txt": "1: fifth\n2: fourth\n3: third\n4: second\n5: first\n"},
    "t022": {"rename_script.sh": "mv foo.txt bar.txt\nmv data.csv results.csv\n"},
    "t023": {"class_avg.txt": "80\n"},
    "t024": {"flag_summary.txt": "enabled_count: 3\n"},
    # heldout
    "h001": {"running_total.txt": "10\n30\n35\n50\n"},
    "h002": {"upper.txt": "RIVER DELTA\nMOUNTAIN PASS\nCOASTAL PLAIN\n"},
    "h003": {"swapped.txt": "moon sun\nwater fire\nsky earth\n"},
    "h004": {"even_odd.txt": "odd\neven\nodd\neven\nodd\n"},
    "h005": {"event_summary.txt": "distinct_events: 3\n"},
    "h006": {"delta.txt": "8\n-3\n9\n"},
    "h007": {"lengths.txt": "10\n9\n3\n"},
    "h008": {"stats.txt": "min: 8\nmax: 71\n"},
    "h009": {"reversed_words.txt": "edoc\natad\npool\n"},
    "h010": {"doubled_table.txt": "alpha:18\nbeta:28\ngamma:10\n"},
    "h011": {"result.txt": "column_sum: 33\n"},
    "h012": {"position.txt": "max_position: 4\n"},
    "h013": {"intersection.txt": "dog\nfox\n"},
    "h014": {"time_summary.txt": "hours: 4\nremaining_minutes: 30\n"},
    "h015": {"config.txt": "host=localhost\nport=8080\nmode=debug\n"},
    "h016": {"buckets.txt": "even: 3\nodd: 3\n"},
    "h017": {"trim_report.txt": "trimmed_chars: 12\n"},
    "h018": {"discounted.txt": "widget 180\ngadget 495\ndoodle 72\n"},
    "h019": {"all_tags.txt": "blue\ngreen\npurple\nred\nyellow\n"},
    "h020": {"palindrome.txt": "level: yes\nbrick: no\nracecar: yes\ntiger: no\ncivic: yes\n"},
}


def _positive_selftest(tasks: list[dict], tmpdir_base: str) -> tuple[bool, list[str]]:
    """Positive selftest: write correct computed answers and assert R=1 on file assertions."""
    import tempfile as _tempfile
    failures: list[str] = []

    for task in tasks:
        tid = task["id"]
        answers = _POSITIVE_SELFTEST_ANSWERS.get(tid)
        if answers is None:
            continue  # No positive test registered for this task

        with _tempfile.TemporaryDirectory(dir=tmpdir_base) as tmpdir:
            sb = setup_sandbox(task, tmpdir)
            for rel, content in answers.items():
                target = sb / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
            result = run_assertions(task, sb, session_jsonl_path=None)
            fs_details = [d for d in result["details"] if not d["type"].startswith("jsonl_")]
            failed = [d for d in fs_details if d["status"] == "FAIL"]
            if failed:
                failures.append(
                    f"{tid} POSITIVE FAIL: {failed}"
                )

    return (len(failures) == 0, failures)


def _self_test() -> None:
    """Parse both JSONL files and validate schema, corpus stats, anti-echo, and positive answers.

    Anti-echo selftest mechanism (three attack vectors):
      1. PROMPT ECHO: write the full goal_prompt text into every expected output file.
      2. SEED CONCAT ECHO: write all pre-seeded file contents (concatenated) into every output.
      3. INDIVIDUAL SEED FILE COPY: for each seed file individually, copy that file verbatim
         into every expected output path; assert at least one file-system assertion FAILS.
         This is the vector that caught h013 (SET_INTERSECTION was gameable by copying a
         coincidentally-sorted seed file that passed file_order_asc + file_contains).
      All three attacks must score R=0 (at least one file assertion FAILS per attack).
      Then a positive selftest writes the known-correct computed answer and asserts R=1.
    All file I/O is into temporary directories. CPU-only, no [REDACTED].exe.
    """
    import tempfile
    print("=== ember_avir_tasks self-test ===")
    ok = True

    all_tasks: list[dict] = []
    for split in ("train", "heldout"):
        try:
            tasks = load_split(split)
        except Exception as e:
            print(f"FAIL  load_split({split!r}): {e}")
            ok = False
            continue

        all_tasks.extend(tasks)
        stats = corpus_stats(tasks)
        print(f"PASS  load_split({split!r}): {stats['n_tasks']} tasks, "
              f"{stats['total_assertions']} assertions, "
              f"difficulties={stats['difficulties']}, "
              f"assertion_types={list(stats['assertion_type_counts'])}")

        # Check all IDs are unique within split
        ids = [t["id"] for t in tasks]
        if len(ids) != len(set(ids)):
            print(f"FAIL  {split}: duplicate task IDs: {[i for i in ids if ids.count(i) > 1]}")
            ok = False
        else:
            print(f"PASS  {split}: all IDs unique")

        # Check split field matches
        wrong_split = [t["id"] for t in tasks if t["split"] != split]
        if wrong_split:
            print(f"FAIL  {split}: tasks with wrong split field: {wrong_split}")
            ok = False
        else:
            print(f"PASS  {split}: all tasks have correct split field")

        # Check each task has at least one file_exists or file_contains assertion
        no_fs = [t["id"] for t in tasks if not any(
            a["type"] in ("file_exists", "file_contains", "file_not_exists")
            for a in t["verifier_assertions"]
        )]
        if no_fs:
            print(f"WARN  {split}: tasks with no file-system assertions: {no_fs}")
        else:
            print(f"PASS  {split}: all tasks have at least one file-system assertion")

    # Cross-split ID uniqueness
    try:
        train_ids = {t["id"] for t in load_split("train")}
        heldout_ids = {t["id"] for t in load_split("heldout")}
        overlap = train_ids & heldout_ids
        if overlap:
            print(f"FAIL  cross-split: overlapping IDs: {overlap}")
            ok = False
        else:
            print(f"PASS  cross-split: no ID overlap between train and heldout")
    except Exception as e:
        print(f"FAIL  cross-split check: {e}")
        ok = False

    if not all_tasks:
        print("\nFAILURES DETECTED (no tasks loaded)")
        raise SystemExit(1)

    with tempfile.TemporaryDirectory() as tmpdir_base:
        # Anti-echo selftest
        echo_ok, echo_failures = _anti_echo_selftest(all_tasks, tmpdir_base)
        if echo_ok:
            print(f"PASS  anti-echo selftest: all {len(all_tasks)} tasks resist all 3 echo attack vectors (prompt/seed-concat/individual-seed-copy)")
        else:
            for msg in echo_failures:
                print(f"FAIL  {msg}")
            ok = False

        # Positive selftest
        pos_ok, pos_failures = _positive_selftest(all_tasks, tmpdir_base)
        if pos_ok:
            tested = sum(1 for t in all_tasks if t["id"] in _POSITIVE_SELFTEST_ANSWERS)
            print(f"PASS  positive selftest: {tested} tasks return R=1 on correct computed answers")
        else:
            for msg in pos_failures:
                print(f"FAIL  {msg}")
            ok = False

    print(f"\n{'ALL PASS' if ok else 'FAILURES DETECTED'}")
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    import sys
    if "--test" in sys.argv or len(sys.argv) == 1:
        _self_test()
    else:
        print("Usage: python ember_avir_tasks.py [--test]")
        print("  --test  run self-test (default)")
