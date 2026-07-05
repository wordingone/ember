#!/usr/bin/env python3
"""Ember totality test - Condition C(-1) / C-NEG1 (status probe / TDD).

C(-1) - No paid-service dependency.
  R: the decisive before/after, A<local-mount-point>/C/deleted, transfer, deletion-sensitive,
     and field-level claims proven through a ZERO-INCREMENTAL-SPEND path;
     api_spend_usd=0, paid_api_surface_used=false.
  Does NOT count: a money-costing API key, hosted model, paid judge, paid
     leaderboard, commercial credential, or cloud credit as blocker /
     required comparison / substitute verifier / quality floor / reason to
     pause/clear. If an identical rubric runs via local code / checked-in or
     free artifacts / non-metered models / authorized subagent judge, that
     zero-cost verifier governs; paid parity is optional non-authoritative
     metadata recorded only after a zero-cost receipt passes.
  Invalid-token (explicit X): invalid_paid_api_exit_ramp
  CHK: clear packet contains zero paid-surface dependency.

LANE-14 HARDENING (2026-07-02, R8 probe-faithfulness audit,
docs/goalforge-debate-ledger.md row R8): the pre-hardening version scanned
every receipt under receipts/ that happened to self-declare BOTH
api_spend_usd and paid_api_surface_used, and GREENed on the first (later:
last-in-sort-order) one satisfying zero-cost -- with NO check on that
receipt's own verdict. R8: "C(-1) went GREEN on a packet whose own verdict
is BLOCKED" (field-level-contribution-proof-20260622T222500Z.json, verdict
FIELD_LEVEL_CONTRIBUTION_PROOF_BLOCKED, zero-cost fields notwithstanding).
Two independent fixes, per the R8-queued hardening:

  (a) VERDICT-LINKAGE: the accepted "best" packet must itself be a
      PASS-class decisive claim (verdict contains PASS, and neither BLOCKED
      nor FAIL) -- a receipt whose own decisive claim did not succeed is not
      evidence that a "decisive claim" was zero-cost-proven; it proves
      nothing was decided at all.

  (b) ALL decisive-claim receipts, not any-one: self-declaring the two
      clear-packet fields is voluntary. A decisive-claim receipt (one that
      renders a `verdict`) that stays SILENT on api_spend_usd /
      paid_api_surface_used has not "proven" a zero-incremental-spend path
      -- it simply never said. Because the condition text is "every
      decisive claim proven through a zero-incremental-spend path" (not
      "no decisive claim proven through a paid one"), an undeclared
      decisive claim cannot be waved through: it counts as an
      UNVERIFIED-SPEND decisive claim, and its presence blocks GREEN
      exactly like an explicit paid-surface violation would. This closes
      the self-attestation gap the R8 audit graded this probe as: only
      receipts that VOLUNTEERED the two fields were ever checked, so a
      paid dependency in an undeclared decisive-claim receipt would sail
      through silently.

ANNEX-COVERAGE AMENDMENT (2026-07-03, gh issue #17, drafted at
scratch/c-neg1-annex-amendment.md, session-reviewed and landed here):
hardening (b) above is a correct floor but had no ceiling -- an undeclared
decisive receipt could never become spend-proven without editing the
historical receipt itself (banned: fabrication). This amendment adds a
SECOND, additive evidence path that never touches a historical receipt:
the newest receipts/spend-annex/spend-annex-*.json (built by
spend_annex_scan.py, issue #17) may cover an undeclared receipt IF AND
ONLY IF the annex carries a row for that exact path whose evidence_class
is "declared", "script_scanned_clean", or "script_scanned_clean_via_
convention" (2026-07-03 mapping-pass addition -- same evidence bar, just
resolved via a confirmed filename-convention table instead of a receipt
field; never "unresolvable" -- that is the literal mechanism preserving
"undeclared != proven-zero": an unresolvable row is the annex's own
honest admission it could not prove zero-spend, so it blocks GREEN
exactly as an absent annex would) AND
whose sha256 matches the receipt file's CURRENT on-disk sha256
(anti-staleness/anti-tamper -- an annex generated against an older
version of a receipt is not evidence about the current one). Any row in
the newest annex with evidence_class "paid_surface_violation" hard-fails
C(-1) unconditionally, same severity class as an explicit
api_spend_usd/paid_api_surface_used violation. No annex file, or an
unparsable one, falls back to the exact pre-amendment behavior.

This is a STATUS PROBE. It always exits 0 and prints exactly one line
beginning with "RED " or "GREEN ". RED/GREEN is determined by really
inspecting state under <external-state> - never hardcoded.
"""

import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _lane14_common import sha256_file as _sha256_file  # noqa: E402

