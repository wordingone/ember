# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""receipt_semantic_check.py — semantic receipt validator (complements receipt_check.py).

receipt_check.py is the SCHEMA floor: "is this a well-formed receipt?" (ticket/ts present,
hash fields declare sha_convention, counts are ints). It deliberately does NOT look at whether
the receipt's CLAIM is supported by the receipt's own contents.

This module is the SEMANTIC layer: "do the receipt's own numbers support its own verdict?"
It exists because of the self-attestation defect: a board/probe that trusts a receipt's
self-reported `verdict=...PASS` / `pass=true` / `verified=true` measures receipt-authoring,
not the organism. A semantic finding means the receipt attests a verdict its own contents
contradict; such a receipt must NOT green a condition until the contradiction is resolved.

Every check re-derives a judgment from the receipt's own fields — it never trusts a label.
The verified failure patterns this catches (each reproduced in --selftest):
  S1 placeholder_in_loadbearing : DRAFT / TODO / FIXME / <<...>> / "not computed" / "fill"
                                  / "placeholder" in any string value (a draft is not a result)
  S2 placeholder_provenance     : a *sha256*/*hash*/*digest* field whose value is not a real
                                  digest (sha256_not_computed, null, "", "TODO", non-hex, wrong len)
  S3 pass_with_failing_subfield : the receipt's top-level verdict reads PASS, but a nested
                                  *pass*/*gate_pass* boolean is false, or a nested verdict/status
                                  string reads FAIL / BLOCKED / DRAFT (a pass riding a failing sub-receipt)
  S4 deletion_not_load_bearing  : a deleted/ablated score equals its matched baseline — the
                                  deletion arm must DEGRADE, else the mechanism is not load-bearing
  S5 claim_vs_number            : a {value, threshold, op, claims_pass} assertion (explicit, or a
                                  value/threshold/pass trio found in a sub-dict) whose re-derived
                                  pass disagrees with the claimed verdict
  S6 nonpositive_delta          : a *delta* field claimed positive but <=0, or a *_ratio* claimed
                                  >1 but <=1 (a "positive delta" that is not positive)
  S7 paid_surface               : paid_api_surface_used true or api_spend_usd>0 (the zero-cost law)

API:  semantic_validate(receipt: dict) -> list[dict]   # [{code, field, detail, severity}, ...]
      empty list == no semantic contradiction found (necessary, not sufficient — a clean
      semantic scan does NOT prove the claim, only that the receipt does not refute itself).

CLI:  --selftest        constructed receipts reproducing each pattern; prints
                         RECEIPT_SEMANTIC_SELFTEST_PASS; exits non-zero on failure
      --file X           fail-closed on a single receipt (exit non-zero on any finding)
      --scan DIR         report-only over every *.json in DIR (exit 0; lists self-attesting receipts)

sha_convention for any receipt this writes: "bytes on disk as-is (binary read, no line-ending
normalization)".
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

# Strings that mark a value as a draft / stub / unfilled placeholder rather than a result.
# Strong markers only — a value that literally reads DRAFT / <<...>> / "fill from the run" is a
# stub; the bare word "placeholder" in prose that *describes* a naming convention is excluded
# (it caused false positives on receipts whose subject is placeholder handling).
_PLACEHOLDER_RE = re.compile(
    r"<<.*?>>|\{\{.*?\}\}|\bTODO\b|\bFIXME\b|\bTBD\b|\bDRAFT\b|"
    r"not[ _]comput|not[ _]measured|fill[ _](in|me|from)|to[ _]be[ _]filled|REPLACE_ME",
    re.IGNORECASE,
)

# List-valued container keys that legitimately hold per-case test fixtures: a `verified:false`
# inside one of these is the test exercising a negative case, NOT a pass riding a failure.
_TEST_FIXTURE_ANCESTOR_RE = re.compile(
    r"(^|[.\[])(cases|rows|tests|examples|findings|probes|samples|trials|negative|fixtures)([.\[]|$)",
    re.IGNORECASE,
)

# Keys that carry a cryptographic-digest VALUE — that value must be a real digest. Restricted to
# digest-denoting suffixes (not the bare word "hash", which matches algo/method metadata keys).
_HASH_KEY_RE = re.compile(r"sha256|sha_256|sha1|(^|_)digest$|(^|_)checksum$", re.IGNORECASE)
# A real digest contains a BOUNDED hex run of exactly 40 (sha1) or 64 (sha256) chars. Bounded so a
# 59-char repeating fake (no exact-40/64 boundary) is rejected, while real values in prefixed/OCI
# form ("sha256:<64hex>", "repo@sha256:<64hex>", "<64hex>") all pass.
_HEX_DIGEST_RE = re.compile(r"(?<![0-9a-fA-F])(?:[0-9a-fA-F]{64}|[0-9a-fA-F]{40})(?![0-9a-fA-F])")
# Keys that are provenance-adjacent metadata, not digest values (skip S2 on these).
_HASH_KEY_EXEMPT_RE = re.compile(r"convention|algo|algorithm|method|scheme|_re$|pattern", re.IGNORECASE)

# Verdict/status keys whose string value declares the receipt's headline result.
_VERDICT_KEY_RE = re.compile(r"^(verdict|status|result|gate_status|outcome)$", re.IGNORECASE)
_PASS_TOKEN_RE = re.compile(r"\bPASS\b|_PASS\b|\bGREEN\b|\bSATISFIED\b|\bOK\b", re.IGNORECASE)
_FAIL_TOKEN_RE = re.compile(r"\bFAIL\b|_FAIL\b|\bBLOCKED\b|\bRED\b|\bDRAFT\b|\bERROR\b|\bINVALID\b", re.IGNORECASE)

_PASS_BOOL_KEY_RE = re.compile(r"(^|_)(pass|gate_pass|passed|verified|ok)$", re.IGNORECASE)
# S3 only flags a top-level PASS riding a false GATE-level boolean (the C-EFF "pass over a failing
# confirmation gate" pattern). Per-component sub-flags (tok_s_pass, ns5_pass, per-shape .pass) are
# excluded: a receipt may honestly record verdict=JOB_PASS while an internal component flag is false.
_S3_GATE_KEY_RE = re.compile(r"(^|_)(gate_pass|gate_status|overall_pass)$", re.IGNORECASE)

_DELTA_KEY_RE = re.compile(r"(^|_)delta($|_)", re.IGNORECASE)
_RATIO_KEY_RE = re.compile(r"_ratio$|^ratio$|speedup|compound", re.IGNORECASE)

_DELETED_KEY_RE = re.compile(r"deleted|ablat|without|reverted", re.IGNORECASE)
# The TREATMENT arm (the full mechanism). Deletion must move the score AWAY from this — if the
# deleted/ablated arm equals the treatment arm, removing the component changed nothing.
_TREATMENT_KEY_RE = re.compile(r"(^|_)(c_score|c_arm|full|treatment|trained|with_organ|with_operator)($|_)", re.IGNORECASE)

_THRESHOLD_KEY_RE = re.compile(r"threshold|required|floor|criterion|minimum|min_", re.IGNORECASE)
# Trio heuristic: throughput-gate idiom only (a >= gate). Excludes ratio/compound/claim to avoid
# inverting on kill-below adjudications.
_TRIO_VALUE_KEY_RE = re.compile(r"tok_s|tokens_per|throughput|\bmfu\b", re.IGNORECASE)
_TRIO_PASS_KEY_RE = re.compile(r"(^|_)(gate_pass|passed)$", re.IGNORECASE)

_OPS = {
    ">=": lambda a, b: a >= b,
    ">": lambda a, b: a > b,
    "<=": lambda a, b: a <= b,
    "<": lambda a, b: a < b,
    "==": lambda a, b: a == b,
}


def _finding(code: str, field: str, detail: str, severity: str = "error") -> dict[str, str]:
    return {"code": code, "field": field, "detail": detail, "severity": severity}


def _walk(obj: Any, path: str = ""):
    """Yield (path, key, value) for every key in every nested dict, and descend lists."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{path}.{k}" if path else str(k)
            yield p, k, v
            yield from _walk(v, p)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            p = f"{path}[{i}]"
            yield from _walk(v, p)


def _is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _top_verdict_is_pass(receipt: dict) -> bool:
    """True iff the receipt's headline result reads PASS-like and not FAIL-like."""
    for k, v in receipt.items():
        if _VERDICT_KEY_RE.match(str(k)) and isinstance(v, str):
            if _PASS_TOKEN_RE.search(v) and not _FAIL_TOKEN_RE.search(v):
                return True
        if _PASS_BOOL_KEY_RE.search(str(k)) and v is True:
            return True
    return False


# ---------------------------------------------------------------------------
# The checks
# ---------------------------------------------------------------------------

def _check_placeholders(receipt: dict) -> list[dict]:
    out = []
    for path, _k, v in _walk(receipt):
        if isinstance(v, str) and _PLACEHOLDER_RE.search(v):
            out.append(_finding(
                "S1_placeholder_in_loadbearing", path,
                f"placeholder/draft marker in value: {v[:80]!r}",
            ))
    return out


def _check_provenance(receipt: dict) -> list[dict]:
    out = []
    for path, k, v in _walk(receipt):
        ks = str(k)
        if not _HASH_KEY_RE.search(ks) or _HASH_KEY_EXEMPT_RE.search(ks):
            continue
        # Only judge scalar leaf values that purport to BE a digest.
        if isinstance(v, (dict, list)):
            continue
        if v is None or v == "":
            # a missing digest is a provenance GAP, not necessarily self-attestation → warn, not error
            out.append(_finding("S2_placeholder_provenance", path, "hash field is null/empty", severity="warn"))
        elif isinstance(v, str) and not _HEX_DIGEST_RE.search(v):
            out.append(_finding(
                "S2_placeholder_provenance", path,
                f"hash field is not a 40/64-hex digest: {v[:60]!r}",
            ))
    return out


def _check_pass_with_failing_subfield(receipt: dict) -> list[dict]:
    out = []
    if not _top_verdict_is_pass(receipt):
        return out
    for path, k, v in _walk(receipt):
        ks = str(k)
        # A failing boolean/verdict inside a per-case test-fixture list is the test exercising a
        # negative case, not a pass riding a failure — skip those (false-positive class).
        if _TEST_FIXTURE_ANCESTOR_RE.search(path):
            continue
        # nested GATE boolean ==false (gate_pass / gate_status / overall_pass), not per-component flags
        if _S3_GATE_KEY_RE.search(ks) and v is False and "." in path:
            out.append(_finding(
                "S3_pass_with_failing_subfield", path,
                "top-level verdict reads PASS but a nested gate_pass/gate_status boolean is false",
            ))
        # nested verdict/status string that reads FAIL/BLOCKED/DRAFT
        if _VERDICT_KEY_RE.match(ks) and isinstance(v, str) and "." in path:
            if _FAIL_TOKEN_RE.search(v) and not _PASS_TOKEN_RE.search(v):
                out.append(_finding(
                    "S3_pass_with_failing_subfield", path,
                    f"top-level verdict reads PASS but nested {ks}={v[:60]!r} reads FAIL/BLOCKED/DRAFT",
                ))
    return out


def _check_deletion_load_bearing(receipt: dict) -> list[dict]:
    """The deletion/ablation arm must DEGRADE the treatment arm. If the deleted/ablated score equals
    the treatment (C / full / trained) score, removing the component changed nothing → not load-bearing.
    (Deletion reverting to a *baseline* is the CORRECT result and is NOT flagged.)"""
    out = []
    for path, _k, v in _walk(receipt):
        if not isinstance(v, dict):
            continue
        deleted = {kk: vv for kk, vv in v.items() if _DELETED_KEY_RE.search(str(kk)) and _is_number(vv)}
        treatment = {kk: vv for kk, vv in v.items()
                     if (_TREATMENT_KEY_RE.search(str(kk)) or str(kk).lower() in ("c_score", "c"))
                     and _is_number(vv)}
        for dk, dv in deleted.items():
            for tk, tv in treatment.items():
                if dv == tv:
                    out.append(_finding(
                        "S4_deletion_not_load_bearing", f"{path}.{dk}",
                        f"deleted/ablated score {dk}={dv} equals treatment {tk}={tv}; deletion did not degrade",
                    ))
    return out


def _check_assertions(receipt: dict) -> list[dict]:
    """S5: re-derive pass from {value, threshold, op, claims_pass} or a value/threshold/pass trio."""
    out = []
    for path, _k, v in _walk(receipt):
        if not isinstance(v, dict):
            continue
        # explicit assertion block
        if "value" in v and "threshold" in v and _is_number(v.get("value")) and _is_number(v.get("threshold")):
            op = v.get("op", ">=")
            fn = _OPS.get(op, _OPS[">="])
            derived = fn(v["value"], v["threshold"])
            claimed = v.get("claims_pass", v.get("pass", None))
            if claimed is not None and bool(claimed) != bool(derived):
                out.append(_finding(
                    "S5_claim_vs_number", path,
                    f"claims_pass={claimed} but value {v['value']} {op} {v['threshold']} is {derived}",
                ))
            continue
        # value/threshold/pass trio inferred from sibling keys. Restricted to the throughput-GATE
        # idiom (a `gate_pass`/`passed` boolean alongside a measured throughput vs a threshold,
        # which is a >= gate). NOT applied to `claim_pass`/`verified` or to ratio/compound values —
        # those are kill-adjudications (pass-if-BELOW) and would invert the >= assumption.
        val = next(((kk, vv) for kk, vv in v.items() if _TRIO_VALUE_KEY_RE.search(str(kk)) and _is_number(vv)), None)
        thr = next(((kk, vv) for kk, vv in v.items() if _THRESHOLD_KEY_RE.search(str(kk)) and _is_number(vv)), None)
        pas = next(((kk, vv) for kk, vv in v.items() if _TRIO_PASS_KEY_RE.search(str(kk)) and isinstance(vv, bool)), None)
        if val and thr and pas:
            derived = val[1] >= thr[1]
            if bool(pas[1]) != bool(derived):
                out.append(_finding(
                    "S5_claim_vs_number", path,
                    f"{pas[0]}={pas[1]} but {val[0]}={val[1]} >= {thr[0]}={thr[1]} is {derived}",
                ))
    return out


def _check_delta_sign(receipt: dict) -> list[dict]:
    out = []
    for path, k, v in _walk(receipt):
        ks = str(k)
        if _DELTA_KEY_RE.search(ks) and _is_number(v) and v <= 0:
            out.append(_finding(
                "S6_nonpositive_delta", path,
                f"delta field {ks}={v} is not positive", severity="warn",
            ))
        if _RATIO_KEY_RE.search(ks) and _is_number(v) and 0 < v <= 1:
            out.append(_finding(
                "S6_nonpositive_delta", path,
                f"ratio/speedup field {ks}={v} is <=1 (claims an improvement it does not show)",
                severity="warn",
            ))
    return out


def _check_paid_surface(receipt: dict) -> list[dict]:
    out = []
    for path, k, v in _walk(receipt):
        ks = str(k).lower()
        if ks == "paid_api_surface_used" and v is True:
            out.append(_finding("S7_paid_surface", path, "paid_api_surface_used=true (zero-cost law)"))
        if ks == "api_spend_usd" and _is_number(v) and v > 0:
            out.append(_finding("S7_paid_surface", path, f"api_spend_usd={v}>0 (zero-cost law)"))
    return out


def semantic_validate(receipt: dict) -> list[dict]:
    """Return semantic findings (empty == receipt does not refute itself)."""
    if not isinstance(receipt, dict):
        return [_finding("S0_not_a_dict", "", f"expected dict, got {type(receipt).__name__}")]
    findings: list[dict] = []
    findings += _check_placeholders(receipt)
    findings += _check_provenance(receipt)
    findings += _check_pass_with_failing_subfield(receipt)
    findings += _check_deletion_load_bearing(receipt)
    findings += _check_assertions(receipt)
    findings += _check_delta_sign(receipt)
    findings += _check_paid_surface(receipt)
    # dedup identical (code, field)
    seen = set()
    uniq = []
    for f in findings:
        key = (f["code"], f["field"], f["detail"])
        if key not in seen:
            seen.add(key)
            uniq.append(f)
    return uniq


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _scan(directory: Path) -> int:
    files = sorted(directory.rglob("*.json"))
    flagged = 0
    for fp in files:
        try:
            data = _load(fp)
        except Exception as exc:
            print(f"  PARSE-ERROR {fp}: {exc}")
            continue
        if not isinstance(data, dict):
            continue
        findings = semantic_validate(data)
        errs = [f for f in findings if f["severity"] == "error"]
        if errs:
            flagged += 1
            print(f"\nSELF-ATTESTING: {fp.relative_to(directory)}")
            for f in errs:
                print(f"  [{f['code']}] {f['field']}: {f['detail']}")
    print(f"\nSCAN: {flagged}/{len(files)} receipts carry a semantic contradiction (error-severity).")
    return 0


def _selftest() -> int:
    cases: list[tuple[str, dict, str]] = []
    # Each case: (name, receipt, expected-finding-code-substring or "" for clean)

    # S1 — DRAFT status + <<placeholder>> (the verified C-EFF draft pattern; neutralized)
    cases.append((
        "S1 draft+placeholder",
        {"ticket": "T", "ts": "Z", "verdict": "C_EFF_PASS",
         "status": "DRAFT — operator fills throughput from the GPU confirmation run",
         "mfu_note": "<<placeholder>>"},
        "S1_placeholder_in_loadbearing",
    ))
    # S2 — sha256_not_computed provenance (the verified C-BASE manifest pattern)
    cases.append((
        "S2 placeholder provenance",
        {"ticket": "T", "ts": "Z", "verdict": "C_BASE_PASS", "sha_convention": "bytes as-is",
         "manifest": [{"component": "core", "sha256": "sha256_not_computed"}]},
        "S2_placeholder_provenance",
    ))
    # S3 — top-level PASS riding a nested gate_pass=false (the verified C-EFF sub-receipt pattern)
    cases.append((
        "S3 pass over failing subfield",
        {"ticket": "T", "ts": "Z", "verdict": "C_EFF_PASS",
         "confirmation": {"gate_pass": False, "tok_s": 19327}},
        "S3_pass_with_failing_subfield",
    ))
    # S4 — deletion arm equals the TREATMENT (C) arm: removing the component changed nothing.
    cases.append((
        "S4 deletion not load-bearing",
        {"ticket": "T", "ts": "Z", "verdict": "C14_PASS",
         "arms": {"a_score": 0.10, "b_score": 0.40, "c_score": 0.55, "deleted_score": 0.55}},
        "S4_deletion_not_load_bearing",
    ))
    # S4 control — deletion reverts to baseline (the CORRECT ablation): must NOT flag
    cases.append((
        "S4 correct ablation (deleted->baseline, not flagged)",
        {"ticket": "T", "ts": "Z", "verdict": "C14_PASS",
         "arms": {"a_score": 0.10, "b_score": 0.40, "c_score": 0.55, "deleted_score": 0.40}},
        "",
    ))
    # S5 — claimed pass contradicts value vs threshold
    cases.append((
        "S5 claim vs number (explicit)",
        {"ticket": "T", "ts": "Z", "verdict": "PASS",
         "throughput_gate": {"value": 19327, "threshold": 25463, "op": ">=", "claims_pass": True}},
        "S5_claim_vs_number",
    ))
    cases.append((
        "S5 claim vs number (trio)",
        {"ticket": "T", "ts": "Z",
         "bench": {"tok_s": 19327, "threshold": 25463, "gate_pass": True}},
        "S5_claim_vs_number",
    ))
    # S6 — non-positive delta claimed as a positive result
    cases.append((
        "S6 nonpositive delta",
        {"ticket": "T", "ts": "Z", "verdict": "PASS", "score_delta": -0.02},
        "S6_nonpositive_delta",
    ))
    cases.append((
        "S6 ratio <= 1",
        {"ticket": "T", "ts": "Z", "verdict": "PASS", "compound_ratio": 0.87},
        "S6_nonpositive_delta",
    ))
    # S7 — paid surface used
    cases.append((
        "S7 paid surface",
        {"ticket": "T", "ts": "Z", "verdict": "PASS", "api_spend_usd": 5.0},
        "S7_paid_surface",
    ))
    # CLEAN control — a genuine receipt: real digest, consistent numbers, deletion degrades, no draft
    cases.append((
        "CLEAN control",
        {"ticket": "T", "ts": "Z", "verdict": "C_EFF_PASS", "sha_convention": "bytes as-is",
         "config_sha256": "184ab8c5b1a6ed0aa12bf3aea88925cfeb6a08830d6f266d5023cdb0643ea9f6",
         "throughput_gate": {"value": 26000, "threshold": 25463, "op": ">=", "claims_pass": True},
         "arms": {"a_score": 0.10, "b_score": 0.40, "c_score": 0.55, "deleted_score": 0.12},
         "score_delta": 0.15, "compound_ratio": 1.65,
         "api_spend_usd": 0, "paid_api_surface_used": False},
        "",
    ))

    print("SELF-TEST: receipt_semantic_check\n" + "=" * 56)
    passed = 0
    for name, receipt, expect in cases:
        findings = semantic_validate(receipt)
        codes = {f["code"] for f in findings}
        if expect == "":
            good = (len([f for f in findings if f["severity"] == "error"]) == 0
                    and len(findings) == 0)
        else:
            good = any(expect in c for c in codes)
        passed += good
        tag = "PASS" if good else "XXXX"
        got = ",".join(sorted(codes)) or "<none>"
        print(f"[{tag}] {name}: expected {expect or '<clean>'} | got {got}")
        if not good:
            for f in findings:
                print(f"        {f}")
    ok = passed == len(cases)
    print("=" * 56 + f"\nSELF-TEST: {passed}/{len(cases)} as expected")
    print("RECEIPT_SEMANTIC_SELFTEST_PASS" if ok else "RECEIPT_SEMANTIC_SELFTEST_FAIL")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="semantic receipt validator (complements receipt_check.py)")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--file", help="fail-closed on a single receipt")
    ap.add_argument("--scan", help="report-only over every *.json under DIR")
    args = ap.parse_args()
    if args.selftest:
        return _selftest()
    if args.file:
        findings = semantic_validate(_load(Path(args.file)))
        errs = [f for f in findings if f["severity"] == "error"]
        for f in findings:
            print(f"[{f['severity']}] {f['code']} {f['field']}: {f['detail']}")
        if not findings:
            print("OK: no semantic contradiction")
        return 1 if errs else 0
    if args.scan:
        return _scan(Path(args.scan))
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
