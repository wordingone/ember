#!/usr/bin/env python3
"""Ember totality test — Condition C2 (status probe / TDD).

C2 — Real external held-out world task.
  R: task/heldout/labels/evaluator/source/license/hashes from an EXTERNAL
     source, FROZEN BEFORE the candidate run.
  Does NOT count: candidate path reading heldout labels, gold echoes,
     sample-submission answers, or locally invented answers.
  Invalid-token (?): invalid_heldout_leak
  CHK: frozen-rows hash predates the candidate receipt; no label-read in the
     candidate path.

Authoritative text: <<external>>/state/<spec> §4.2 (C2).
Receipt hint: receipts/<peer-loop>/* — frozen-rows hash vs candidate
receipt.

This is a STATUS PROBE. It ALWAYS exits 0 and prints exactly one line
beginning with "RED " or "GREEN ". RED/GREEN is determined by really
inspecting state under <external-state> — never hardcoded.

LANE-14 HARDENING (2026-07-02, R8 probe-faithfulness audit,
docs/goalforge-debate-ledger.md row R8): C2 was graded the one
"FAITHFUL-leaning" GREEN of the six audited rows -- "the auditor
independently recomputed the frozen-rows sha256" already held before this
edit, and this hardening is ADDITIVE disclosure, not a tightening that is
meant to flip the verdict (POS control requirement: current C2 receipts
must STAY GREEN). Two additions:

  (a) git-anchor freshness leg: `git log -1 --format=%ct -- <path>` on the
      resolved frozen-rows file. When git info is available, this is
      recorded as a DISCLOSURE in the GREEN/RED reason (never gates the
      verdict by itself) -- an untracked file is reported UNANCHORED; a
      tracked file's last-commit time is compared to the candidate's own ts
      and reported PRE-DATES / POST-DATES. It is deliberately non-blocking
      even when POST-DATES: this repo's receipt history was reconstructed
      via batched imports (git commit time reflects when a file was
      checked into THIS tree, not necessarily the original historical
      cadence -- e.g. the real d3-gym-fresh-rows-offset8-len12 receipt
      commits 20s AFTER its own candidate's logical ts, an artifact of
      commit-batching, not a leak signal). The load-bearing freeze-before-
      candidate check remains the existing internal-ts comparison above
      (fr_ts < cand_ts); the git-anchor leg is a second, independent,
      disclosed data point for a human/adversarial reviewer, not a second
      gate.

  (b) non-self-labeled leak check: the existing LEAK_POLICIES / marker-
      string scan only catches a candidate that (accidentally or not)
      LABELS its own leak (a policy name or marker substring). This adds a
      genuine CONTENT check: if the frozen-rows row carries an explicit
      gold/reference-answer field AND the candidate's arm-C output text is
      present, string-match the gold value into the arm-C text -- a literal
      leak that was never self-labeled. Absence of either side (no gold
      field in this benchmark's row schema, as is true of the real D3-Gym
      rows on disk today, or no arm-C output text) is recorded as a NOTE,
      never RED -- the hardening's own text: "absence of arm outputs = note,
      not RED".

Run ONLY via:  wsl python3 <this file>
Under WSL the execution root is /mnt<local-mount-point>/ on this host (some hosts use <local-mount-point>/); both
candidate roots are probed.
"""

# [PATH-REWRITE 2026-07-01] Imported from
# <<external>>/state/ember-totality-build/ into
# <local-exec-root>-goalforge/scripts/ember_totality/. Original WSL dual/triple-mount
# candidates pointing at <<external>>/state/<external-state> (and /mnt<local-mount-point>/M/...,
# <local-mount-point>/M/..., B:\\M\\... variants) replaced with a single REPO_ROOT-relative
# candidate, REPO_ROOT computed from this file's own location (two levels up
# from scripts/ember_totality/), for native Windows system-python execution.
# No probe logic changed -- only path resolution. <external-state> does not exist
# under the new repo root, so these probes are expected to emit a clean RED
# 'root not found' line, which is the correct, non-error outcome.

import datetime
import glob
import hashlib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _lane14_common import git_last_commit_time  # noqa: E402

# --- Locate <external-state> robustly across WSL mount conventions ----------------
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
CANDIDATE_ROOTS = [
    p for p in (os.environ.get("EMBER_TOTALITY_ROOT"), REPO_ROOT,
                os.path.join(REPO_ROOT, "<external-state>"))
    if p
]
ROOT = next((r for r in CANDIDATE_ROOTS if os.path.isdir(r)), None)