# --- Locate the state root ----------------------------------------------------
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
CANDIDATE_ROOTS = [
    p for p in (os.environ.get("EMBER_TOTALITY_ROOT"), REPO_ROOT,
                os.path.join(REPO_ROOT, "<external-state>"))
    if p
]
ROOT = next((r for r in CANDIDATE_ROOTS if os.path.isdir(r)), None)

# --- Invalid-tokens / paid-surface dependency markers --------------------------
INVALID_TOKENS = [
    "invalid_paid_api_exit_ramp",   # the explicit X token
    "paid-api",
    "paid_api",
    "hosted-model",
    "hosted_model",
    "paid-judge",
    "paid_judge",
    "paid-leaderboard",
    "paid_leaderboard",
    "commercial-credential",
    "commercial_credential",
    "cloud-credit",
    "cloud_credit",
]

SPEND_KEY = "api_spend_usd"
PAID_FLAG_KEY = "paid_api_surface_used"
VERDICT_KEY = "verdict"

# A decisive claim's own verdict must contain PASS and neither of these.
NOT_PASS_MARKERS = ("BLOCKED", "FAIL")


def emit(color, reason):
    print(f"{color} {reason}")
    sys.exit(0)


def _as_bool_true(v):
    if isinstance(v, bool):
        return v is True
    if isinstance(v, (int, float)):
        return v != 0
    if isinstance(v, str):
        return v.strip().lower() in ("true", "yes", "1")
    return False


def _spend_nonzero(v):
    if isinstance(v, bool):
        return False
    if isinstance(v, (int, float)):
        return v != 0
    if isinstance(v, str):
        s = v.strip()
        try:
            return float(s) != 0.0
        except ValueError:
            return False
    return False


def _is_pass_class(verdict_str):
    v = str(verdict_str).upper()
    if not v:
        return False
    if any(marker in v for marker in NOT_PASS_MARKERS):
        return False
    return "PASS" in v


def _decisive_claim_files():
    """Every JSON receipt under ROOT/receipts/** that renders a non-empty
    `verdict` -- the structural definition of "a decisive claim" used
    consistently across this receipt corpus (resident-training-gate,
    field-level-*, native-operator-*, scienceagentbench-*, etc. all key
    their outcome under `verdict`)."""
    out = []
    for p in glob.glob(os.path.join(ROOT, "receipts", "**", "*.json"), recursive=True):
        if not os.path.isfile(p):
            continue
        # [SESSION-REVIEWED 2026-07-03 round 3] the spend-annex's own output
        # family is the coverage LEDGER, not a decisive experimental claim --
        # its verdict field describes coverage. Counting it made every annex
        # regeneration a fresh undeclared decisive receipt forever (a
        # treadmill this probe was chasing). Mirrors the scanner's own
        # corpus-membership rule.
        base = os.path.basename(p)
        rel_dir = os.path.basename(os.path.dirname(p))
        if rel_dir == "spend-annex" and base.startswith("spend-annex-"):
            continue
        try:
            with open(p, "r", encoding="utf-8", errors="ignore") as fh:
                raw = fh.read()
            d = json.loads(raw)
        except Exception:
            continue
        if not isinstance(d, dict):
            continue
        v = d.get(VERDICT_KEY)
        if isinstance(v, str) and v.strip():
            out.append((p, d, raw))
    return sorted(out, key=lambda t: t[0])


def _newest_spend_annex(root):
    """Return (rows_by_path: dict[str, dict], annex_path_or_None). rows_by_path keys
    are the annex row's own 'path' field (already root-relative, forward-slashed).
    Picks the lexicographically-newest spend-annex-*.json under receipts/spend-annex/
    (the compact-ts filename convention sorts correctly). Malformed/missing annex ->
    ({}, None), never raises -- absence must fall back to the pre-amendment behavior,
    not crash the probe."""
    cand = sorted(glob.glob(os.path.join(root, "receipts", "spend-annex", "spend-annex-*.json")))
    if not cand:
        return {}, None
    newest = cand[-1]
    try:
        with open(newest, "r", encoding="utf-8", errors="ignore") as fh:
            annex = json.load(fh)
    except Exception:
        return {}, None
    if not isinstance(annex, dict) or not isinstance(annex.get("rows"), list):
        return {}, None
    by_path = {}
    for row in annex["rows"]:
        if isinstance(row, dict) and isinstance(row.get("path"), str):
            by_path[row["path"]] = row
    return by_path, newest


