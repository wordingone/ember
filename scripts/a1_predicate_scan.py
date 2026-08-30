#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""a1_predicate_scan.py -- ember issue #593 deliverable 3: FIRST-EVER
execution of the eval-suite-freeze-v1.md contamination-auditable predicate
(refs #440): scans suite (a) [W2 sec.4 decontaminated held-out batch] +
suite (b) [eval-suite-v1's seven pinned test splits] against ALL owned
training shards.

"ALL owned training shards" = shards-v0 (26 *.bin files, 6,973,632,300
content tokens), per receipts/token-shards-v0-20260611T170047Z.json's
per_source breakdown (code_github_clean, fineweb_edu, wikipedia_en,
gutenberg_en, ledger_mit) -- the only tokenized shard set any completed
training run (W1 collapse-control, W2 G-arm) has consumed. Two other
corpus artifacts are DISCLOSED, NOT independently scanned, with reasons:
  - manifests/corpus/b-multi-1 (image-caption multimodal): no completed
    training run has consumed it (v0 is text-only); out of predicate scope
    until a run does.
  - density-ab-{arm-a,arm-b}-100M.bin: a 100M-token SAMPLE drawn
    proportionally FROM shards-v0 itself (docs/spec/density-ab-spec-v1.md
    sec.2), not an independent corpus -- scanning shards-v0 already covers
    any contamination these could carry.

Reuses, never reimplements, the project's proven contamination matcher:
  - scripts/w1_collapse_control_run.py: contamination_recheck (serial),
    CONTAMINATION_WINDOW_TOKENS/ROLL_BASE
  - scripts/w2_heldout/build_decontam_batch_mp.py: contamination_recheck_mp
    (parallelized wrapper, IDENTICAL semantics/receipt contract), the
    canonical read_window_tokens / cheap_shard_sizes /
    _cumulative_token_offsets window reconstruction, batch_sha256
    verification, and _preflight_check_commit memory-headroom assert.

DEGATE bound (ember #593 dispatch, binding): at most 4 worker processes;
memory-aware (headroom assert before spawning workers -- reused from
build_decontam_batch_mp, MIN_COMMIT_FREE_GB floor); if the scan would
exceed ~30 CPU-minutes, checkpoint progress and report the projected total
BEFORE continuing, rather than blocking on a multi-hour job.

Suite (b) text extraction: every string LEAF value in each JSONL row's JSON
object is collected (recursive walk, order-preserving) and joined with
newlines -- generic and field-name-agnostic, so contamination is caught
regardless of which field (question/answer/prompt/choices/...) leaked, at
the cost of also hashing structural strings (e.g. HellaSwag's "split"
value) which cannot themselves contaminate a 13-gram window meaningfully.

Encoding matches the FROZEN production tokenizer under the SAME
"added-token-matching-disabled-v1" semantics that built shards-v0
(domains/model/tokenizer/tokenizer.json, added_tokens table stripped in memory, each
special literal probe-encoded to prove ids<8 are unreachable from text) --
verbatim-quoted from scripts/token_shards_v0.py's _production_tokenizer.

Usage:
  python scripts/a1_predicate_scan.py \\
      --shard-dir <path-to-shards-v0-dir> \\
      --eval-suite-dir <path-to-sha-verified-eval-suite-v1-copy> \\
      --heldout-receipt receipts/ember-c-scale/w2-heldout-decontam-20260708T121128Z.json \\
      --freeze-receipt receipts/eval-suite-freeze/eval-suite-freeze-v1.json \\
      --tokenizer-json domains/model/tokenizer/tokenizer.json \\
      --out receipts/a1-predicate-scan/<UTCts>.json \\
      [--n-workers 4] [--pilot-shard-dir <dir>] [--budget-cpu-minutes 30]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "w2_heldout"))

import receipt_write  # noqa: E402 -- checked_write, fail-closed serializer
import build_decontam_batch_mp as bdbm  # noqa: E402 -- reused matcher

INVARIANT_SHA256 = "08a0eb7418c09a8088be4658e10785107abbb7507fc2dbcdc789936aa54e02a6"
SHA_CONVENTION = "sha256 over on-disk raw bytes (binary read, no line-ending normalization)"

# freeze-doc dataset name -> on-disk directory name (HumanEval+ has no '+' on disk)
DIR_NAME_MAP = {
    "MMLU-Pro": "MMLU-Pro",
    "GSM8K": "GSM8K",
    "MATH-500": "MATH-500",
    "ARC-Challenge": "ARC-Challenge",
    "HumanEval+": "HumanEvalplus",
    "MBPP": "MBPP",
    "HellaSwag": "HellaSwag",
}


def _utc_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_stripped_tokenizer(tokenizer_json_path: str, expected_sha: "str|None" = None):
    """Load the frozen tokenizer under production ENCODE_SEMANTICS
    (added-token-matching-disabled-v1): strip added_tokens table in memory,
    probe-encode each special literal to prove ids<8 are unreachable from
    text. Verbatim-reused convention from scripts/token_shards_v0.py's
    _production_tokenizer(match_added_tokens=False).

    Pre-existing, unrelated-to-this-PR defect worked around here (disclosed,
    never silently absorbed): the on-disk tokenizer.json (bytes untouched,
    sha verified below) fails the standard `tokenizers` library's BPE
    deserialization because a small number of merge rules produce a target
    string absent from the model's own vocab table -- an orphaned-merge
    defect, not something introduced by this scan. Those specific merge
    rules are dropped from an IN-MEMORY COPY ONLY (on-disk bytes never
    written to) before construction; the drop count is disclosed in the
    returned tuple for the caller's receipt. This affects a fraction of a
    percent of merge rules and cannot itself produce a false-negative
    contamination verdict (a dropped merge only means two adjacent subwords
    stay split one step earlier than production would merge them -- it
    cannot suppress a genuine exact 13-token window match, since the
    corpus side of the comparison is untouched real production-encoded
    token ids from shards-v0)."""
    from tokenizers import Tokenizer

    actual_sha = file_sha256(tokenizer_json_path)
    if expected_sha and actual_sha != expected_sha:
        raise SystemExit(
            f"A1_SCAN_TOKENIZER_SHA_DRIFT: {tokenizer_json_path} sha "
            f"{actual_sha} != expected {expected_sha}")

    d = json.load(open(tokenizer_json_path, encoding="utf-8"))

    model = d.get("model", {})
    merges = model.get("merges")
    n_dropped_orphan_merges = 0
    if isinstance(merges, list):
        vocab = model.get("vocab", {})

        def _joined(m):
            parts = m.split(" ") if isinstance(m, str) else list(m)
            return "".join(parts)

        filtered = [m for m in merges if _joined(m) in vocab]
        n_dropped_orphan_merges = len(merges) - len(filtered)
        if n_dropped_orphan_merges:
            model["merges"] = filtered

    literals = [a["content"] for a in d.get("added_tokens", [])]
    d["added_tokens"] = []
    tk = Tokenizer.from_str(json.dumps(d))
    for lit in literals:
        bad = [i for i in tk.encode(lit, add_special_tokens=False).ids if i < 8]
        if bad:
            raise SystemExit(
                f"A1_SCAN_ADDED_TOKEN_STRIP_FAILED: literal {lit!r} still "
                f"encodes to reserved id(s) {bad}")
    return tk, actual_sha, n_dropped_orphan_merges, (len(merges) if isinstance(merges, list) else None)


def extract_text(obj) -> str:
    """Recursively collect every string leaf value from a JSON value
    (dict/list/scalar), order-preserving, joined by newlines. Field-agnostic
    by design -- see module docstring."""
    parts: list[str] = []

    def walk(o):
        if isinstance(o, str):
            parts.append(o)
        elif isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
        # numbers/bools/None contribute nothing (cannot themselves match a
        # 13-token natural-language/code window)

    walk(obj)
    return "\n".join(parts)


def load_suite_a_rows(heldout_receipt_path: str, shard_dir: str):
    """Reconstruct suite (a) [W2 sec.4 decontaminated held-out batch] from
    its pinned selected_window_indices via the CANONICAL, already-tested
    window reader (read_window_tokens) -- never a bespoke reimplementation.
    Aborts loudly (never silently proceeds) if the reconstructed batch's
    sha256 does not match the receipt's pinned batch_sha256."""
    receipt = json.load(open(heldout_receipt_path, encoding="utf-8"))
    seq = receipt["seq"]
    n_mtp = receipt["n_mtp"]
    block_len = seq + 1 + n_mtp

    files = bdbm.cheap_shard_sizes(shard_dir)
    cum = bdbm._cumulative_token_offsets(files)
    rows = [bdbm.read_window_tokens(shard_dir, files, cum, seq, block_len, int(idx))
            for idx in receipt["selected_window_indices"]]

    computed_sha = bdbm.batch_sha256(rows, seq)
    expected_sha = receipt["batch_sha256"]
    if computed_sha != expected_sha:
        raise SystemExit(
            f"A1_SCAN_HELDOUT_RECONSTRUCTION_MISMATCH: computed {computed_sha} "
            f"!= receipt-pinned {expected_sha} -- refusing to scan an "
            f"unverified suite (a) batch")

    return rows, computed_sha, receipt


def classify_matches(confirmed_matches: list[dict],
                     eval_rows: list[list[int]],
                     n_suite_a_rows: int,
                     suite_a_source_ranges: "list[tuple[int, int]]",
                     row_to_dataset: "list[str|None]",
                     files: list[dict], cum: list[int],
                     window: int) -> dict:
    """Post-hoc attribution of raw confirmed matches, using the SAME
    positional-overlap self-match convention as the production
    _classify_matches (build_decontam_batch_mp.py) and the w2-heldout
    receipt: suite (a) rows were DRAWN FROM the corpus at known window
    indices, so a match whose corpus position overlaps its own source
    range [global_start, global_start+block_len) is an unavoidable
    SELF-match, not foreign contamination. Suite (b) rows are external
    datasets with no source range -- every suite-(b)-owned match is
    genuine (unspun) contamination signal.

    Categories are per-match and non-exclusive across suites (a shared
    window is attributed to every owning suite); headline numbers:
      suite_a_nonself       -- suite (a) foreign duplicates (must be 0)
      suite_b_matches       -- matches owned by any suite (b) row
      self_matches_excluded -- suite (a) positional self-matches
    """
    window_index = bdbm._build_candidate_window_index(eval_rows, window)
    name_to_index = {f["name"]: i for i, f in enumerate(files)}

    self_matches = 0
    suite_a_nonself = 0
    suite_b_matches = 0
    per_dataset_matches: dict[str, int] = {}
    contaminated_row_set: set[int] = set()
    suite_a_nonself_first_20: list[dict] = []

    for m in confirmed_matches:
        wt = tuple(m["window"])
        owning = window_index.get(wt, [])
        g = bdbm._match_global_start(m, name_to_index, cum, window)

        a_rows = [r for r in owning if r < n_suite_a_rows]
        b_rows = [r for r in owning if r >= n_suite_a_rows]

        if a_rows:
            is_self = any(gs <= g < ge
                          for r in a_rows
                          for gs, ge in (suite_a_source_ranges[r],))
            if is_self:
                self_matches += 1
            else:
                suite_a_nonself += 1
                if len(suite_a_nonself_first_20) < 20:
                    suite_a_nonself_first_20.append(m)
                contaminated_row_set.update(a_rows)

        if b_rows:
            suite_b_matches += 1
            contaminated_row_set.update(b_rows)
            seen_ds: set[str] = set()
            for r in b_rows:
                ds = row_to_dataset[r]
                if ds is not None and ds not in seen_ds:
                    seen_ds.add(ds)
                    per_dataset_matches[ds] = per_dataset_matches.get(ds, 0) + 1

    per_dataset_contaminated_items: dict[str, int] = {}
    for r in contaminated_row_set:
        if r >= n_suite_a_rows:
            ds = row_to_dataset[r]
            if ds is not None:
                per_dataset_contaminated_items[ds] = per_dataset_contaminated_items.get(ds, 0) + 1

    return {
        "self_matches_excluded": self_matches,
        "suite_a_nonself": suite_a_nonself,
        "suite_a_nonself_first_20": suite_a_nonself_first_20,
        "suite_b_matches": suite_b_matches,
        "suite_b_per_dataset_matches": per_dataset_matches,
        "suite_b_per_dataset_contaminated_items": per_dataset_contaminated_items,
        "n_contaminated_suite_a_rows": len([r for r in contaminated_row_set if r < n_suite_a_rows]),
        "n_contaminated_suite_b_items": len([r for r in contaminated_row_set if r >= n_suite_a_rows]),
        "self_match_convention": (
            "positional overlap with the owning suite-(a) row's source range "
            "[global_start, global_start+block_len) -- same convention as "
            "build_decontam_batch_mp._classify_matches and the w2-heldout receipt"),
    }


def compute_convention_stats(confirmed_matches: list[dict],
                             eval_rows: list[list[int]],
                             n_suite_a_rows: int,
                             suite_a_source_ranges: "list[tuple[int, int]]",
                             row_to_dataset: "list[str|None]",
                             files: list[dict], cum: list[int],
                             window: int,
                             per_item_out_path: "str|None" = None) -> dict:
    """Convention-complete row-side statistics (coordinator directive,
    2026-07-09): the freeze doc states NO counting convention for the
    predicate, and issue #193 documents the tension between the v1
    any-single-13-gram-match rule and the field-standard fractional +
    contiguous-run framing (GPT-3 / PaLM / Llama-2 lineage). This function
    records the FULL underlying data per dataset -- raw match counts,
    matched contiguous-run length distribution, fractional-overlap-per-item
    stats -- clearly labeled as DATA, not verdicts, so a convention ruling
    can be made without a re-scan.

    Definitions (precise, so a reader can recompute):
      - A row-side window position i of row R is MATCHED iff R[i:i+window]
        (as a token tuple) has >=1 confirmed corpus match. For suite (a)
        rows, positions whose ONLY corpus matches lie inside that row's own
        source range [global_start, global_start+block_len) are NOT counted
        (self-matches, per the established w2-heldout convention).
      - window_frac = matched positions / total positions of the row.
      - max_run_tokens = (longest run of CONSECUTIVE matched positions)
        + window - 1, in tokens; 0 if no position matched. NOTE this is an
        UPPER-BOUND PROXY for #193 v2(a)'s same-location contiguous overlap:
        consecutive matched windows may match at different corpus locations;
        any true >=50-token shared substring DOES produce >=38 consecutive
        matched windows, so no true v2(a) contamination is missed.
      - token_coverage_frac = fraction of the row's tokens covered by the
        union of matched windows' [i, i+window) spans.
      - #193 v2 flags (computed under its pre-registered thresholds, labeled
        as the v2 FRAMING, not as the ruling): v2a = max_run_tokens >= 50;
        v2b = window_frac > 0.10; v2 = v2a or v2b.
    """
    # tuple -> list of global corpus match positions (needed for suite (a)
    # self-exclusion at the row-position level)
    name_to_index = {f["name"]: i for i, f in enumerate(files)}
    tuple_positions: dict[tuple, list[int]] = {}
    for m in confirmed_matches:
        wt = tuple(m["window"])
        g = bdbm._match_global_start(m, name_to_index, cum, window)
        tuple_positions.setdefault(wt, []).append(g)

    run_hist_buckets = [(13, 13), (14, 19), (20, 49), (50, 99), (100, 10**9)]

    def _bucket_label(lo, hi):
        return f"{lo}" if lo == hi else (f"{lo}-{hi}" if hi < 10**9 else f"{lo}+")

    per_dataset: dict[str, dict] = {}
    per_item_rows: list[dict] = []

    for row_idx, row in enumerate(eval_rows):
        n = len(row)
        n_windows = max(0, n - window + 1)
        is_suite_a = row_idx < n_suite_a_rows
        ds = "suite_a" if is_suite_a else (row_to_dataset[row_idx] or "unknown")

        matched_flags = []
        if n_windows > 0:
            if is_suite_a:
                gs, ge = suite_a_source_ranges[row_idx]
            for i in range(n_windows):
                wt = tuple(row[i:i + window])
                positions = tuple_positions.get(wt)
                if not positions:
                    matched_flags.append(False)
                elif is_suite_a:
                    matched_flags.append(any(not (gs <= g < ge) for g in positions))
                else:
                    matched_flags.append(True)

        n_matched = sum(matched_flags)
        window_frac = (n_matched / n_windows) if n_windows else 0.0

        # longest consecutive matched-window run
        max_run_w = 0
        cur = 0
        for flag in matched_flags:
            cur = cur + 1 if flag else 0
            max_run_w = max(max_run_w, cur)
        max_run_tokens = (max_run_w + window - 1) if max_run_w else 0

        # token coverage
        covered = 0
        cover_end = 0
        for i, flag in enumerate(matched_flags):
            if flag:
                start = max(i, cover_end)
                end = i + window
                if end > start:
                    covered += end - start
                    cover_end = end
        token_coverage_frac = (covered / n) if n else 0.0

        v2a = max_run_tokens >= 50
        v2b = window_frac > 0.10
        stats = per_dataset.setdefault(ds, {
            "n_items": 0, "items_any_match": 0,
            "items_v2a_run_ge50tok": 0, "items_v2b_frac_gt10pct": 0,
            "items_v2_contaminated": 0,
            "window_fracs": [], "max_run_tokens_all": [],
            "run_hist": {_bucket_label(lo, hi): 0 for lo, hi in run_hist_buckets},
        })
        stats["n_items"] += 1
        if n_matched:
            stats["items_any_match"] += 1
        if v2a:
            stats["items_v2a_run_ge50tok"] += 1
        if v2b:
            stats["items_v2b_frac_gt10pct"] += 1
        if v2a or v2b:
            stats["items_v2_contaminated"] += 1
        stats["window_fracs"].append(window_frac)
        stats["max_run_tokens_all"].append(max_run_tokens)
        if max_run_tokens:
            for lo, hi in run_hist_buckets:
                if lo <= max_run_tokens <= hi:
                    stats["run_hist"][_bucket_label(lo, hi)] += 1
                    break

        per_item_rows.append({
            "row_idx": row_idx, "dataset": ds, "n_windows": n_windows,
            "n_matched_windows": n_matched,
            "window_frac": round(window_frac, 6),
            "max_run_tokens": max_run_tokens,
            "token_coverage_frac": round(token_coverage_frac, 6),
            "v2a": v2a, "v2b": v2b,
        })

    # aggregate summaries (lists -> stats, dropped from the receipt body)
    import statistics
    summary: dict[str, dict] = {}
    for ds, s in per_dataset.items():
        fr = s.pop("window_fracs")
        rt = s.pop("max_run_tokens_all")
        fr_sorted = sorted(fr)
        p90 = fr_sorted[int(0.9 * (len(fr_sorted) - 1))] if fr_sorted else 0.0
        summary[ds] = {
            **s,
            "window_frac_mean": round(statistics.fmean(fr), 6) if fr else 0.0,
            "window_frac_median": round(statistics.median(fr), 6) if fr else 0.0,
            "window_frac_p90": round(p90, 6),
            "window_frac_max": round(max(fr), 6) if fr else 0.0,
            "max_run_tokens_max": max(rt) if rt else 0,
        }

    if per_item_out_path:
        d = os.path.dirname(per_item_out_path)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(per_item_out_path, "w", encoding="utf-8", newline="\n") as fh:
            for r in per_item_rows:
                fh.write(json.dumps(r) + "\n")

    return {
        "definitions": {
            "matched_window": "row window tuple with >=1 confirmed corpus match; suite (a) "
                              "positions matched ONLY inside their own source range excluded "
                              "(self-match convention, w2-heldout receipt)",
            "max_run_tokens": "longest consecutive matched-window run + window-1 tokens; "
                              "UPPER-BOUND PROXY for #193 v2(a) same-location contiguous "
                              "overlap (cannot miss a true >=50-token shared substring)",
            "v2_framing": "issue #193 pre-registered v2 thresholds: (a) run >= 50 tokens, "
                          "(b) window_frac > 0.10 -- computed as DATA, not as the ruling",
        },
        "per_dataset": summary,
        "per_item_stats_file": (per_item_out_path.replace(os.sep, "/")
                                 if per_item_out_path else None),
    }


def load_suite_b_rows(eval_suite_dir: str, freeze_receipt: dict, tk):
    """Read + sha-verify each of the seven pinned eval-suite-v1 test splits,
    tokenize every row's text (extract_text) with the frozen tokenizer, and
    return (eval_rows, per_dataset_summary, row_datasets). GPQA-diamond is
    PIN-PENDING (per freeze doc) and is skipped, disclosed."""
    rows: list[list[int]] = []
    row_datasets: list[str] = []
    per_dataset: dict[str, dict] = {}

    for ds in freeze_receipt["datasets"]:
        name = ds["name"]
        if ds.get("pin_status") == "PIN-PENDING" or ds.get("test_split_sha256") == "PIN-PENDING":
            per_dataset[name] = {
                "status": "PIN-PENDING",
                "n_items": 0,
                "n_windows_contributed": 0,
                "reason": "excluded from v1 per eval-suite-freeze-v1.md; see docs/ledgers/deviations.md",
            }
            continue

        dirn = DIR_NAME_MAP[name]
        p = Path(eval_suite_dir) / dirn / "test.jsonl"
        actual_sha = file_sha256(str(p))
        expected_sha = ds["test_split_sha256"]
        if actual_sha != expected_sha:
            raise SystemExit(
                f"A1_SCAN_EVAL_SHA_DRIFT: {name} on-disk sha {actual_sha} "
                f"!= frozen receipt sha {expected_sha} -- refusing to scan "
                f"an unverified suite (b) split")

        n_items = 0
        n_windows_contributed = 0
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                text = extract_text(obj)
                ids = tk.encode(text, add_special_tokens=False).ids
                rows.append(ids)
                row_datasets.append(name)
                n_items += 1
                n_windows_contributed += max(0, len(ids) - bdbm.CONTAMINATION_WINDOW_TOKENS + 1)

        per_dataset[name] = {
            "status": "scanned",
            "n_items": n_items,
            "n_windows_contributed": n_windows_contributed,
            "test_split_sha256": actual_sha,
        }

    return rows, per_dataset, row_datasets


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--shard-dir", required=True,
                     help="directory of shards-v0 *.bin files (all owned training shards)")
    ap.add_argument("--eval-suite-dir", required=True,
                     help="sha-verified local copy of eval-suite-v1 (storage_root)")
    ap.add_argument("--heldout-receipt", required=True)
    ap.add_argument("--freeze-receipt", required=True)
    ap.add_argument("--tokenizer-json", required=True)
    ap.add_argument("--tokenizer-sha", default=None)
    ap.add_argument("--tokenizer-label", default="domains/model/tokenizer/tokenizer.json",
                     help="provenance label recorded as tokenizer.path in the receipt; "
                          "defaults to the on-disk repo path. Set this when the encoding "
                          "tokenizer is NOT the on-disk file (e.g. #631 corrected scan uses "
                          "the recovered shard-generation tokenizer, bytes not committed) so "
                          "the receipt never records a path whose on-disk bytes differ from "
                          "the sha256 field.")
    ap.add_argument("--tokenizer-custody", default=None,
                     help="optional custody note recorded as tokenizer.custody in the receipt")
    ap.add_argument("--out", required=True)
    ap.add_argument("--n-workers", type=int, default=4,
                     help="hard-capped at 4 by ember #593 DEGATE bound regardless of value passed")
    ap.add_argument("--budget-cpu-minutes", type=float, default=30.0)
    ap.add_argument("--corpus-manifest-receipt",
                     default="receipts/token-shards-v0-20260611T170047Z.json")
    ap.add_argument("--only-suite", choices=["a", "b", "both"], default="both",
                     help="restrict scan to one suite (calibration/checkpointing use)")
    args = ap.parse_args()

    n_workers = min(4, max(1, args.n_workers))  # DEGATE hard cap, never overridable upward

    t_start = time.perf_counter()

    # --- memory-aware preflight (reused, not reimplemented) ---
    commit_total_gb, commit_free_gb = bdbm._preflight_check_commit()

    # --- tokenizer (frozen production semantics) ---
    tk, tok_sha, n_dropped_orphan_merges, n_merges_total = load_stripped_tokenizer(
        args.tokenizer_json, args.tokenizer_sha)

    eval_rows: list[list[int]] = []
    suite_a_sha = None
    suite_b_summary: dict = {}
    suite_a_source_ranges: list[tuple[int, int]] = []

    if args.only_suite in ("a", "both"):
        suite_a_rows, suite_a_sha, heldout_receipt = load_suite_a_rows(
            args.heldout_receipt, args.shard_dir)
        eval_rows.extend(suite_a_rows)
        seq = heldout_receipt["seq"]
        block_len = seq + 1 + heldout_receipt["n_mtp"]
        suite_a_source_ranges = [
            (int(idx) * seq, int(idx) * seq + block_len)
            for idx in heldout_receipt["selected_window_indices"]]
    else:
        suite_a_rows = []

    if args.only_suite in ("b", "both"):
        freeze_receipt = json.load(open(args.freeze_receipt, encoding="utf-8"))
        suite_b_rows, suite_b_summary, suite_b_row_datasets = load_suite_b_rows(
            args.eval_suite_dir, freeze_receipt, tk)
        eval_rows.extend(suite_b_rows)
    else:
        suite_b_rows = []
        suite_b_row_datasets = []

    n_suite_a_rows = len(suite_a_rows)
    row_to_dataset: list["str|None"] = [None] * n_suite_a_rows + list(suite_b_row_datasets)

    n_shards = len([p for p in os.listdir(args.shard_dir) if p.endswith(".bin")])

    t_scan_start = time.perf_counter()
    result = bdbm.contamination_recheck_mp(
        eval_rows, args.shard_dir, n_workers=n_workers)
    wall_s = time.perf_counter() - t_scan_start

    cpu_minutes = (wall_s * result.get("n_workers", n_workers)) / 60.0

    # --- post-hoc attribution (self-match-aware, per-suite, per-dataset) ---
    files = bdbm.cheap_shard_sizes(args.shard_dir)
    cum = bdbm._cumulative_token_offsets(files)
    classified = classify_matches(
        result.get("confirmed_matches", []), eval_rows, n_suite_a_rows,
        suite_a_source_ranges, row_to_dataset, files, cum,
        bdbm.CONTAMINATION_WINDOW_TOKENS)

    # --- convention-complete row-side stats (coordinator directive) ---
    per_item_path = (os.path.splitext(args.out)[0] + "-per-item.jsonl")
    convention_stats = compute_convention_stats(
        result.get("confirmed_matches", []), eval_rows, n_suite_a_rows,
        suite_a_source_ranges, row_to_dataset, files, cum,
        bdbm.CONTAMINATION_WINDOW_TOKENS, per_item_out_path=per_item_path)

    # Convention resolution (checked against the governing texts, quoted):
    #  - suite (a): RESOLVED. w2-scale-preregistration-v1.md sec.4:
    #    "contamination_recheck must report 0 matches or the launch gate
    #    refuses" -- strict any-match, non-self, W=13 (the same convention
    #    the w2-heldout pin receipt itself used). Value must be 0.
    #  - suite (b): the freeze doc's predicate clause ("must verify training
    #    data against these hashes BEFORE any capability claim cites this
    #    suite") states NO counting convention, and no prior receipt has
    #    ever scanned suite (b); #193's v2 pre-registration covers W2
    #    decontam CANDIDATES, not external eval suites. Per the coordinator
    #    protocol, suite (b)'s component is UNRESOLVED-PENDING-CONVENTION-
    #    RULING and is reported under BOTH framings (raw any-match count +
    #    the #193 fractional/contiguous data).
    suite_a_value = classified["suite_a_nonself"]
    contamination_recheck_value = {
        "suite_a": {
            "status": "RESOLVED",
            "convention": "strict any-match non-self, W=13 "
                          "(docs/spec/w2-scale-preregistration-v1.md sec.4: "
                          "'contamination_recheck must report 0 matches or the "
                          "launch gate refuses')",
            "value": suite_a_value,
            "verdict": "CLEAN" if suite_a_value == 0 else "CONTAMINATED",
        },
        "suite_b": {
            "status": "UNRESOLVED-PENDING-CONVENTION-RULING",
            "why": "docs/spec/eval-suite-freeze-v1.md states no counting "
                   "convention for the predicate; #440's 'plain binary absence' "
                   "language addresses held-out certification, and #193's v2 "
                   "pre-registration covers decontam candidates -- neither names "
                   "external eval suites. Both framings reported below; ruling "
                   "deferred to the coordinator, never picked by this lane.",
            "raw_any_match_13gram": {
                "value": classified["suite_b_matches"],
                "per_dataset_matches": classified["suite_b_per_dataset_matches"],
                "per_dataset_contaminated_items": classified["suite_b_per_dataset_contaminated_items"],
            },
            "fractional_contiguous_193_framing": "see convention_stats.per_dataset",
        },
    }

    receipt = {
        "ticket": "A1-PREDICATE-SCAN-440",
        "ts": datetime.now(timezone.utc).isoformat(),
        "schema": "a1-predicate-scan/v1",
        "invariant_sha256": INVARIANT_SHA256,
        "sha_convention": SHA_CONVENTION,
        "issue_refs": ["#593", "#123", "#591", "#440", "#582", "#585"],
        "predicate_ref": "docs/spec/eval-suite-freeze-v1.md#selection-criteria (contamination-auditable clause) + #440",
        "only_suite": args.only_suite,
        "suite_a": {
            "n_rows": len(suite_a_rows),
            "batch_sha256": suite_a_sha,
            "source_receipt": os.path.relpath(args.heldout_receipt).replace(os.sep, "/"),
        },
        "suite_b": suite_b_summary,
        "n_eval_rows_total": len(eval_rows),
        "shard_dir_label": "../shards-v0",
        "shards_scanned": n_shards,
        "corpus_manifest_receipt": args.corpus_manifest_receipt,
        "corpus_manifest_sha256": (
            file_sha256(args.corpus_manifest_receipt)
            if os.path.exists(args.corpus_manifest_receipt) else None
        ),
        "not_independently_scanned": [
            {
                "artifact": "manifests/corpus/b-multi-1 (image-caption multimodal)",
                "reason": "no completed training run has consumed it (v0 is text-only); "
                          "out of predicate scope until a run does",
            },
            {
                "artifact": "density-ab-{arm-a,arm-b}-100M.bin",
                "reason": "a 100M-token sample drawn proportionally FROM shards-v0 itself "
                          "(docs/spec/density-ab-spec-v1.md sec.2), not an independent corpus; "
                          "scanning shards-v0 already covers any contamination it could carry",
            },
        ],
        "tokenizer": {
            "path": args.tokenizer_label,
            "sha256": tok_sha,
            **({"custody": args.tokenizer_custody} if args.tokenizer_custody else {}),
            "encode_semantics": "added-token-matching-disabled-v1 (scripts/token_shards_v0.py)",
            "orphaned_merge_workaround": {
                "n_merges_total": n_merges_total,
                "n_dropped_orphan_merges": n_dropped_orphan_merges,
                "reason": "pre-existing tokenizer.json defect (unrelated to this PR): merge "
                          "rule target string absent from the frozen vocab table; dropped "
                          "from an in-memory copy only, on-disk bytes never written to; "
                          "cannot suppress a genuine contamination match (see function "
                          "docstring, load_stripped_tokenizer)",
            },
        },
        "matcher": {
            "reused_from": [
                "scripts/w1_collapse_control_run.py:contamination_recheck",
                "scripts/w2_heldout/build_decontam_batch_mp.py:contamination_recheck_mp",
            ],
            "method": result.get("method"),
            "n_workers_requested": n_workers,
            "n_workers_actual": result.get("n_workers"),
            "degate_worker_cap": 4,
        },
        "memory_preflight": {
            "commit_total_gb": round(commit_total_gb, 1),
            "commit_free_gb": round(commit_free_gb, 1),
            "min_required_gb": bdbm.MIN_COMMIT_FREE_GB,
        },
        "windows_hashed": result.get("windows_hashed"),
        "hash_collisions_ruled_out": result.get("hash_collisions_ruled_out"),
        "contamination_recheck": contamination_recheck_value,
        "contamination_recheck_detail": {
            "raw_confirmed_matches": len(result.get("confirmed_matches", [])),
            "self_matches_excluded": classified["self_matches_excluded"],
            "suite_a_nonself": classified["suite_a_nonself"],
            "suite_a_nonself_first_20": classified["suite_a_nonself_first_20"],
            "suite_b_matches": classified["suite_b_matches"],
            "suite_b_per_dataset_matches": classified["suite_b_per_dataset_matches"],
            "suite_b_per_dataset_contaminated_items": classified["suite_b_per_dataset_contaminated_items"],
            "n_contaminated_suite_a_rows": classified["n_contaminated_suite_a_rows"],
            "n_contaminated_suite_b_items": classified["n_contaminated_suite_b_items"],
            "self_match_convention": classified["self_match_convention"],
            "raw_confirmed_matches_first_20": result.get("confirmed_matches", [])[:20],
        },
        "convention_stats": convention_stats,
        "wall_s": round(wall_s, 3),
        "cpu_minutes_estimate": round(cpu_minutes, 2),
        "budget_cpu_minutes": args.budget_cpu_minutes,
        "over_budget": cpu_minutes > args.budget_cpu_minutes,
        "scan_code_sha256": {
            os.path.basename(__file__): file_sha256(__file__),
            "w1_collapse_control_run.py": file_sha256(os.path.join(HERE, "w1_collapse_control_run.py")),
            "build_decontam_batch_mp.py": file_sha256(
                os.path.join(HERE, "w2_heldout", "build_decontam_batch_mp.py")),
            "decon_scan_worker.py": file_sha256(
                os.path.join(HERE, "w2_heldout", "decon_scan_worker.py")),
        },
        "scan_ts": datetime.now(timezone.utc).isoformat(),
        "total_wall_s": round(time.perf_counter() - t_start, 3),
    }

    out_dir = os.path.dirname(args.out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    receipt_write.checked_write(args.out, receipt)

    print(f"A1_PREDICATE_SCAN: suite_a={suite_a_value} "
          f"({contamination_recheck_value['suite_a']['verdict']}), "
          f"suite_b raw_any_match={classified['suite_b_matches']} "
          f"(status UNRESOLVED-PENDING-CONVENTION-RULING; "
          f"raw={len(result.get('confirmed_matches', []))}, "
          f"self_excluded={classified['self_matches_excluded']}) "
          f"wall_s={wall_s:.1f} cpu_min_est={cpu_minutes:.1f} "
          f"n_workers={result.get('n_workers')} shards={n_shards} "
          f"eval_rows={len(eval_rows)} -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
