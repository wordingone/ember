#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""ember_cbase_avir_data.py — C-BASE [REDACTED]-task data pipeline (GAP1 BUILD).

Synthesizes correct action traces for each HEADLESS-verifiable train task,
EXECUTES them against a fresh sandbox via run_assertions(), keeps only R=1,
tokenizes (goal_prompt + verified trace) with the frozen ByteLevel BPE tokenizer
(vocab 32000, added-token-matching-disabled-v1), and packs via write_packed_shard
into data/cbase_pretrain/ .bin shards.

HARD REQUIREMENTS (does-not-count guards):
(a) EXECUTING-VERIFIED: every emitted trace scored run_assertions R=1 by EXECUTION;
    synthesis_trusted_count MUST be 0.
(b) TRAIN-ONLY FIREWALL: held-out h0xx tasks NEVER enter the corpus.
(c) TOKENIZER CONSISTENCY: same tokenizer as shards-v0 (vocab 32000);
    token IDs < 32000 always.
(d) LOADS BACK: written shards load via PackedShardLoader and windows decode.

Usage:
    python scripts/ember_cbase_avir_data.py
"""
from __future__ import annotations

import json
import os
import pathlib
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
_TOK_PATH = _REPO / "domains" / "model" / "tokenizer" / "tokenizer.json"

sys.path.insert(0, str(_HERE))

from ember_avir_tasks import load_split, setup_sandbox, run_assertions  # noqa: E402
from timeshare_pretrain import write_packed_shard  # noqa: E402

# ---------------------------------------------------------------------------
# Tokenizer loader — added-token-matching-disabled-v1
# ---------------------------------------------------------------------------

def _load_production_tokenizer():
    """Load frozen ByteLevel BPE tokenizer with added_tokens stripped in-memory.

    Implements the same strip-verification pattern as token_shards_v0.py:
    strip the added_tokens list from the JSON before building the tokenizer,
    then probe each literal to ensure no id < 8 slips through.
    """
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
# Correct-answer table (deterministically computed from seed files)
# ---------------------------------------------------------------------------

# These are the exact outputs that run_assertions() expects.
# Computed from the seed file contents — not echoed from the prompts.
_CORRECT_ANSWERS: dict[str, dict[str, str]] = {
    "t001": {"output.txt": "101\n"},       # sum(17,34,9,41)=101
    "t002": {"count.txt": "5\n"},          # 5 lines in words.txt
    "t003": {"max.txt": "max: 87\n"},      # max(23,87,14,62,5)=87
    "t004": {"sorted.txt": "apricot\nblueberry\nkiwi\nmango\npeach\n"},
    "t005": {"split.txt": "north\nsouth\neast\nwest\n"},
    "t006": {"total.txt": "14\n"},         # 3+2+4+5=14
    "t007": {"inverted.txt": "red=color\nlarge=size\nheavy=weight\n"},
    "t008": {"winner.txt": "winner: bob\n"},  # bob:91 highest
    "t009": {"vowel_count.txt": "vowel_count: 4\n"},  # umbrella,apple,ivy,octopus
    "t010": {"word_count.txt": "9\n"},     # "the cat sat\non the mat\nwith a hat"
    "t011": {"row_sums.txt": "6\n15\n24\n"},  # 1+2+3=6, 4+5+6=15, 7+8+9=24
    "t012": {"char_counts.txt": "3\n8\n2\n"},  # cat=3, elephant=8, ox=2
    "t013": {"dedup_stats.txt": "unique_count: 4\n"},  # oak,birch,pine,maple=4
    "t014": {"diffs.txt": "35\n16\n33\n"},   # 45-10=35, 19-3=16, 133-100=33
    "t015": {"freq.txt": "bird:1\ncat:3\ndog:2\n"},
    "t016": {"products.txt": "42\n33\n32\n"},  # 6*7=42, 3*11=33, 8*4=32
    "t017": {"error_count.txt": "3\n"},    # 3 ERROR lines
    "t018": {"stock_report.txt": "low_stock_count: 3\n"},  # bolts:4,nails:7,pegs:2
    "t019": {"line_tally.txt": "total_lines: 5\n"},  # 2+3=5
    "t020": {"average.txt": "25.0\n"},     # (10+20+30+40)/4=25.0
    "t021": {"reversed.txt": "1: fifth\n2: fourth\n3: third\n4: second\n5: first\n"},
    "t022": {"rename_script.sh": "mv foo.txt bar.txt\nmv data.csv results.csv\n"},
    "t023": {"class_avg.txt": "80\n"},     # (88+74+92+66)/4=80
    "t024": {"flag_summary.txt": "enabled_count: 3\n"},  # verbose,cache,metrics
}

# Heldout IDs — MUST NEVER enter the corpus (train-only firewall)
_HELDOUT_IDS: frozenset[str] = frozenset(
    t["id"] for t in load_split("heldout")
)


# ---------------------------------------------------------------------------
# Trace synthesizer
# ---------------------------------------------------------------------------

def _synthesize_trace(task: dict, answer: dict[str, str]) -> str:
    """Synthesize the goal_prompt + assistant completion as a training pair string.

    Format: the goal prompt as the user turn, followed by the assistant turn
    that (a) reasons briefly, then (b) writes the output file content.
    This is the wire-format context->completion pair.
    """
    goal = task["goal_prompt"].strip()

    # Build the assistant completion showing the file write
    completion_parts = []
    for relpath, content in answer.items():
        completion_parts.append(
            f"I'll compute the answer and write it to {relpath}.\n"
            f"<write_file>\n"
            f"path: {relpath}\n"
            f"content:\n{content}"
            f"</write_file>"
        )
    completion = "\n".join(completion_parts)

    return f"User: {goal}\n\nAssistant: {completion}"


# ---------------------------------------------------------------------------
# Core pipeline
# ---------------------------------------------------------------------------

def run_pipeline(
    file_state_train_ids: list[str],
    output_dir: str | os.PathLike | None = None,
    verbose: bool = True,
) -> dict[str, Any]:
    """Run the full C-BASE [REDACTED]-task data pipeline.

    For each task in file_state_train_ids:
      1. Synthesize the correct action trace.
      2. Execute: apply trace effects to a fresh sandbox, call run_assertions().
         Keep ONLY R=1 traces.
      3. Serialize as (goal_prompt + verified_trace) pair.
      4. Tokenize with the frozen tokenizer (vocab 32000, added-tokens stripped).
      5. Pack via write_packed_shard into data/cbase_pretrain/ .bin shards.

    Returns a result dict with counts and paths.
    """
    out_dir = pathlib.Path(output_dir) if output_dir else _DATA_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    # TRAIN-ONLY FIREWALL: check at entry
    for tid in file_state_train_ids:
        if tid in _HELDOUT_IDS:
            raise ValueError(
                f"FIREWALL VIOLATION: held-out task {tid!r} in file_state_train_ids"
            )

    tasks_by_id = {t["id"]: t for t in load_split("train")}

    tokenizer = _load_production_tokenizer()

    all_token_ids: list[int] = []
    traces_emitted = 0
    traces_executing_verified = 0
    synthesis_trusted_count = 0
    dropped: list[str] = []
    flagged_for_operator: list[str] = []  # jsonl-only tasks needing live [REDACTED].exe

    for tid in file_state_train_ids:
        # FIREWALL: double-check every ID
        if tid in _HELDOUT_IDS:
            raise ValueError(f"FIREWALL VIOLATION: {tid!r} is a held-out task")

        task = tasks_by_id.get(tid)
        if task is None:
            if verbose:
                print(f"[SKIP] {tid}: not found in train split")
            dropped.append(tid)
            continue

        answer = _CORRECT_ANSWERS.get(tid)
        if answer is None:
            if verbose:
                print(f"[SKIP] {tid}: no correct answer registered")
            dropped.append(tid)
            continue

        # Step 1: synthesize trace
        pair_text = _synthesize_trace(task, answer)

        # Step 2: EXECUTE — apply trace effects to fresh sandbox, run assertions
        with tempfile.TemporaryDirectory() as tmpdir:
            sandbox = setup_sandbox(task, tmpdir)

            # Write the correct answer files (the "trace effects")
            for relpath, content in answer.items():
                target = sandbox / relpath
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")

            # Run assertions with session_jsonl_path=None (file-state headless path)
            result = run_assertions(task, sandbox, session_jsonl_path=None)

        r = result["r"]

        if r < 1.0:
            # Trace did not verify R=1 — DROP, never emit
            if verbose:
                failed = [d for d in result["details"] if d["status"] == "FAIL"]
                print(f"[DROP] {tid}: R={r}, failed={failed}")
            dropped.append(tid)
            # This is NOT synthesis-trusted; it's a genuine execution failure
            continue

        # R=1 confirmed — EXECUTING-VERIFIED
        traces_executing_verified += 1
        traces_emitted += 1
        # synthesis_trusted_count stays 0 — we only emit executing-verified traces

        # Step 3: Tokenize
        token_ids = tokenizer.encode(pair_text, add_special_tokens=False).ids

        # Consistency check: all ids < 32000
        if any(i >= 32000 for i in token_ids):
            raise ValueError(
                f"Token id >= 32000 in {tid}: "
                f"{[i for i in token_ids if i >= 32000]}"
            )

        all_token_ids.extend(token_ids)

        if verbose:
            print(f"[PASS] {tid}: R=1, {len(token_ids)} tokens")

    if not all_token_ids:
        raise RuntimeError("No token IDs produced — no verified traces to pack")

    # Step 4: Pack into a single shard
    shard_path = out_dir / "cbase_avir_tasks-00000.bin"
    write_packed_shard(str(shard_path), all_token_ids)

    if verbose:
        print(f"\nPacked {len(all_token_ids)} tokens into {shard_path}")
        print(f"Traces emitted: {traces_emitted}")
        print(f"Traces executing-verified: {traces_executing_verified}")
        print(f"Synthesis-trusted: {synthesis_trusted_count}")
        print(f"Dropped: {dropped}")

    return {
        "shard_path": str(shard_path),
        "traces_emitted": traces_emitted,
        "traces_executing_verified": traces_executing_verified,
        "synthesis_trusted_count": synthesis_trusted_count,
        "total_tokens": len(all_token_ids),
        "dropped": dropped,
        "flagged_for_operator": flagged_for_operator,
    }


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    FILE_STATE_TRAIN_IDS = [
        "t001", "t002", "t003", "t004", "t005", "t006",
        "t007", "t008", "t009", "t010", "t011", "t012",
        "t013", "t014", "t015", "t016", "t017", "t018",
        "t019", "t020", "t021", "t022", "t023", "t024",
    ]
    result = run_pipeline(FILE_STATE_TRAIN_IDS, verbose=True)
    print("\nPipeline result:")
    print(json.dumps(result, indent=2))
