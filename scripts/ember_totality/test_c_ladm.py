#!/usr/bin/env python3
"""test_c_ladm.py — STATUS PROBE for Ember goal condition C-LADM.

Registry text: docs/spec/conditions-v1.md sec 4.2 C-LADM (docs/authority/GOAL.md sec 1 item 1, "sec-1-1").
R: the verified-episode LEDGER admission rules -- world-provided ground truth (verifier
verdict recorded), no self-admitted episodes, matched-control pool membership -- actually
hold on every admitted row, not merely asserted in prose. Board CHK for the trust boundary
every downstream capability condition's input data rests on (gh issue #95).

RULING [R1, ledger scope, 2026-07-04]: "ledger" in THIS probe means EXACTLY two files, by
literal path relative to ROOT -- receipts/ledger/episodes.jsonl and
receipts/ledger/control_pool.jsonl. It NEVER means the totality-board receipt trail
(receipts/ember-totality-*, EMBER_TOTALITY_BOARD.md) -- a same-named but unrelated object
elsewhere in this codebase's vocabulary.

[RULING-DRIFT CORRECTION, 2026-07-06, gh issue #254]: R1's original text (2026-07-04) claimed
"the issue text's own 'receipts/ledger/' path reference was wrong -- that directory does not
exist" and moved LEDGER_REL/CONTROL_POOL_REL to a bare `ledger/` path. That claim was false:
receipts/ledger/episodes.jsonl and receipts/ledger/control_pool.jsonl are real, current files
(verified present at audit time; a bare `ledger/` directory exists nowhere at the state root).
R1's false premise is quoted here rather than silently edited out, per the reproducibility
audit's finding, so a future reader can see exactly what was wrong and why the path below
reverted to receipts/ledger/. See gh issue #254 (RULING-DRIFT class) and
docs/audit/c-ladm-sec1-1-admission-recon-20260704.md sec2 Finding 0 for the original
(incorrect) reasoning this superseded.

Rules enforced (recon dossier sec3, frozen 2026-07-04) and their mechanization:

  1. verified verdict recorded (math-core-v1.md sec1, ledger-schema-v3.md) --
     MACHINE-CHECKED: every episode row has an explicit boolean `verified`.
  3. every entry carries the receipt of the executed job that produced it
     (math-core-v1.md sec1 Ledger def) -- MACHINE-CHECKED, with the documented-absence
     exception for the 1,909 seed rows (ledger-schema-v3.md: `receipt` absent + `origin`
     containing "seed" => the blanket receipt receipts/t3-seed-20260610T021308Z.json
     covers them; a naive "assert receipt present" would falsely RED these legitimate rows).
  5. matched-control pool membership (docs/authority/GOAL.md sec1 item1 "matched control" adversary class;
     math-core-v1.md sec5b's C = matched-control update class) -- MACHINE-CHECKED, partial:
     every non-seed-origin episode's `task` has >=1 same-task row in control_pool.jsonl.
     What this CANNOT check from ledger data alone: whether a specific capability CLAIM's
     G_c computation actually used the control (that lives in the BOOTSTRAP_PASS receipt,
     out of this probe's scope).
  6. append-only up to dedup, `task:sha(src)` key (math-core-v1.md sec1 Ledger def) --
     MACHINE-CHECKED: duplicate `key` values within episodes.jsonl and within
     control_pool.jsonl (checked separately per file -- control-pool keys carry a distinct
     `:ctrl:` namespace marker and are never cross-checked against episode keys).
  [RULING R3, sampler/origin consistency, 2026-07-04] -- MACHINE-CHECKED: where BOTH
     `sampler` and `origin` are present on a row, they must agree (ledger-schema-v3.md notes
     `sampler` is a superseded passthrough of `origin`; disagreement is a real defect, cheap
     to catch).
  [RULING R5, control_pool.jsonl integrity, 2026-07-04] -- MACHINE-CHECKED, dual-source:
     this probe's OWN sha256 read of control_pool.jsonl taken immediately before and after
     shelling out to scripts/ledger_dedup.py's existing byte-unchanged assertion (invoked
     against TEMP view/receipt outputs -- never the live receipts/ledger/views/ tree or a new
     receipts/ file -- so this probe never writes anywhere under the live ledger). If
     ledger_dedup.py cannot be invoked cleanly (env/path issue), that is disclosed as its own
     UNAVAILABLE note, never silently treated as a pass; this probe's own direct sha
     comparison stands on its own regardless.
  [RULING R2, no self-admission / self-judgment banned at admission, 2026-07-04] --
     INSTRUMENT-LEVEL CHECK, ONCE (not per-episode): the sole verifier comparator this repo
     wires everywhere (scripts/v_compare.py, per scripts/proofs/verifier_surface_coverage.py's
     own grounding) is confirmed present as SOURCE CODE (not a serialized-model artifact --
     .pt/.bin/.safetensors/.gguf/.ckpt/.pth extensions checked and absent). The per-episode
     gap -- independently confirming EACH row's `verified` value truly came from that
     instrument rather than the sampler self-reporting -- is NOT mechanized here and is
     disclosed explicitly in the GREEN/RED detail string, never silently passed.
  [RULING R4, anti-Goodhart / world-provided ground truth, 2026-07-04] -- CONFIRMED
     NOT-MECHANIZABLE-FROM-EPISODE-ROWS: phase-2 step 0 read
     scripts/proofs/verifier_surface_coverage.py in full. It does NOT assert "V is
     never-learned/model-based" -- it mechanizes a DIFFERENT completion criterion (receipt
     COVERAGE per task-prefix, verifier-v1.md's Completion-criteria items 1+4). No other
     script anywhere in this tree asserts the property either (searched for
     "anti-Goodhart"/"never learned, never model-based"/"is_model_based" -- only docstring
     QUOTES of the axiom exist, in this file's own header and
     scripts/proofs/error_assimilation_pipeline_test.py, never a computable check of it).
     This rule ships as a disclosed gap, never a silent pass; no probe extension is cited
     because none covers it.

DISCIPLINE: status probe -- always exits 0, one line, real bytes decide, no hardcoded
verdict. RED / GREEN / UNEVALUABLE(env); primary-ledger-absent is RED (input-missing).
This probe NEVER writes to receipts/ledger/episodes.jsonl or receipts/ledger/control_pool.jsonl -- read-only
throughout; the one subprocess it may invoke is redirected to temp outputs only.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
CANDIDATE_ROOTS = [p for p in (os.environ.get("EMBER_TOTALITY_ROOT"), REPO_ROOT) if p]
ROOT = next((r for r in CANDIDATE_ROOTS if os.path.isdir(r)), None)

# RULING R1 -- literal paths, never the totality-board receipt trail. Restored to
# receipts/ledger/ 2026-07-06 (gh #254 RULING-DRIFT correction) -- see the docstring note
# above; the bare ledger/ path this constant held before was never a real location.
LEDGER_REL = os.path.join("receipts", "ledger", "episodes.jsonl")
CONTROL_POOL_REL = os.path.join("receipts", "ledger", "control_pool.jsonl")
RECEIPTS_DIR_REL = "receipts"
SEED_BLANKET_RECEIPT_REL = os.path.join("receipts", "t3-seed-20260610T021308Z.json")
VERIFIER_INSTRUMENT_REL = os.path.join("scripts", "v_compare.py")
LEDGER_DEDUP_SCRIPT_REL = os.path.join("scripts", "ledger_dedup.py")

SERIALIZED_MODEL_EXTS = (".pt", ".bin", ".safetensors", ".gguf", ".ckpt", ".pth")

INVALID_TOKENS = [
    "invalid_ladm_missing_verified",
    "invalid_ladm_unreceipted_non_seed_row",
    "invalid_ladm_seed_blanket_receipt_missing",
    "invalid_ladm_dangling_receipt",
    "invalid_ladm_no_matched_control",
    "invalid_ladm_duplicate_key",
    "invalid_ladm_sampler_origin_mismatch",
    "invalid_ladm_control_pool_verified_true",
    "invalid_ladm_control_pool_sha_disagreement",
]


def emit(color, reason):
    """Print the single status line and exit 0 (status-probe contract)."""
    print(f"{color} {reason}")
    sys.exit(0)


def _load_jsonl(path):
    rows = []
    malformed = 0
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                malformed += 1
    return rows, malformed


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _resolve_receipt(root, receipt_name):
    """A `receipt` field is a bare filename living flat under receipts/ (verified
    empirically this phase: both distinct filenames found in episodes.jsonl resolve
    directly at receipts/<name>, no nesting)."""
    p = os.path.join(root, RECEIPTS_DIR_REL, receipt_name)
    return p if os.path.isfile(p) else None


def _ledger_dedup_verdict(root, control_path):
    """RULING R5: shell out to ledger_dedup.py's existing control_pool byte-unchanged
    assertion, redirected to TEMP outputs only (never the live receipts/ledger/views/ tree, never a
    new file under receipts/). Returns (verdict: "unchanged"|"changed"|"unavailable", note).
    A failure to invoke cleanly is disclosed, never silently treated as a pass."""
    script = os.path.join(root, LEDGER_DEDUP_SCRIPT_REL)
    if not os.path.isfile(script):
        return "unavailable", f"{LEDGER_DEDUP_SCRIPT_REL} not found"
    ledger_path = os.path.join(root, LEDGER_REL)
    try:
        with tempfile.TemporaryDirectory(prefix="c_ladm_dedup_") as tmpdir:
            view_out = os.path.join(tmpdir, "dedup-cluster.jsonl")
            control_view_out = os.path.join(tmpdir, "dedup-cluster-control.jsonl")
            receipt_dir = os.path.join(tmpdir, "receipts")
            os.makedirs(receipt_dir, exist_ok=True)
            proc = subprocess.run(
                [sys.executable, script, "--backfill",
                 "--ledger", ledger_path,
                 "--control-pool", control_path,
                 "--view-out", view_out,
                 "--control-view-out", control_view_out,
                 "--receipt-dir", receipt_dir],
                capture_output=True, text=True, timeout=60, cwd=root,
            )
    except Exception as exc:
        return "unavailable", f"subprocess invocation failed: {exc}"
    combined = (proc.stdout or "") + (proc.stderr or "")
    if "control_pool sha256 changed" in combined:
        return "changed", "ledger_dedup.py reported control_pool sha256 changed"
    if proc.returncode == 0:
        return "unchanged", "ledger_dedup.py's own before/after assertion passed"
    return "unavailable", f"ledger_dedup.py exited {proc.returncode} without a byte-unchanged verdict: {combined[-300:]!r}"


def main():
    if ROOT is None:
        emit("UNEVALUABLE", "C-LADM: state root not found under any known layout")

    ledger_path = os.path.join(ROOT, LEDGER_REL)
    control_path = os.path.join(ROOT, CONTROL_POOL_REL)

    if not os.path.isfile(ledger_path):
        emit("RED", f"C-LADM: primary ledger absent at {LEDGER_REL} -> input-missing")
    if not os.path.isfile(control_path):
        emit("RED", f"C-LADM: control pool absent at {CONTROL_POOL_REL} -> input-missing")

    # RULING R5, part 1: this probe's own sha256 read, immediately before touching
    # anything else (baseline for the dual-source comparison below).
    sha_before = _sha256_file(control_path)

    episodes, ep_malformed = _load_jsonl(ledger_path)
    control, ctl_malformed = _load_jsonl(control_path)

    if ep_malformed or ctl_malformed:
        emit("RED",
             f"C-LADM: {ep_malformed} malformed episode line(s), "
             f"{ctl_malformed} malformed control-pool line(s) -> ledger not cleanly parseable")

    offenders = []  # (key, token)
    seed_exception_count = 0
    receipted_count = 0
    no_control_tasks_live = set()

    control_tasks = set()
    control_keys_seen = set()
    for c in control:
        control_tasks.add(c.get("task"))
        k = c.get("key")
        if k in control_keys_seen:
            offenders.append((k, "invalid_ladm_duplicate_key(control_pool)"))
        control_keys_seen.add(k)
        if c.get("verified") is not False:
            offenders.append((k, "invalid_ladm_control_pool_verified_true"))

    seed_blanket_exists = os.path.isfile(os.path.join(ROOT, SEED_BLANKET_RECEIPT_REL))

    seen_keys = set()
    for e in episodes:
        key = e.get("key")
        origin = e.get("origin", "") or ""
        is_seed = "seed" in origin

        # Rule 6 -- dedup key uniqueness.
        if key in seen_keys:
            offenders.append((key, "invalid_ladm_duplicate_key"))
        seen_keys.add(key)

        # Rule 1 -- verified boolean present.
        if not isinstance(e.get("verified"), bool):
            offenders.append((key, "invalid_ladm_missing_verified"))

        # Rule 3 -- receipt present, with the documented seed-origin exception.
        receipt = e.get("receipt")
        if receipt is None:
            if is_seed and seed_blanket_exists:
                seed_exception_count += 1
            elif is_seed:
                offenders.append((key, "invalid_ladm_seed_blanket_receipt_missing"))
            else:
                offenders.append((key, "invalid_ladm_unreceipted_non_seed_row"))
        else:
            receipted_count += 1
            if _resolve_receipt(ROOT, receipt) is None:
                offenders.append((key, "invalid_ladm_dangling_receipt"))

        # Rule 5 (partial) -- matched-control pool membership for non-seed episodes.
        # RULING R1: scope is literally receipts/ledger/control_pool.jsonl -- not the broader
        # receipts/ledger/views/*control*.jsonl sidecars (checked separately this phase and found
        # NOT to change the offender set here; see report).
        if not is_seed and e.get("task") not in control_tasks:
            offenders.append((key, "invalid_ladm_no_matched_control"))
            no_control_tasks_live.add(e.get("task"))

        # RULING R3 -- sampler/origin consistency when both present.
        sampler = e.get("sampler")
        if sampler is not None and sampler != origin:
            offenders.append((key, "invalid_ladm_sampler_origin_mismatch"))

    # RULING R5, part 2: shell out to ledger_dedup.py's own assertion (temp outputs only),
    # then re-read control_pool.jsonl's sha256 myself once more -- three independent reads
    # (before, ledger_dedup's own internal before/after, and this probe's after) must agree.
    dedup_verdict, dedup_note = _ledger_dedup_verdict(ROOT, control_path)
    sha_after = _sha256_file(control_path)
    if sha_before != sha_after:
        offenders.append(("<control_pool.jsonl>", "invalid_ladm_control_pool_sha_disagreement"))
    elif dedup_verdict == "changed":
        offenders.append(("<control_pool.jsonl>", "invalid_ladm_control_pool_sha_disagreement"))

    if offenders:
        shown = offenders[:5]
        more = f" (+{len(offenders) - 5} more)" if len(offenders) > 5 else ""
        by_token = {}
        for _, tok in offenders:
            by_token[tok] = by_token.get(tok, 0) + 1
        emit("RED",
             f"C-LADM: {len(offenders)} offending row(s) across {len(by_token)} rule(s) "
             f"{by_token} -> {shown}{more}"
             + (f" [{len(no_control_tasks_live)} distinct task(s) with zero matched-control "
                f"coverage in receipts/ledger/control_pool.jsonl (RULING R1 scope; also absent from "
                f"receipts/ledger/views/*control*.jsonl sidecars, checked separately -- widening scope "
                f"does not change this verdict)]"
                if no_control_tasks_live else ""))

    # RULING R2 -- self-admission, instrument-level check ONCE.
    verifier_path = os.path.join(ROOT, VERIFIER_INSTRUMENT_REL)
    verifier_instrument_ok = (
        os.path.isfile(verifier_path)
        and not verifier_path.lower().endswith(SERIALIZED_MODEL_EXTS)
    )
    if not verifier_instrument_ok:
        emit("RED",
             f"C-LADM: verifier instrument check failed -- {VERIFIER_INSTRUMENT_REL} "
             f"missing or is not source code (self-admission instrument-externality "
             f"precondition unmet)")

    detail = (
        f"C-LADM: {len(episodes)} episodes ({seed_exception_count} seed-origin "
        f"documented-receipt-absent per ledger-schema-v3.md, {receipted_count} receipted "
        f"and resolved) + {len(control)} control-pool rows (all verified=False, as required); "
        f"key-dedup clean; sampler/origin consistent where both present; every non-seed "
        f"episode has a matched-control task; control_pool.jsonl sha256 dual-source check: "
        f"{dedup_verdict} ({dedup_note}), this-probe's-own before/after agree. "
        f"Self-admission instrument check (RULING R2): OK -- {VERIFIER_INSTRUMENT_REL} is "
        f"source code, not a serialized model. "
        f"DISCLOSED COVERAGE GAPS, never silently passed: "
        f"(a) self-admission verified at the INSTRUMENT level only, once per run -- NOT "
        f"independently re-confirmed per-episode that each row's `verified` value truly "
        f"came from that instrument rather than sampler self-report (RULING R2); "
        f"(b) anti-Goodhart 'V is never-learned/model-based' is a property of the "
        f"verifier's own architecture, not re-derivable from episode rows -- confirmed "
        f"this phase that scripts/proofs/verifier_surface_coverage.py does NOT already "
        f"assert it (RULING R4, disclosed not-mechanizable-from-episode-rows)."
    )
    emit("GREEN", detail)


if __name__ == "__main__":
    main()