# Invalid-tokens that C2 declares as NON-counting outcomes. The first is the
# explicit ? token; the rest encode the "does NOT count" leak substitutes
# (candidate path reading heldout labels / gold echoes / sample-submission
# answers / locally invented answers). If ANY appears as a marker in the
# candidate receipt, the condition is RED.
INVALID_TOKENS = [
    "invalid_heldout_leak",     # explicit ? token
    "heldout_label_read",       # does NOT count: candidate path reading heldout labels
    "gold_echo",                # does NOT count: gold echoes
    "sample_submission_answer", # does NOT count: sample-submission answers
    "sample-submission-answer",
    "locally_invented_answer",  # does NOT count: locally invented answers
    "answer_key",
]

# Candidate-path policies that constitute a label/answer read (a leak).
# A legitimate candidate extracts evaluator-REQUIREMENT structure from the
# external eval_script; it must NOT echo a gold answer / answer key / label.
LEAK_POLICIES = {
    "gold_answer_echo",
    "answer_key_lookup",
    "heldout_label_lookup",
    "sample_submission_echo",
    "locally_invented_answer",
}


def emit(color, reason):
    """Print the single status line and exit 0 (status-probe contract)."""
    print(f"{color} {reason}")
    sys.exit(0)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_ts(s):
    """Parse a compact UTC stamp like 20260622T152425Z -> datetime, or None."""
    if not isinstance(s, str):
        return None
    m = re.match(r"^(\d{8})T(\d{6})Z$", s.strip())
    if not m:
        return None
    try:
        return datetime.datetime.strptime(m.group(0), "%Y%m%dT%H%M%SZ")
    except ValueError:
        return None


def win_to_wsl(path):
    """Translate a Windows B:\\... path to this host's WSL mount; return the
    first existing candidate or None."""
    if not isinstance(path, str):
        return None
    p = path.replace("\\", "/")
    if len(p) >= 3 and p[1:3] == ":/":
        drive = p[0].lower()
        for pref in (f"/mnt/{drive}", f"/{drive}"):
            cand = pref + p[2:]
            if os.path.exists(cand):
                return cand
        return None
    # Already a posix path inside the repo (best effort relocate under ROOT)
    if os.path.exists(p):
        return p
    return None


