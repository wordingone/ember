#!/usr/bin/env python3
"""ember_cbase_avir_data_v2.py — C-BASE [REDACTED]-task pretrain corpus REDO.

Closes all four defects from the REJECT verdict:
  Defect A: NO sandbox pre-seed — sandbox is CLEARED; file written only DURING
            synthesized turn (mtime gate must genuinely pass).
  Defect B: session_jsonl_path is NEVER None — full assertion stack fires,
            including jsonl_tool_call_this_turn, file_created_this_turn,
            jsonl_stop_reason_eq, jsonl_tool_call_count_gte.
  Defect C: [REDACTED].exe canonical wire format (JSONL assistant entries), NOT
            <write_file> pseudo-tags.
  Defect D: answers COMPUTED from sandbox input via real Python — no hardcoded
            _CORRECT_ANSWERS dict.

HARD RULES:
  - TRAIN-ONLY FIREWALL: raises on any heldout id (h0xx). Checked at entry +
    per-iteration. Heldout ids must never enter corpus or be readable into it.
  - Frozen tokenizer: nc-ladder/domains/model/tokenizer/tokenizer.json, SHA256 2c557e7f...,
    vocab 32000. All token ids must be < 32000.
  - No GPU, no daemon — CPU only.
  - Do NOT edit timeshare_pretrain.py or ember_avir_harness.py (read-only deps).

Usage:
    python scripts/ember_cbase_avir_data_v2.py
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import sys
import tempfile
import time
from typing import Any

# ---------------------------------------------------------------------------
# Repo paths
# ---------------------------------------------------------------------------

_HERE = pathlib.Path(__file__).resolve().parent
_REPO = _HERE.parent
_DATA_DIR = _REPO / "data" / "cbase_pretrain"
_TOK_PATH = _REPO / "tokenizer" / "tokenizer.json"

sys.path.insert(0, str(_HERE))

from ember_avir_tasks import load_split, setup_sandbox  # noqa: E402
from ember_avir_harness import (  # noqa: E402
    TurnResult,
    _parse_jsonl_entries,
    _extract_turn_signal,
    run_assertions as harness_run_assertions,
)
from timeshare_pretrain import write_packed_shard, PackedShardLoader  # noqa: E402

# ember_avir_tasks.run_assertions (the weak path that skips JSONL assertions
# when session_jsonl_path=None) is intentionally NOT imported here.
# We use harness_run_assertions (from ember_avir_harness) which always fires
# the full assertion stack.

# ---------------------------------------------------------------------------
# TRAIN-ONLY FIREWALL
# ---------------------------------------------------------------------------

_HELDOUT_PATTERN = re.compile(r"^h\d{3}$")


def _assert_not_heldout(task_id: str) -> None:
    """Raise if task_id matches the heldout pattern h001-h020."""
    if _HELDOUT_PATTERN.match(task_id):
        raise ValueError(
            f"FIREWALL VIOLATION: heldout task id {task_id!r} must never "
            f"enter the pretrain corpus. Train-only firewall triggered."
        )


# ---------------------------------------------------------------------------
# Tokenizer loader (same as v1 — added-token-matching-disabled-v1)
# ---------------------------------------------------------------------------

def _load_production_tokenizer():
    """Load frozen ByteLevel BPE tokenizer with added_tokens stripped in-memory."""
    from tokenizers import Tokenizer
    with open(_TOK_PATH, "rb") as f:
        d = json.loads(f.read().decode("utf-8"))
    literals = [a["content"] for a in d.get("added_tokens", [])]
    d["added_tokens"] = []
    tk = Tokenizer.from_str(json.dumps(d))
    for lit in literals:
        bad = [i for i in tk.encode(lit, add_special_tokens=False).ids if i < 8]
        if bad:
            raise ValueError(
                f"added-token strip failed: literal {lit!r} still encodes to "
                f"reserved id(s) {bad}"
            )
    return tk


# ---------------------------------------------------------------------------
# Answer computation — computed from sandbox input files, NOT hardcoded
# ---------------------------------------------------------------------------

def _compute_answer(task: dict, sandbox: pathlib.Path) -> dict[str, str]:
    """Compute the correct output content by executing the task's transformation
    over the REAL sandbox input files.

    Returns a dict mapping output_relpath -> content_string.
    Raises ValueError if the task id is not recognised.
    """
    tid = task["id"]
    _assert_not_heldout(tid)  # firewall: per-iteration check

    if tid == "t001":
        # Read numbers.txt, sum integers, write to output.txt
        nums = [int(x) for x in (sandbox / "numbers.txt").read_text().splitlines() if x.strip()]
        return {"output.txt": str(sum(nums)) + "\n"}

    elif tid == "t002":
        # Read words.txt, count lines, write to count.txt
        lines = [l for l in (sandbox / "words.txt").read_text().splitlines() if l.strip() or True]
        # count all lines (including blank)
        raw = (sandbox / "words.txt").read_text()
        n = len([l for l in raw.splitlines()])
        return {"count.txt": str(n) + "\n"}

    elif tid == "t003":
        # Read values.txt, find max, write 'max: N' to max.txt
        vals = [int(x) for x in (sandbox / "values.txt").read_text().splitlines() if x.strip()]
        return {"max.txt": f"max: {max(vals)}\n"}

    elif tid == "t004":
        # Read items.txt, sort lines, write to sorted.txt
        lines = [l for l in (sandbox / "items.txt").read_text().splitlines() if l.strip()]
        return {"sorted.txt": "\n".join(sorted(lines)) + "\n"}

    elif tid == "t005":
        # Read tokens.txt (space-separated words on one line), write one per line to split.txt
        raw = (sandbox / "tokens.txt").read_text().strip()
        words = raw.split()
        return {"split.txt": "\n".join(words) + "\n"}

    elif tid == "t006":
        # Read costs.txt (item:price), sum prices, write total to total.txt
        total = 0
        for line in (sandbox / "costs.txt").read_text().splitlines():
            line = line.strip()
            if line and ":" in line:
                total += int(line.split(":", 1)[1])
        return {"total.txt": str(total) + "\n"}

    elif tid == "t007":
        # Read pairs.txt (key=value), write inverted (value=key) to inverted.txt
        lines = []
        for line in (sandbox / "pairs.txt").read_text().splitlines():
            line = line.strip()
            if "=" in line:
                k, v = line.split("=", 1)
                lines.append(f"{v}={k}")
        return {"inverted.txt": "\n".join(lines) + "\n"}

    elif tid == "t008":
        # Read scores.txt (name:score), find winner (max score), write 'winner: NAME'
        best_name, best_score = None, None
        for line in (sandbox / "scores.txt").read_text().splitlines():
            line = line.strip()
            if ":" in line:
                name, score_s = line.split(":", 1)
                score = int(score_s)
                if best_score is None or score > best_score:
                    best_score = score
                    best_name = name
        return {"winner.txt": f"winner: {best_name}\n"}

    elif tid == "t009":
        # Read tagged.txt (words), count vowel-starting, write 'vowel_count: N'
        vowels = set("aeiouAEIOU")
        count = sum(
            1 for line in (sandbox / "tagged.txt").read_text().splitlines()
            if line.strip() and line.strip()[0] in vowels
        )
        return {"vowel_count.txt": f"vowel_count: {count}\n"}

    elif tid == "t010":
        # Read sentences.txt, count total words, write integer to word_count.txt
        total_words = 0
        for line in (sandbox / "sentences.txt").read_text().splitlines():
            total_words += len(line.split())
        return {"word_count.txt": str(total_words) + "\n"}

    elif tid == "t011":
        # Read matrix.txt (space-sep ints per line), write row sums to row_sums.txt
        sums = []
        for line in (sandbox / "matrix.txt").read_text().splitlines():
            line = line.strip()
            if line:
                sums.append(str(sum(int(x) for x in line.split())))
        return {"row_sums.txt": "\n".join(sums) + "\n"}

    elif tid == "t012":
        # Read lengths.txt (one word per line), write char lengths to char_counts.txt
        lengths = []
        for line in (sandbox / "lengths.txt").read_text().splitlines():
            word = line.strip()
            if word:
                lengths.append(str(len(word)))
        return {"char_counts.txt": "\n".join(lengths) + "\n"}

    elif tid == "t013":
        # Read duplicates.txt, count unique lines, write 'unique_count: N'
        lines = [l.strip() for l in (sandbox / "duplicates.txt").read_text().splitlines() if l.strip()]
        return {"dedup_stats.txt": f"unique_count: {len(set(lines))}\n"}

    elif tid == "t014":
        # Read ranges.txt (low:high), compute high-low per line, write to diffs.txt
        diffs = []
        for line in (sandbox / "ranges.txt").read_text().splitlines():
            line = line.strip()
            if ":" in line:
                lo, hi = line.split(":", 1)
                diffs.append(str(int(hi) - int(lo)))
        return {"diffs.txt": "\n".join(diffs) + "\n"}

    elif tid == "t015":
        # Read words2.txt, count word frequencies, write sorted 'word:count' to freq.txt
        counts: dict[str, int] = {}
        for line in (sandbox / "words2.txt").read_text().splitlines():
            word = line.strip()
            if word:
                counts[word] = counts.get(word, 0) + 1
        lines = [f"{w}:{c}" for w, c in sorted(counts.items())]
        return {"freq.txt": "\n".join(lines) + "\n"}

    elif tid == "t016":
        # Read coords.txt (x,y), compute x*y per line, write to products.txt
        prods = []
        for line in (sandbox / "coords.txt").read_text().splitlines():
            line = line.strip()
            if "," in line:
                x, y = line.split(",", 1)
                prods.append(str(int(x) * int(y)))
        return {"products.txt": "\n".join(prods) + "\n"}

    elif tid == "t017":
        # Read log.txt (LEVEL: msg), count ERROR lines, write integer to error_count.txt
        count = sum(
            1 for line in (sandbox / "log.txt").read_text().splitlines()
            if line.startswith("ERROR:")
        )
        return {"error_count.txt": str(count) + "\n"}

    elif tid == "t018":
        # Read inventory.txt (item:qty), count items with qty < 10, write 'low_stock_count: N'
        count = 0
        for line in (sandbox / "inventory.txt").read_text().splitlines():
            line = line.strip()
            if ":" in line:
                _, qty_s = line.split(":", 1)
                if int(qty_s) < 10:
                    count += 1
        return {"stock_report.txt": f"low_stock_count: {count}\n"}

    elif tid == "t019":
        # Read a.txt and b.txt, count total lines, write 'total_lines: N'
        a_lines = len([l for l in (sandbox / "a.txt").read_text().splitlines()])
        b_lines = len([l for l in (sandbox / "b.txt").read_text().splitlines()])
        return {"line_tally.txt": f"total_lines: {a_lines + b_lines}\n"}

    elif tid == "t020":
        # Read numbers2.txt, compute average (1 decimal place), write to average.txt
        nums = [float(x) for x in (sandbox / "numbers2.txt").read_text().splitlines() if x.strip()]
        avg = round(sum(nums) / len(nums), 1)
        return {"average.txt": f"{avg}\n"}

    elif tid == "t021":
        # Read tokens2.txt (one word per line), write reversed+numbered to reversed.txt
        words = [l.strip() for l in (sandbox / "tokens2.txt").read_text().splitlines() if l.strip()]
        reversed_words = list(reversed(words))
        lines = [f"{i + 1}: {w}" for i, w in enumerate(reversed_words)]
        return {"reversed.txt": "\n".join(lines) + "\n"}

    elif tid == "t022":
        # Read mapping.txt (old new), write 'mv old new' per line to rename_script.sh
        mv_lines = []
        for line in (sandbox / "mapping.txt").read_text().splitlines():
            parts = line.strip().split()
            if len(parts) == 2:
                mv_lines.append(f"mv {parts[0]} {parts[1]}")
        return {"rename_script.sh": "\n".join(mv_lines) + "\n"}

    elif tid == "t023":
        # Read grades.txt (student:grade), compute average (round to int), write to class_avg.txt
        grades = []
        for line in (sandbox / "grades.txt").read_text().splitlines():
            line = line.strip()
            if ":" in line:
                _, g = line.split(":", 1)
                grades.append(int(g))
        avg = round(sum(grades) / len(grades))
        return {"class_avg.txt": str(avg) + "\n"}

    elif tid == "t024":
        # Read flags.txt (key:true|false), count true flags, write 'enabled_count: N'
        count = 0
        for line in (sandbox / "flags.txt").read_text().splitlines():
            line = line.strip()
            if ":" in line:
                _, val = line.split(":", 1)
                if val.strip().lower() == "true":
                    count += 1
        return {"flag_summary.txt": f"enabled_count: {count}\n"}

    else:
        raise ValueError(f"_compute_answer: unrecognised task id {tid!r}")


# ---------------------------------------------------------------------------
# Canonical JSONL entry builders ([REDACTED].exe wire format)
# ---------------------------------------------------------------------------

def _make_read_entry(rel_path: str, entry_id: str = "tu_1") -> dict:
    """Build a canonical Read tool_use JSONL entry."""
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "stop_reason": "tool_use",
            "usage": {"input_tokens": 120, "output_tokens": 30},
            "content": [
                {
                    "type": "tool_use",
                    "id": entry_id,
                    "name": "Read",
                    "input": {"file_path": rel_path},
                }
            ],
        },
    }


def _make_write_entry(rel_path: str, content: str, entry_id: str = "tu_2") -> dict:
    """Build a canonical Write tool_use JSONL entry."""
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "stop_reason": "tool_use",
            "usage": {"input_tokens": 150, "output_tokens": 50},
            "content": [
                {
                    "type": "tool_use",
                    "id": entry_id,
                    "name": "Write",
                    "input": {"file_path": rel_path, "content": content},
                }
            ],
        },
    }


def _make_end_turn_entry() -> dict:
    """Build a canonical end_turn JSONL entry."""
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 180, "output_tokens": 20},
            "content": [{"type": "text", "text": "Done."}],
        },
    }


def _build_session_entries(task: dict, answer: dict[str, str]) -> list[dict]:
    """Build the list of JSONL entries for the synthesized [REDACTED].exe session.

    Structure determined by jsonl_tool_call_count_gte (N=2 or N=3):
      N=2 (most tasks): Read(input_file) -> Write(output_file) -> end_turn
      N=3 (t019 only):  Read(a.txt) -> Read(b.txt) -> Write(output_file) -> end_turn
      N/A (t001 only):  Write(output_file) -> end_turn   (no gte assertion)

    The number of tool_use entries MUST satisfy gte:N for the assertion to pass.
    """
    tid = task["id"]

    # Determine gte from verifier_assertions
    gte = None
    for a in task["verifier_assertions"]:
        if a.get("type") == "jsonl_tool_call_count_gte":
            gte = a["count"]
            break

    # Get the input files (seed files) and output files (answer keys)
    input_files = list(task["sandbox_setup"].get("files", {}).keys())
    output_file = list(answer.keys())[0]
    output_content = answer[output_file]

    entries = []

    if gte is None:
        # t001: no gte, just Write + end_turn (1 tool_use satisfies built-in gate)
        entries.append(_make_write_entry(output_file, output_content, "tu_1"))
    elif gte == 2:
        # Standard: Read(first_input) -> Write(output) -> end_turn
        read_file = input_files[0] if input_files else "input.txt"
        entries.append(_make_read_entry(read_file, "tu_1"))
        entries.append(_make_write_entry(output_file, output_content, "tu_2"))
    elif gte == 3:
        # t019: Read(a.txt) -> Read(b.txt) -> Write(output) -> end_turn
        if len(input_files) >= 2:
            entries.append(_make_read_entry(input_files[0], "tu_1"))
            entries.append(_make_read_entry(input_files[1], "tu_2"))
        else:
            # Fallback: duplicate the read if only one input
            entries.append(_make_read_entry(input_files[0], "tu_1"))
            entries.append(_make_read_entry(input_files[0], "tu_2"))
        entries.append(_make_write_entry(output_file, output_content, "tu_3"))
    else:
        raise ValueError(f"Unexpected gte={gte} for task {tid}")

    entries.append(_make_end_turn_entry())
    return entries


# ---------------------------------------------------------------------------
# Headless TurnResult construction (no live [REDACTED].exe required)
# ---------------------------------------------------------------------------

def _synthesize_turn_result(
    session_jsonl_path: pathlib.Path,
    turn_start_s: float,
) -> TurnResult:
    """Build a TurnResult by parsing the synthesized JSONL file.

    This is the headless path from the grounding contract: feed the synthesized
    JSONL through _parse_jsonl_entries + _extract_turn_signal, then construct
    TurnResult. No HTTP client or [REDACTED].exe needed.
    """
    entries, _ = _parse_jsonl_entries(session_jsonl_path, after_byte=0)
    stop_reason, api_error, input_tokens, output_tokens, tool_call_seen = (
        _extract_turn_signal(entries)
    )
    return TurnResult(
        turn_id=0,
        tui_lines=[],
        stop_reason=stop_reason,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        api_error=api_error,
        elapsed_s=0.0,
        timed_out=False,
        tool_call_seen_this_turn=tool_call_seen,
        turn_start_s=turn_start_s,
    )


# ---------------------------------------------------------------------------
# Full assertion list builder
# ---------------------------------------------------------------------------

def _build_harness_builtin_assertions(output_file: str) -> list[dict]:
    """Build ONLY the built-in harness gate assertions (using harness key names).

    These are the 6 action-coupling + standard gates that harness_run_assertions
    knows how to evaluate. They use harness key conventions:
      file_contains -> needle key
      file_min_lines -> n key
      jsonl_stop_reason_eq -> expected key

    The task's own verifier_assertions are evaluated separately via
    ember_avir_tasks.run_assertions (which uses 'text', 'min_lines', 'value' keys).
    """
    return [
        {"type": "jsonl_tool_call_this_turn"},
        {"type": "file_created_this_turn", "path": output_file},
        {"type": "file_exists", "path": output_file},
        {"type": "jsonl_no_api_error"},
        {"type": "jsonl_stop_reason_eq", "expected": "end_turn"},
    ]


# ---------------------------------------------------------------------------
# Pretrain text rendering
# ---------------------------------------------------------------------------

def _render_pretrain_text(task: dict, entries: list[dict]) -> str:
    """Render the pretrain sample as goal_prompt + verified assistant turns.

    Per grounding contract §2:
      text = goal_prompt + "\\n" + completion
    where completion = "\\n".join(json.dumps(entry) for entry in entries)
    and entries = all assistant-role JSONL records from the synthesized slice.
    """
    completion = "\n".join(json.dumps(e) for e in entries)
    return task["goal_prompt"] + "\n" + completion


# ---------------------------------------------------------------------------
# Core pipeline
# ---------------------------------------------------------------------------

def run_pipeline(
    output_dir: str | os.PathLike | None = None,
    verbose: bool = True,
) -> dict[str, Any]:
    """Run the full C-BASE [REDACTED]-task pretrain data pipeline (v2 — REDO).

    For each TRAIN task t001-t024:
      1. FIREWALL: raise on any heldout id.
      2. COMPUTE answer from sandbox input via real Python.
      3. SYNTHESIZE [REDACTED].exe-format session JSONL.
      4. VERIFY via FULL assertion stack (no session_jsonl_path=None skip).
      5. RENDER pretrain target text per grounding rendering rule.
      6. TOKENIZE with frozen tokenizer (vocab 32000, assert all ids<32000).
      7. PACK via write_packed_shard.

    Returns a result dict with counts and paths.
    """
    out_dir = pathlib.Path(output_dir) if output_dir else _DATA_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    tasks = load_split("train")

    # FIREWALL: check at entry for all task ids
    for task in tasks:
        _assert_not_heldout(task["id"])

    tokenizer = _load_production_tokenizer()

    all_token_ids: list[int] = []
    traces_emitted = 0
    traces_full_R1 = 0
    dropped: list[str] = []
    per_task_results: list[dict] = []

    for task in tasks:
        tid = task["id"]
        _assert_not_heldout(tid)  # per-iteration firewall check

        if verbose:
            print(f"[{tid}] processing...")

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = pathlib.Path(tmpdir)

            # Step 1: set up sandbox INPUT files (seed files only — NOT pre-seeding output)
            sandbox = setup_sandbox(task, tmpdir_path)

            # Step 2: compute answer from real input files
            try:
                answer = _compute_answer(task, sandbox)
            except Exception as exc:
                if verbose:
                    print(f"[DROP] {tid}: compute_answer raised {exc!r}")
                dropped.append(tid)
                per_task_results.append({"id": tid, "r": 0, "reason": f"compute_answer_error: {exc}"})
                continue

            # Step 3: synthesize [REDACTED].exe-format JSONL entries
            try:
                entries = _build_session_entries(task, answer)
            except Exception as exc:
                if verbose:
                    print(f"[DROP] {tid}: build_session_entries raised {exc!r}")
                dropped.append(tid)
                per_task_results.append({"id": tid, "r": 0, "reason": f"build_entries_error: {exc}"})
                continue

            # CRITICAL: record turn_start BEFORE writing JSONL and output file
            # (mtime gate requires file mtime >= turn_start_s)
            turn_start_s = time.time() - 0.001  # small negative slack

            # Write synthesized JSONL to a temp file
            session_jsonl_path = tmpdir_path / "session.jsonl"
            with session_jsonl_path.open("w", encoding="utf-8") as fh:
                for entry in entries:
                    fh.write(json.dumps(entry) + "\n")

            # Write the output file to the sandbox (simulates Write tool_use effect)
            output_file = list(answer.keys())[0]
            output_content = answer[output_file]
            target_path = sandbox / output_file
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(output_content, encoding="utf-8")

            # Step 4: construct TurnResult via headless path
            result = _synthesize_turn_result(session_jsonl_path, turn_start_s)

            # Step 4a: Run built-in harness gates via harness_run_assertions
            # (action-coupling gates: tool_call_this_turn, file_created_this_turn, etc.)
            builtin_assertions = _build_harness_builtin_assertions(output_file)
            harness_passed, harness_failures = harness_run_assertions(result, sandbox, builtin_assertions)

            if not harness_passed:
                if verbose:
                    print(f"[DROP] {tid}: harness gate failures: {harness_failures}")
                dropped.append(tid)
                per_task_results.append({"id": tid, "r": 0, "failures": harness_failures})
                continue

            # Step 4b: Run task corpus assertions via ember_avir_tasks.run_assertions
            # with session_jsonl_path NOT None — this fires the full task assertion stack
            # including jsonl_tool_call_count_gte, file_order_asc, file_min_lines, etc.
            import ember_avir_tasks as _eat
            task_result = _eat.run_assertions(task, sandbox, session_jsonl_path=str(session_jsonl_path))
            if not task_result["pass"]:
                failed_details = [d for d in task_result["details"] if d.get("status") == "FAIL"]
                if verbose:
                    print(f"[DROP] {tid}: task corpus assertions failed: {failed_details}")
                dropped.append(tid)
                per_task_results.append({"id": tid, "r": 0, "task_assertion_failures": failed_details})
                continue

            # Full R=1 confirmed
            traces_full_R1 += 1
            traces_emitted += 1

            # Step 5: render pretrain target text
            text = _render_pretrain_text(task, entries)

            # Step 6: tokenize
            token_ids = tokenizer.encode(text, add_special_tokens=False).ids
            bad_ids = [i for i in token_ids if i >= 32000]
            if bad_ids:
                raise ValueError(f"Token ids >= 32000 in {tid}: {bad_ids[:5]}")

            all_token_ids.extend(token_ids)

            per_task_results.append({
                "id": tid,
                "r": 1,
                "tokens": len(token_ids),
                "tool_call_count": sum(
                    1 for e in entries
                    if e.get("message", {}).get("stop_reason") == "tool_use"
                ),
            })

            if verbose:
                print(f"[PASS] {tid}: R=1, {len(token_ids)} tokens, entries={len(entries)}")

    if not all_token_ids:
        raise RuntimeError("No token IDs produced — no verified traces to pack")

    # Step 7: pack into shard
    shard_path = out_dir / "cbase_avir_tasks_v2-00000.bin"
    write_packed_shard(str(shard_path), all_token_ids)

    if verbose:
        print(f"\nPacked {len(all_token_ids)} tokens into {shard_path}")
        print(f"Traces emitted: {traces_emitted}")
        print(f"Traces full R=1: {traces_full_R1}")
        print(f"Dropped: {dropped}")

    # Step 8: round-trip verification — load ONLY the v2 shard (not the whole dir,
    # which may contain the rejected v1 shard cbase_avir_tasks-00000.bin)
    import numpy as _np_rt
    rt_arr = _np_rt.fromfile(str(shard_path), dtype="<u2")
    rt_first = list(rt_arr[:min(5, len(rt_arr))])
    rt_last = list(rt_arr[-min(5, len(rt_arr)):])
    expected_first = all_token_ids[:min(5, len(all_token_ids))]
    expected_last = all_token_ids[-min(5, len(all_token_ids)):]
    rt_token_count = int(len(rt_arr))
    rt_ok = (
        [int(x) for x in rt_first] == expected_first
        and [int(x) for x in rt_last] == expected_last
        and rt_token_count == len(all_token_ids)
    )

    if verbose:
        print(f"Round-trip: loaded {rt_token_count} tokens, ok={rt_ok}")
        print(f"  first ids: {[int(x) for x in rt_first]} (expected {expected_first})")
        print(f"  last ids:  {[int(x) for x in rt_last]} (expected {expected_last})")

    if not rt_ok:
        raise RuntimeError(
            f"Round-trip FAILED: loaded {rt_token_count} != packed {len(all_token_ids)}"
        )

    return {
        "shard_path": str(shard_path),
        "shard_tokens": len(all_token_ids),
        "traces_emitted": traces_emitted,
        "traces_full_R1": traces_full_R1,
        "dropped": dropped,
        "roundtrip_ok": rt_ok,
        "per_task": per_task_results,
        "first_ids": [int(x) for x in rt_first],
        "last_ids": [int(x) for x in rt_last],
    }


# ---------------------------------------------------------------------------
# Does-not-count self-check
# ---------------------------------------------------------------------------

def does_not_count_self_check() -> str:
    """Return a string confirming the four defects are closed.

    This function does NOT count as a separate test — it is a documentation
    aid. The TDD tests in test_ember_cbase_avir_data_v2.py are the evidence.
    """
    checks = [
        "NO_SANDBOX_PRESEED: sandbox is cleared via setup_sandbox (input only); "
        "output file written AFTER turn_start_s is recorded.",
        "NO_SESSION_JSONL_NONE: session_jsonl_path is always the synthesized JSONL "
        "path — never None. harness_run_assertions fires the full stack. "
        "ember_avir_tasks.run_assertions called with session_jsonl_path=str(...) not None.",
        "CANONICAL_FORMAT: entries are built via _make_read_entry/_make_write_entry/"
        "_make_end_turn_entry using the [REDACTED].exe wire format (JSONL assistant entries "
        "with stop_reason/content/tool_use blocks). No <write_file> pseudo-tags.",
        "ANSWERS_COMPUTED_FROM_INPUT: _compute_answer reads real sandbox input files "
        "and executes the transformation. No _CORRECT_ANSWERS hardcoded dict.",
        "FIREWALL_ENFORCED: _assert_not_heldout raises on h0xx pattern at entry and "
        "per-iteration. Heldout tasks never enter the corpus.",
    ]
    return "\n".join(checks)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print(does_not_count_self_check())
    print()
    result = run_pipeline(verbose=True)
    print("\n=== PIPELINE RESULT ===")
    print(f"shard_path:      {result['shard_path']}")
    print(f"shard_tokens:    {result['shard_tokens']}")
    print(f"traces_emitted:  {result['traces_emitted']}")
    print(f"traces_full_R1:  {result['traces_full_R1']}")
    print(f"dropped:         {result['dropped']}")
    print(f"roundtrip_ok:    {result['roundtrip_ok']}")