def main():
    if ROOT is None:
        emit("UNEVALUABLE",
             "C(-1): state root not found under any known layout "
             f"({CANDIDATE_ROOTS}) -> input-missing, dead branch under the "
             "flat-layout resolver (paper-consistency flip, 2026-07-02)")

    decisive = _decisive_claim_files()
    if not decisive:
        emit("RED", "C(-1): no decisive-claim (verdict-bearing) receipts found "
                    "under receipts/ -> clear-packet artifact ABSENT")

    declared_ok = []          # (rel, verdict) -- declares zero-cost cleanly, no invalid-token
    declared_pass_ok = []     # subset of declared_ok whose verdict is PASS-class
    spend_violations = []     # (rel, value)
    paid_violations = []      # (rel, value)
    invalid_hits = []         # (rel, tokens)
    undeclared = []           # (rel, verdict) -- decisive claim, spend fields absent
    near_miss = []            # declares one/both fields but not cleanly zero-cost

    for p, d, raw in decisive:
        rel = os.path.relpath(p, ROOT)
        verdict = d.get(VERDICT_KEY, "")
        low = raw.lower()

        has_both = (SPEND_KEY in d) and (PAID_FLAG_KEY in d)
        if not has_both:
            undeclared.append((rel, verdict))
            continue

        # legitimate field name "paid_api_surface_used" contains "paid_api" --
        # scrub it before substring-scanning for the invalid-token markers.
        scrub = low.replace("paid_api_surface_used", "")
        hit = sorted({t for t in INVALID_TOKENS if t.lower() in scrub})
        if hit:
            invalid_hits.append((rel, hit))
            continue

        if _spend_nonzero(d.get(SPEND_KEY)):
            spend_violations.append((rel, d.get(SPEND_KEY)))
            continue
        if _as_bool_true(d.get(PAID_FLAG_KEY)):
            paid_violations.append((rel, d.get(PAID_FLAG_KEY)))
            continue

        spend_zero = (d.get(SPEND_KEY) == 0) or (d.get(SPEND_KEY) == 0.0)
        paid_false = (d.get(PAID_FLAG_KEY) is False) or \
                     (str(d.get(PAID_FLAG_KEY)).strip().lower() == "false")
        if not (spend_zero and paid_false):
            near_miss.append(f"{rel}: fields present but not zero-cost "
                              f"({SPEND_KEY}={d.get(SPEND_KEY)!r}, "
                              f"{PAID_FLAG_KEY}={d.get(PAID_FLAG_KEY)!r})")
            continue

        declared_ok.append((rel, verdict))
        if _is_pass_class(verdict):
            declared_pass_ok.append((rel, verdict))

    # --- Hard fails: an explicit paid-surface violation anywhere -----------------
    if spend_violations:
        rel, val = spend_violations[0]
        emit("RED", f"C(-1): paid-surface dependency present - {rel} has "
                    f"{SPEND_KEY}={val!r} (nonzero spend) -> condition NOT met")
    if paid_violations:
        rel, val = paid_violations[0]
        emit("RED", f"C(-1): paid-surface dependency present - {rel} has "
                    f"{PAID_FLAG_KEY}={val!r} (paid API used) -> condition NOT met")
    if not declared_pass_ok and invalid_hits:
        rel, toks = invalid_hits[0]
        emit("RED", f"C(-1): invalid-token present in {rel} {toks} "
                    "(does-NOT-count paid surface) and no PASS-class clean "
                    "clear packet found -> condition NOT met")

    # (a) VERDICT-LINKAGE: no PASS-class zero-cost decisive claim exists.
    if not declared_pass_ok:
        if declared_ok:
            rel, verdict = declared_ok[0]
            emit("RED",
                 f"C(-1): zero-cost decisive-claim receipt(s) exist but NONE "
                 f"are PASS-class (e.g. {rel} verdict={verdict!r}) -> a "
                 "non-PASS decisive claim does not prove a decisive claim was "
                 "zero-cost-proven; VERDICT-LINKAGE not satisfied")
        emit("RED", "C(-1): no clear-packet receipt declares "
                    f"{SPEND_KEY}=0 AND {PAID_FLAG_KEY}=false on a PASS-class "
                    f"verdict (clear packet ABSENT). near_miss={near_miss[:3]}")

    # (b) ALL decisive claims, not any-one -- UNCHANGED in spirit. An undeclared
    # decisive-claim receipt is UNVERIFIED spend UNLESS the newest sha-pinned
    # spend-annex (receipts/spend-annex/spend-annex-*.json, gh issue #17) covers it
    # with evidence_class != "unresolvable" and a matching current-on-disk sha256.
    # This never edits the historical receipt (fabrication-banned) -- it is a
    # separate, additive, machine-scanned proof that the probe is now willing to
    # accept as a second path to the same "proven through a zero-incremental-spend
    # path" requirement the registry text already states.
    annex_rows, annex_path = _newest_spend_annex(ROOT)

    annex_violations = [r for p, r in annex_rows.items() if r.get("evidence_class") == "paid_surface_violation"]
    if annex_violations:
        rel = annex_violations[0].get("path")
        emit("RED", f"C(-1): newest spend-annex ({os.path.relpath(annex_path, ROOT)}) "
                    f"reports evidence_class=paid_surface_violation for {rel} -> "
                    "condition NOT met (annex-detected paid-surface dependency)")

    still_undeclared = []
    annex_covered = []
    for rel, verdict in undeclared:
        # annex rows are keyed by forward-slash paths (spend_annex_scan.py's own
        # convention); `rel` here is os.path.relpath's OS-native separator (backslash
        # on Windows) -- normalize ONLY for the lookup key, never for display/os calls.
        row = annex_rows.get(rel.replace("\\", "/"))
        if (row is not None
                and row.get("evidence_class") in (
                    "declared", "script_scanned_clean", "script_scanned_clean_via_convention",
                    # [SESSION-REVIEWED 2026-07-03, gh #17] content-clean narrowing:
                    # generator-absent rows count ONLY when the receipt's OWN text
                    # scanned clean of paid-vendor/API-key patterns (class assigned
                    # by the scanner only after that per-row content scan). The raw
                    # generator_absent_historical class (evidenced-absent but
                    # content-DIRTY, or pre-narrowing rows) is deliberately NOT
                    # accepted -- script-absence is not spend-absence.
                    "generator_absent_content_clean",
                    # [SESSION-REVIEWED 2026-07-03 round 3] same narrowing
                    # pattern: external-live-generator rows count ONLY after
                    # their own receipt text scanned clean.
                    "external_generator_content_clean")
                and isinstance(row.get("sha256"), str)):
            on_disk_sha = _sha256_file(os.path.join(ROOT, rel))
            if on_disk_sha == row["sha256"]:
                annex_covered.append((rel, verdict, row["evidence_class"]))
                continue
        still_undeclared.append((rel, verdict))

    # Byte-identical regression floor: when the annex covers nothing (no annex
    # present, unparsable, or every undeclared receipt stays undeclared),
    # still_undeclared == undeclared exactly (same content, same order -- nothing
    # was ever skipped) and both RED/GREEN messages below must read EXACTLY as
    # they did before this amendment, not merely "equivalent". The annex-aware
    # wording only appears once annex_covered is non-empty.
    if still_undeclared:
        sample = [rel for rel, _v in still_undeclared[:5]]
        if annex_covered:
            emit("RED",
                 f"C(-1): {len(still_undeclared)}/{len(decisive)} decisive-claim "
                 f"(verdict-bearing) receipts never declare {SPEND_KEY}/"
                 f"{PAID_FLAG_KEY} AND are not annex-covered "
                 f"-> zero-incremental-spend is UNPROVEN for those claims "
                 "(undeclared != proven-zero); 'every decisive claim' is not "
                 f"satisfied by one clean packet alone. sample={sample}"
                 + (f" ... +{len(still_undeclared) - 5} more" if len(still_undeclared) > 5 else ""))
        emit("RED",
             f"C(-1): {len(undeclared)}/{len(decisive)} decisive-claim "
             f"(verdict-bearing) receipts never declare {SPEND_KEY}/"
             f"{PAID_FLAG_KEY} -> zero-incremental-spend is UNPROVEN for "
             "those claims (undeclared != proven-zero); 'every decisive "
             f"claim' is not satisfied by one clean packet alone. sample={sample}"
             + (f" ... +{len(undeclared) - 5} more" if len(undeclared) > 5 else ""))

    best_rel, best_verdict = declared_pass_ok[-1]
    if annex_covered:
        annex_note = (f"; {len(annex_covered)} additional receipt(s) covered via "
                       f"sha-pinned spend-annex {os.path.relpath(annex_path, ROOT)}")
        emit("GREEN",
             f"C(-1): PASS-class clear packet {best_rel} (verdict={best_verdict!r}) "
             f"declares {SPEND_KEY}=0, {PAID_FLAG_KEY}=false, no invalid-token; "
             f"ALL {len(decisive)} decisive-claim (verdict-bearing) receipts under "
             "receipts/ declare zero paid-surface dependency (none undeclared-and-"
             f"uncovered, none violating){annex_note}")
    emit("GREEN",
         f"C(-1): PASS-class clear packet {best_rel} (verdict={best_verdict!r}) "
         f"declares {SPEND_KEY}=0, {PAID_FLAG_KEY}=false, no invalid-token; "
         f"ALL {len(decisive)} decisive-claim (verdict-bearing) receipts under "
         "receipts/ declare zero paid-surface dependency (none undeclared, "
         "none violating)")


if __name__ == "__main__":
    main()