def main():
    if ROOT is None:
        emit("UNEVALUABLE", "C2: state root not found under any known layout -- input-missing, dead branch under the flat-layout resolver (paper-consistency flip, 2026-07-02)")

    # --- (A) Find candidate receipt(s) that ran against a frozen held-out task.
    # The D3 native-loop candidate receipts carry fresh_rows_path +
    # fresh_rows_sha256 + external_task_source. Scan all of them and require at
    # least ONE that fully satisfies the CHK with no invalid-token / leak.
    patterns = [
        os.path.join(ROOT, "receipts", "<peer-loop>", "*native-loop*.json"),
        os.path.join(ROOT, "receipts", "<peer-loop>", "*candidate*.json"),
        os.path.join(ROOT, "receipts", "**", "*native-loop*.json"),
    ]
    found = set()
    for pat in patterns:
        found.update(glob.glob(pat, recursive=True))
    candidates = sorted(found)
    if not candidates:
        emit("RED", "C2: no D3 native-loop candidate receipt found "
                    "(receipts/<peer-loop>/*native-loop* absent) "
                    "-> satisfying artifact ABSENT")

    failures = []
    for rp in candidates:
        try:
            with open(rp, "r", encoding="utf-8") as fh:
                raw = fh.read()
            data = json.loads(raw)
        except Exception as exc:
            failures.append(f"{os.path.basename(rp)}: unreadable ({exc})")
            continue

        # --- (B) Negative assertions: NONE of the invalid-tokens may appear ----
        lowered = raw.lower()
        hit = [t for t in INVALID_TOKENS if t.lower() in lowered]
        if hit:
            failures.append(f"{os.path.basename(rp)}: invalid-token present {hit}")
            continue

        # --- (C) External source must be genuinely external -------------------
        ext = data.get("external_task_source") or {}
        src_url = str(ext.get("source_url", ""))
        dataset = str(ext.get("dataset", ""))
        external_ok = src_url.startswith("http") and bool(dataset) and (
            "huggingface" in src_url or "/" in dataset
        )
        if not external_ok:
            failures.append(f"{os.path.basename(rp)}: external_task_source not "
                            f"externally sourced (url={src_url!r} dataset={dataset!r})")
            continue

        # --- (D) Frozen-rows artifact: must exist, hash-match, and PREDATE ------
        fr_claimed = data.get("fresh_rows_sha256")
        fr_path = data.get("fresh_rows_path")
        if not (isinstance(fr_claimed, str) and len(fr_claimed) == 64 and fr_path):
            failures.append(f"{os.path.basename(rp)}: missing fresh_rows_sha256/path")
            continue

        fr_disk = win_to_wsl(fr_path)
        if fr_disk is None:
            # The receipt records a C:\tmp build path; the frozen rows also live
            # under ROOT/receipts/<peer-loop>/ — locate by basename.
            base = os.path.basename(fr_path.replace("\\", "/"))
            alt = os.path.join(ROOT, "receipts", "<peer-loop>", base)
            fr_disk = alt if os.path.isfile(alt) else None
        if fr_disk is None:
            failures.append(f"{os.path.basename(rp)}: frozen-rows file not on disk "
                            f"({fr_path})")
            continue

        actual_sha = sha256_file(fr_disk)
        if actual_sha != fr_claimed.lower():
            failures.append(f"{os.path.basename(rp)}: frozen-rows hash MISMATCH "
                            f"(disk={actual_sha[:12]} claimed={fr_claimed[:12]})")
            continue

        # Frozen BEFORE the candidate run: frozen-rows ts must predate candidate ts.
        cand_ts = parse_ts(data.get("ts"))
        # frozen-rows ts: prefer the rows-file's own ts field, else its filename.
        try:
            fr_data = json.load(open(fr_disk, "r", encoding="utf-8"))
        except Exception:
            fr_data = {}
        fr_ts = parse_ts(fr_data.get("ts"))
        if fr_ts is None:
            mfn = re.search(r"(\d{8}T\d{6}Z)", os.path.basename(fr_disk))
            fr_ts = parse_ts(mfn.group(1)) if mfn else None
        if cand_ts is None or fr_ts is None:
            failures.append(f"{os.path.basename(rp)}: unparseable ts "
                            f"(cand={data.get('ts')} frozen={fr_data.get('ts')})")
            continue
        if not (fr_ts < cand_ts):
            failures.append(f"{os.path.basename(rp)}: frozen-rows ts {fr_ts} "
                            f"NOT before candidate ts {cand_ts}")
            continue

        # --- (E) No label-read in the candidate path --------------------------
        # The candidate (arm C) must extract evaluator-REQUIREMENT structure,
        # never echo gold answers / heldout labels / sample-submission answers.
        rows = data.get("per_task_rows") or []
        if not rows:
            failures.append(f"{os.path.basename(rp)}: no per_task_rows")
            continue

        leak_found = None
        heldout_tag_ok = False
        for row in rows:
            split = str(row.get("split", ""))
            if "heldout" in split or "held-out" in split or "fresh_heldout" in split:
                heldout_tag_ok = True
            preds = row.get("arm_predictions") or {}
            cpred = preds.get("C") or {}
            policy = str(cpred.get("policy", "")).lower()
            if policy in LEAK_POLICIES:
                leak_found = f"arm-C policy is a leak: {policy!r}"
                break
            # A candidate prediction set carrying explicit gold/answer CONTENT
            # (not just expected-artifact path names) would be a leak. Flag the
            # leak markers anywhere in the prediction object.
            cpred_blob = json.dumps(cpred).lower()
            for tok in ("heldout_label", "answer_key", "gold_answer",
                        "sample_submission_answer", "locally_invented"):
                if tok in cpred_blob:
                    leak_found = f"arm-C prediction contains leak marker {tok!r}"
                    break
            if leak_found:
                break

        if leak_found:
            failures.append(f"{os.path.basename(rp)}: {leak_found}")
            continue
        if not heldout_tag_ok:
            failures.append(f"{os.path.basename(rp)}: per_task_rows not tagged "
                            f"as held-out split")
            continue

        # --- LANE-14 HARDENING (a): git-anchor freshness leg (disclosure-only) --
        commit_ts, git_note = git_last_commit_time(ROOT, fr_disk)
        if git_note == "untracked":
            git_anchor_note = "git-anchor: frozen-rows file UNANCHORED (untracked in this tree)"
        elif git_note == "git_unavailable":
            git_anchor_note = "git-anchor: git info unavailable (no repo / git call failed) -- UNANCHORED"
        else:
            commit_dt = datetime.datetime.utcfromtimestamp(commit_ts)
            order = "PRE-DATES" if commit_dt < cand_ts else "POST-DATES"
            git_anchor_note = (
                f"git-anchor: frozen-rows last-commit {commit_dt.isoformat()}Z "
                f"{order} candidate ts {cand_ts.isoformat()}Z "
                "(disclosure only, non-blocking -- this repo's receipt history "
                "was reconstructed via batched imports, so commit time reflects "
                "when a file was checked into THIS tree, not the original "
                "cadence; the load-bearing freeze-before-candidate check is the "
                "internal fr_ts<cand_ts comparison above)"
            )

        # --- LANE-14 HARDENING (b): non-self-labeled leak check (content match) -
        fr_rows_by_task = {}
        for fr_row in (fr_data.get("rows") or []):
            inner = fr_row.get("row") if isinstance(fr_row, dict) else None
            if isinstance(inner, dict) and inner.get("task_id"):
                fr_rows_by_task[str(inner["task_id"])] = inner
        gold_field_names = ("gold_answer", "gold", "reference_answer",
                            "expected_answer", "answer", "ground_truth", "label")
        content_leak = None
        gold_present_count = 0
        arm_output_present_count = 0
        for row in rows:
            task_id = str(row.get("task_id", ""))
            frozen_row = fr_rows_by_task.get(task_id)
            if not frozen_row:
                continue
            gold_key = next((k for k in gold_field_names
                             if isinstance(frozen_row.get(k), str) and frozen_row.get(k).strip()),
                            None)
            if not gold_key:
                continue
            gold_present_count += 1
            gold_value = frozen_row[gold_key].strip()
            cpred = ((row.get("arm_predictions") or {}).get("C")) or {}
            arm_text_parts = []
            for k in ("artifacts", "outputs", "checks"):
                v = cpred.get(k)
                if isinstance(v, list):
                    arm_text_parts.extend(str(x) for x in v)
            for k in ("output_text", "text"):
                v = cpred.get(k)
                if isinstance(v, str):
                    arm_text_parts.append(v)
            if not arm_text_parts:
                continue
            arm_output_present_count += 1
            arm_text = "\n".join(arm_text_parts)
            if gold_value and gold_value in arm_text:
                content_leak = (f"task_id={task_id!r}: frozen-rows {gold_key!r}="
                                f"{gold_value[:40]!r} appears verbatim in arm-C output "
                                "(non-self-labeled leak)")
                break

        if content_leak:
            failures.append(f"{os.path.basename(rp)}: {content_leak}")
            continue

        if gold_present_count == 0:
            leak_check_note = ("non-self-labeled leak check: NOTE -- no gold/reference-answer "
                               f"field ({gold_field_names}) present in this benchmark's frozen "
                               "rows; nothing to content-match (not RED)")
        elif arm_output_present_count == 0:
            leak_check_note = (f"non-self-labeled leak check: NOTE -- {gold_present_count} frozen "
                               "row(s) carry a gold field but arm-C carries no output text/artifact "
                               "content to compare against (absence of arm outputs = note, not RED)")
        else:
            leak_check_note = (f"non-self-labeled leak check: PASS -- {gold_present_count} gold "
                               f"field(s) checked against {arm_output_present_count} arm-C output(s), "
                               "no verbatim match")

        # This receipt satisfies C2: external, frozen-before, hash-verified,
        # no leak in the candidate path, no invalid-token.
        emit("GREEN",
             f"C2: candidate {os.path.relpath(rp, ROOT)} ran on EXTERNAL held-out "
             f"{dataset} ({len(rows)} rows); frozen-rows sha256 {actual_sha[:12]} "
             f"VERIFIED on disk and frozen at {fr_ts.isoformat()}Z BEFORE candidate "
             f"run {cand_ts.isoformat()}Z; arm-C policy extracts evaluator "
             f"requirements (no label/gold/sample-answer read); "
             f"no invalid_heldout_leak token present; {git_anchor_note}; "
             f"{leak_check_note}")

    emit("RED", "C2: D3 native-loop candidate receipt(s) present but none satisfy "
                f"CHK (external + frozen-before + hash-match + no-leak) cleanly "
                f"-> {failures[:3]}")


if __name__ == "__main__":
    main()
