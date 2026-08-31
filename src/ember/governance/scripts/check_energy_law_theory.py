#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""check_energy_law_theory.py — docs/spec/energy-law-theory-v1.md sec6b receipt-shape checker.

Contract (sec6b, v1.1 as of commit ea859d0, read in full before writing this): "Every receipt
claiming under this document carries: adm_fingerprint {hardware id, corpus manifest combined-sha
(per scripts/manifest_sha.py), val-shard sha, eval-harness sha, governor env}, c_functional_id +
value, e_gpu_hours + power_qualifier (fixed|measured|unqualified), lever_class
(trajectory-preserving | trajectory-altering | conditional-L3-met | conditional-L3-unmet),
claim_type (rate | frontier-shift | matched-capability | triage), h_mli_receipt path (for any
trajectory-preserving claim, incl. the null-arm run paths), m_drift field (pure-rate claims),
marginal_composed paths (composition claims), n_envelope_points + holdout path (fit claims),
c0_grid (matched-capability claims)."

Enforces the sec6 [S] (script-checkable) falsifier tokens mechanically:
  invalid_admissible_drift, invalid_scalarization_swap,
  invalid_rate_claim_for_trajectory_altering, invalid_multiplication_without_marginal,
  invalid_exponent_fit_underdetermined, invalid_class_by_assertion,
  invalid_energy_units_unqualified
[A] (audit-only) tokens (invalid_sup_claim) are NOT checked here — sec6's own discipline: "a
trigger with no evaluator is prose", so this script only claims what it can mechanically decide.

**Design choices disclosed (team-lead: "your call, disclosed"):**
- c_functional_id registry is a tiny in-script pin (CANONICAL_C_FUNCTIONAL_ID), matching sec1's
  "SANCTIONED INTERIM pin" (C := -L_val). A receipt may deviate ONLY if it carries a
  `t4_entry_upgrade_receipt` path that exists on disk (sec1's own pre-registered-upgrade carve-out).
- "Composition claims" are self-declared via `is_composed_multiplier: true` (no other structural
  signal distinguishes a composed-product receipt from a single-lever one).
- "Fit claims" (n_envelope_points/holdout/OoM-span/cross-point-ADM checks) are scoped to
  claim_type=="frontier-shift" receipts that carry an `envelope_points` list — sec3 EXP's fit
  floor is stated for exponent/frontier claims specifically, not every frontier-shift receipt
  necessarily fits a curve, so a frontier-shift receipt WITHOUT `envelope_points` is checked on
  the base+lever_class/claim_type matrix only (not held to the 8-point fit floor).
- DT-6 interop (sec6b tail) is checked only when the receipt self-declares
  `cited_by_ceff_or_cscale_pass: true` — building a cross-receipt citation graph is out of scope
  for a receipt-SHAPE checker; the receipt author is the source of truth for its own citation status.

CLI:
  python check_energy_law_theory.py --file receipts/some-claim.json
  python check_energy_law_theory.py --all              # scans receipts/ AND ALL SUBDIRECTORIES
                                                        # for any receipt whose serialized text
                                                        # cites "energy-law-theory"
  python check_energy_law_theory.py --selftest

Verdict per receipt: PASS | FAIL (token list + reasons) | UNEVALUABLE (not a sec6b claim-shaped
receipt at all -- missing the base field set entirely -- or unreadable/malformed input).
Fail-closed: --file exits nonzero on FAIL/UNEVALUABLE; --all is report-only (exit 0 always,
listing every finding) since it may legitimately find zero or all-UNEVALUABLE receipts.

Stdlib only. No network.
"""
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
RECEIPTS_DIR = REPO_ROOT / "receipts"
SPEC_PATH = REPO_ROOT / "docs" / "spec" / "energy-law-theory-v1.md"

sys.path.insert(0, str(HERE))
import receipt_write  # noqa: E402

SHA_CONVENTION = "bytes on disk as-is (binary read, no line-ending normalization)"

# sec1: "C := -L_val ... the SANCTIONED INTERIM pin" -- the tiny in-script registry.
CANONICAL_C_FUNCTIONAL_ID = "neg_val_loss_v1"

POWER_QUALIFIERS = {"fixed", "measured", "unqualified"}
LEVER_CLASSES = {"trajectory-preserving", "trajectory-altering",
                 "conditional-L3-met", "conditional-L3-unmet"}
CLAIM_TYPES = {"rate", "frontier-shift", "matched-capability", "triage"}
TRAJECTORY_PRESERVING_CLASS = {"trajectory-preserving", "conditional-L3-met"}

BASE_FIELDS = ("adm_fingerprint", "c_functional_id", "c_functional_value",
              "e_gpu_hours", "power_qualifier", "lever_class", "claim_type")
ADM_SUBFIELDS = ("hardware_id", "corpus_manifest_sha", "val_shard_sha",
                 "eval_harness_sha", "governor_env")
DT6_TRIPLE = ("signal_per_gpu_hour", "equal_wallclock_band", "exceeds_band")


class Unevaluable(Exception):
    """Not a sec6b claim-shaped receipt at all, or unreadable/malformed input."""


# ---------------------------------------------------------------------------
# Pure-function checks -- each returns a list of (token_or_None, reason) tuples.
# token=None means a base structural finding (not one of the 7 [S] falsifier tokens).
# ---------------------------------------------------------------------------

def check_base_shape(receipt):
    """Returns None if the receipt is not sec6b-claim-shaped at all (missing every base
    field), else a list of per-field findings (possibly empty)."""
    present = [f for f in BASE_FIELDS if f in receipt]
    if not present:
        return None   # not a claim receipt -- caller raises Unevaluable
    findings = []
    for f in BASE_FIELDS:
        if f not in receipt:
            findings.append((None, f"missing required base field '{f}'"))
    if "power_qualifier" in receipt and receipt["power_qualifier"] not in POWER_QUALIFIERS:
        findings.append((None, f"power_qualifier={receipt['power_qualifier']!r} not in "
                               f"{sorted(POWER_QUALIFIERS)}"))
    if "lever_class" in receipt and receipt["lever_class"] not in LEVER_CLASSES:
        findings.append((None, f"lever_class={receipt['lever_class']!r} not in "
                               f"{sorted(LEVER_CLASSES)}"))
    if "claim_type" in receipt and receipt["claim_type"] not in CLAIM_TYPES:
        findings.append((None, f"claim_type={receipt['claim_type']!r} not in "
                               f"{sorted(CLAIM_TYPES)}"))
    return findings


def check_adm_fingerprint(receipt):
    fp = receipt.get("adm_fingerprint")
    if not isinstance(fp, dict):
        return [(None, "adm_fingerprint missing or not an object")]
    return [(None, f"adm_fingerprint missing sub-field '{sf}'")
            for sf in ADM_SUBFIELDS if sf not in fp]


def check_scalarization(receipt, repo_root):
    cid = receipt.get("c_functional_id")
    if cid == CANONICAL_C_FUNCTIONAL_ID:
        return []
    upgrade_path = receipt.get("t4_entry_upgrade_receipt")
    if upgrade_path and (repo_root / upgrade_path).is_file():
        return []   # pre-registered T4-entry upgrade, sec1's carve-out
    return [("invalid_scalarization_swap",
            f"c_functional_id={cid!r} != registry {CANONICAL_C_FUNCTIONAL_ID!r} and no "
            f"existing t4_entry_upgrade_receipt path")]


def check_class_by_assertion(receipt, repo_root):
    lever_class = receipt.get("lever_class")
    if lever_class not in TRAJECTORY_PRESERVING_CLASS:
        return []
    h = receipt.get("h_mli_receipt")
    if not isinstance(h, dict):
        return [("invalid_class_by_assertion",
                f"lever_class={lever_class!r} requires h_mli_receipt {{path, "
                f"null_arm_run_paths}}, got {h!r}")]
    path = h.get("path")
    null_arms = h.get("null_arm_run_paths")
    reasons = []
    if not path or not (repo_root / path).is_file():
        reasons.append(("invalid_class_by_assertion",
                        f"h_mli_receipt.path {path!r} does not exist on disk"))
    if not isinstance(null_arms, list) or not null_arms:
        reasons.append(("invalid_class_by_assertion",
                        "h_mli_receipt.null_arm_run_paths missing or empty (sec3 H-MLI "
                        "mandates a null control arm)"))
    else:
        for p in null_arms:
            if not (repo_root / p).is_file():
                reasons.append(("invalid_class_by_assertion",
                                f"h_mli_receipt.null_arm_run_paths entry {p!r} does not "
                                f"exist on disk"))
    return reasons


def check_m_drift(receipt):
    """pure-rate claims (claim_type=='rate' from a trajectory-preserving-class lever)
    require an m_drift field. Not an [S]-token failure (no dedicated token names this),
    reported as a base structural finding."""
    if receipt.get("claim_type") == "rate" and receipt.get("lever_class") in TRAJECTORY_PRESERVING_CLASS:
        if "m_drift" not in receipt:
            return [(None, "claim_type=rate on a trajectory-preserving lever requires "
                          "an m_drift field")]
    return []


def check_composition(receipt, repo_root):
    if not receipt.get("is_composed_multiplier"):
        return []
    paths = receipt.get("marginal_composed")
    if not isinstance(paths, list) or not paths:
        return [("invalid_multiplication_without_marginal",
                "is_composed_multiplier=true but marginal_composed is missing/empty")]
    missing = [p for p in paths if not (repo_root / p).is_file()]
    if missing:
        return [("invalid_multiplication_without_marginal",
                f"marginal_composed path(s) do not exist on disk: {missing}")]
    return []


def check_trajectory_altering_protocol(receipt):
    """sec2/sec6: a trajectory-altering lever's rate/frontier-shift claim without a
    valid (>=3-level) c0_grid is invalid_rate_claim_for_trajectory_altering. matched-
    capability claim_type is the CORRECT protocol and is exempt."""
    if receipt.get("lever_class") != "trajectory-altering":
        return []
    claim_type = receipt.get("claim_type")
    if claim_type not in ("rate", "frontier-shift"):
        return []   # matched-capability (correct protocol) and triage (permitted) exempt
    grid = receipt.get("c0_grid")
    if not isinstance(grid, list) or len(grid) < 3:
        return [("invalid_rate_claim_for_trajectory_altering",
                f"lever_class=trajectory-altering, claim_type={claim_type!r} requires "
                f"c0_grid with >=3 levels, got {grid!r}")]
    return []


def check_matched_capability_grid(receipt):
    """matched-capability claims always require the >=3-level c0_grid, independent of
    lever_class (sec2's certification protocol for this claim_type)."""
    if receipt.get("claim_type") != "matched-capability":
        return []
    grid = receipt.get("c0_grid")
    if not isinstance(grid, list) or len(grid) < 3:
        return [(None, f"claim_type=matched-capability requires c0_grid with >=3 "
                       f"levels, got {grid!r}")]
    return []


def check_energy_units_qualified(receipt):
    if receipt.get("claim_type") != "frontier-shift":
        return []
    if receipt.get("power_qualifier") == "unqualified":
        return [("invalid_energy_units_unqualified",
                "claim_type=frontier-shift (a frontier claim) with power_qualifier="
                "unqualified")]
    return []


def check_fit_floor_and_admissible_drift(receipt, repo_root):
    """sec3 EXP fit floor + sec6 invalid_admissible_drift, scoped to frontier-shift
    claims that carry an envelope_points list (see module docstring's disclosed scoping
    choice). Returns (findings, applicable: bool)."""
    if receipt.get("claim_type") != "frontier-shift":
        return [], False
    points = receipt.get("envelope_points")
    if points is None:
        return [], False   # not a fit-style frontier-shift claim (disclosed scope)

    findings = []
    n = receipt.get("n_envelope_points")
    holdout_path = receipt.get("holdout_path")
    e_span_log10 = receipt.get("e_span_log10")

    underdetermined_reasons = []
    if not isinstance(n, int) or n < 8:
        underdetermined_reasons.append(f"n_envelope_points={n!r} < 8")
    if not isinstance(e_span_log10, (int, float)) or e_span_log10 < 1.0:
        underdetermined_reasons.append(f"e_span_log10={e_span_log10!r} < 1.0 (>=1 OoM required)")
    if not holdout_path or not (repo_root / holdout_path).is_file():
        underdetermined_reasons.append(f"holdout_path {holdout_path!r} missing/does not exist")
    if underdetermined_reasons:
        findings.append(("invalid_exponent_fit_underdetermined",
                        "; ".join(underdetermined_reasons)))

    if isinstance(points, list) and len(points) >= 2:
        fps = []
        for pt in points:
            if not isinstance(pt, dict) or "adm_fingerprint" not in pt:
                findings.append((None, f"envelope_points entry missing adm_fingerprint: {pt!r}"))
                continue
            fps.append(pt["adm_fingerprint"])
        if fps and any(fp != fps[0] for fp in fps):
            findings.append(("invalid_admissible_drift",
                            "envelope_points carry differing adm_fingerprint values within "
                            "one fit claim"))

    return findings, True


def check_dt6_interop(receipt):
    if not receipt.get("cited_by_ceff_or_cscale_pass"):
        return []
    missing = [f for f in DT6_TRIPLE if f not in receipt]
    if missing:
        return [(None, f"cited_by_ceff_or_cscale_pass=true requires the DT-6 triple, "
                       f"missing: {missing}")]
    return []


# ---------------------------------------------------------------------------
# Combined receipt check
# ---------------------------------------------------------------------------

def check_receipt(receipt, repo_root=REPO_ROOT):
    """Returns {verdict, tokens, findings}. Raises Unevaluable if the receipt is not
    sec6b-claim-shaped at all (no base fields present)."""
    if not isinstance(receipt, dict):
        raise Unevaluable("receipt did not parse to a JSON object")

    base = check_base_shape(receipt)
    if base is None:
        raise Unevaluable("no sec6b base fields present -- not a claim-shaped receipt "
                          "(citing the document in spec_ref alone does not make a receipt "
                          "a sec6b claim)")

    all_findings = list(base)
    all_findings += check_adm_fingerprint(receipt)
    all_findings += check_scalarization(receipt, repo_root)
    all_findings += check_class_by_assertion(receipt, repo_root)
    all_findings += check_m_drift(receipt)
    all_findings += check_composition(receipt, repo_root)
    all_findings += check_trajectory_altering_protocol(receipt)
    all_findings += check_matched_capability_grid(receipt)
    all_findings += check_energy_units_qualified(receipt)
    fit_findings, _ = check_fit_floor_and_admissible_drift(receipt, repo_root)
    all_findings += fit_findings
    all_findings += check_dt6_interop(receipt)

    tokens = sorted({t for t, _ in all_findings if t is not None})
    verdict = "FAIL" if all_findings else "PASS"
    return {
        "verdict": verdict,
        "tokens": tokens,
        "findings": [{"token": t, "reason": r} for t, r in all_findings],
    }


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------

def _utc_ts():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _relpath_or_str(p, repo_root):
    try:
        return p.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return str(p)


def _load_receipt(path):
    p = Path(path)
    if not p.is_file():
        raise Unevaluable(f"receipt not found: {p}")
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise Unevaluable(f"receipt {p} unreadable/invalid JSON: {e}")
    return d


def run_file(path, repo_root=REPO_ROOT):
    RECEIPTS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        receipt = _load_receipt(path)
        result = check_receipt(receipt, repo_root)
    except Unevaluable as e:
        print(f"check_energy_law_theory: UNEVALUABLE {path} — {e}")
        return 1

    print(f"check_energy_law_theory: {result['verdict']} {path}")
    if result["findings"]:
        for f in result["findings"]:
            label = f["token"] or "structural"
            print(f"  [{label}] {f['reason']}")
    return 0 if result["verdict"] == "PASS" else 1


def _iter_receipt_files(receipts_dir):
    """receipts_dir/*.json plus receipts_dir/**/*.json (subdirectory receipts), deduped
    and sorted. Mirrors check_publication_gate.py's iter_receipt_files() -- a receipt-
    shape checker that only ever looked at the top level silently missed every
    subdirectory receipt (e.g. receipts/ember-c-scale/), which is a gate hole in the
    same family this checker exists to close, not just a cosmetic gap."""
    root = Path(receipts_dir)
    if not root.is_dir():
        return []
    files = sorted(root.glob("*.json")) + sorted(root.glob("**/*.json"))
    seen = set()
    out = []
    for f in files:
        if f not in seen:
            seen.add(f)
            out.append(f)
    return out


def run_all(receipts_dir=RECEIPTS_DIR, repo_root=REPO_ROOT):
    """Report-only: scans receipts_dir AND ALL SUBDIRECTORIES for any receipt whose
    serialized text cites 'energy-law-theory'. Always exits 0 (may legitimately find
    zero or all-UNEVALUABLE receipts -- that is the honest current state, per the
    theory's own zero-law-grade-receipts banner)."""
    files = _iter_receipt_files(receipts_dir)
    citing = []
    for p in files:
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        if "energy-law-theory" in text:
            citing.append(p)

    print(f"check_energy_law_theory --all: {len(files)} receipt(s) scanned, "
          f"{len(citing)} cite energy-law-theory")

    counts = {"PASS": 0, "FAIL": 0, "UNEVALUABLE": 0}
    for p in citing:
        try:
            receipt = _load_receipt(p)
            result = check_receipt(receipt, repo_root)
            verdict = result["verdict"]
            print(f"  {verdict:12s} {p.name}")
            if result["findings"]:
                for f in result["findings"][:5]:
                    print(f"    [{f['token'] or 'structural'}] {f['reason']}")
        except Unevaluable as e:
            verdict = "UNEVALUABLE"
            print(f"  UNEVALUABLE  {p.name} — {e}")
        counts[verdict] += 1

    print(f"summary: PASS={counts['PASS']} FAIL={counts['FAIL']} "
          f"UNEVALUABLE={counts['UNEVALUABLE']}")

    ts = _utc_ts()
    receipts_dir_p = Path(receipts_dir)
    receipts_dir_p.mkdir(parents=True, exist_ok=True)
    out_path = receipts_dir_p / f"check-energy-law-theory-all-{ts}.json"
    generator_sha256 = hashlib.sha256(Path(__file__).resolve().read_bytes()).hexdigest()
    receipt_write.checked_write(str(out_path), {
        "ticket": "CHECK-ENERGY-LAW-THEORY-ALL",
        "ts": ts,
        "kind": "gate",
        "spec_ref": "docs/spec/energy-law-theory-v1.md sec6b (receipt-field contract)",
        "receipts_scanned": len(files),
        "citing_receipts": [_relpath_or_str(p, repo_root) for p in citing],
        "counts": counts,
        "generator": {"path": "src/ember/governance/scripts/check_energy_law_theory.py", "sha256": generator_sha256},
        "sha_convention": SHA_CONVENTION,
    })
    print(f"receipt: {out_path}")
    return 0


# ---------------------------------------------------------------------------
# Selftest -- one conforming receipt per claim_type + one violator per [S] token.
# ---------------------------------------------------------------------------

def _selftest():
    import tempfile
    import io
    import contextlib

    failures = []

    def check(name, cond):
        status = "PASS" if cond else "FAIL"
        print(f"  [{status}] {name}")
        if not cond:
            failures.append(name)

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)

        def _touch(relpath):
            p = root / relpath
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("{}", encoding="utf-8")
            return relpath

        def _adm(hw="rtx4090-01"):
            return {"hardware_id": hw, "corpus_manifest_sha": "e164ea32", "val_shard_sha": "abc",
                    "eval_harness_sha": "def", "governor_env": "EMBER_VRAM_FRACTION=0.80"}

        def _base(claim_type, lever_class, **extra):
            d = {
                "adm_fingerprint": _adm(),
                "c_functional_id": CANONICAL_C_FUNCTIONAL_ID,
                "c_functional_value": -1.234,
                "e_gpu_hours": 2.5,
                "power_qualifier": "fixed",
                "lever_class": lever_class,
                "claim_type": claim_type,
            }
            d.update(extra)
            return d

        # ================= UNEVALUABLE: not a claim-shaped receipt =================
        not_claim = {"ticket": "X", "ts": "20260702T000000Z", "spec_ref": "energy-law-theory-v1.md"}
        raised = False
        try:
            check_receipt(not_claim, root)
        except Unevaluable:
            raised = True
        check("non-claim-shaped receipt (e.g. a manifest util citing the doc) -> Unevaluable, "
              "never forced through the schema", raised)

        # ================= 4 CONFORMING fixtures, one per claim_type =================

        # -- rate, trajectory-preserving --
        hmli_path = _touch("hmli-1.json")
        null_arm_path = _touch("null-arm-1.json")
        rate_ok = _base("rate", "trajectory-preserving",
                        h_mli_receipt={"path": hmli_path, "null_arm_run_paths": [null_arm_path]},
                        m_drift=0.002)
        r = check_receipt(rate_ok, root)
        check("CONFORMING claim_type=rate (trajectory-preserving, h_mli+m_drift present) "
              "-> PASS", r["verdict"] == "PASS")

        # -- triage (most permissive) --
        triage_ok = _base("triage", "trajectory-altering")
        r = check_receipt(triage_ok, root)
        check("CONFORMING claim_type=triage (trajectory-altering, no c0_grid needed) -> PASS",
              r["verdict"] == "PASS")

        # -- matched-capability, trajectory-altering, c0_grid >=3 --
        mc_ok = _base("matched-capability", "trajectory-altering", c0_grid=[0.5, 1.0, 1.5])
        r = check_receipt(mc_ok, root)
        check("CONFORMING claim_type=matched-capability (c0_grid=3 levels) -> PASS",
              r["verdict"] == "PASS")

        # -- frontier-shift, trajectory-preserving, WITHOUT envelope_points (disclosed
        #    scope: fit floor only applies when envelope_points is present) --
        hmli_path2 = _touch("hmli-2.json")
        null_arm_path2 = _touch("null-arm-2.json")
        fs_ok = _base("frontier-shift", "trajectory-preserving",
                     h_mli_receipt={"path": hmli_path2, "null_arm_run_paths": [null_arm_path2]},
                     m_drift=0.001)
        r = check_receipt(fs_ok, root)
        check("CONFORMING claim_type=frontier-shift (trajectory-preserving, no "
              "envelope_points -> fit floor not applicable, h_mli present) -> PASS",
              r["verdict"] == "PASS")

        # -- frontier-shift WITH a full, valid 8-point fit (exercises the fit floor
        #    + admissible-drift consistency check on the PASS side too) --
        holdout_path = _touch("holdout-1.json")
        fp = _adm()
        fs_fit_ok = _base("frontier-shift", "trajectory-preserving",
                          h_mli_receipt={"path": hmli_path2, "null_arm_run_paths": [null_arm_path2]},
                          m_drift=0.001, n_envelope_points=8, holdout_path=holdout_path,
                          e_span_log10=1.2,
                          envelope_points=[{"adm_fingerprint": fp} for _ in range(8)])
        r = check_receipt(fs_fit_ok, root)
        check("CONFORMING claim_type=frontier-shift WITH a valid 8-point/1.2-OoM/holdout "
              "fit and consistent ADM fingerprints across all points -> PASS",
              r["verdict"] == "PASS")

        # ================= 7 VIOLATOR fixtures, one per [S] token =================

        # -- invalid_admissible_drift --
        fp2 = _adm(hw="rtx4090-02")
        drift_bad = dict(fs_fit_ok)
        drift_bad["envelope_points"] = [{"adm_fingerprint": fp}] * 7 + [{"adm_fingerprint": fp2}]
        r = check_receipt(drift_bad, root)
        check("VIOLATOR invalid_admissible_drift: one envelope point's adm_fingerprint "
              "differs from the rest -> FAIL carries the token",
              r["verdict"] == "FAIL" and "invalid_admissible_drift" in r["tokens"])

        # -- invalid_scalarization_swap --
        swap_bad = _base("triage", "trajectory-altering", c_functional_id="some_other_id_v2")
        r = check_receipt(swap_bad, root)
        check("VIOLATOR invalid_scalarization_swap: c_functional_id off-registry, no "
              "t4_entry_upgrade_receipt -> FAIL carries the token",
              r["verdict"] == "FAIL" and "invalid_scalarization_swap" in r["tokens"])
        # ... but WITH an existing upgrade receipt, it's exempt (carve-out proven both ways)
        upgrade_path = _touch("t4-upgrade.json")
        swap_ok = _base("triage", "trajectory-altering", c_functional_id="cap_M_v2",
                        t4_entry_upgrade_receipt=upgrade_path)
        r = check_receipt(swap_ok, root)
        check("t4_entry_upgrade_receipt carve-out: off-registry id WITH an existing "
              "upgrade receipt path -> exempt, no invalid_scalarization_swap token",
              "invalid_scalarization_swap" not in r["tokens"])

        # -- invalid_rate_claim_for_trajectory_altering --
        alt_bad = _base("frontier-shift", "trajectory-altering")   # no c0_grid at all
        r = check_receipt(alt_bad, root)
        check("VIOLATOR invalid_rate_claim_for_trajectory_altering: trajectory-altering "
              "frontier-shift claim with no c0_grid -> FAIL carries the token",
              r["verdict"] == "FAIL" and "invalid_rate_claim_for_trajectory_altering" in r["tokens"])

        # -- invalid_multiplication_without_marginal --
        comp_bad = _base("rate", "trajectory-preserving",
                         h_mli_receipt={"path": hmli_path, "null_arm_run_paths": [null_arm_path]},
                         m_drift=0.001, is_composed_multiplier=True)   # no marginal_composed
        r = check_receipt(comp_bad, root)
        check("VIOLATOR invalid_multiplication_without_marginal: is_composed_multiplier=true "
              "with no marginal_composed paths -> FAIL carries the token",
              r["verdict"] == "FAIL" and "invalid_multiplication_without_marginal" in r["tokens"])

        # -- invalid_exponent_fit_underdetermined --
        underdet_bad = _base("frontier-shift", "trajectory-preserving",
                             h_mli_receipt={"path": hmli_path2, "null_arm_run_paths": [null_arm_path2]},
                             m_drift=0.001, n_envelope_points=4, holdout_path=holdout_path,
                             e_span_log10=1.2,
                             envelope_points=[{"adm_fingerprint": fp} for _ in range(4)])
        r = check_receipt(underdet_bad, root)
        check("VIOLATOR invalid_exponent_fit_underdetermined: n_envelope_points=4 (<8) "
              "-> FAIL carries the token",
              r["verdict"] == "FAIL" and "invalid_exponent_fit_underdetermined" in r["tokens"])

        # -- invalid_class_by_assertion --
        class_bad = _base("rate", "trajectory-preserving")   # no h_mli_receipt at all
        r = check_receipt(class_bad, root)
        check("VIOLATOR invalid_class_by_assertion: trajectory-preserving lever with no "
              "h_mli_receipt -> FAIL carries the token",
              r["verdict"] == "FAIL" and "invalid_class_by_assertion" in r["tokens"])

        # -- invalid_energy_units_unqualified --
        units_bad = _base("frontier-shift", "trajectory-altering", c0_grid=[0.5, 1.0, 1.5],
                          power_qualifier="unqualified")
        r = check_receipt(units_bad, root)
        check("VIOLATOR invalid_energy_units_unqualified: frontier-shift claim with "
              "power_qualifier=unqualified -> FAIL carries the token",
              r["verdict"] == "FAIL" and "invalid_energy_units_unqualified" in r["tokens"])

        check("all 7 [S] tokens each individually reproduced by a dedicated violator fixture",
              True)   # summary marker; the 7 checks above are the real assertions

        # -- DT-6 interop (self-declared citation) --
        dt6_bad = dict(triage_ok)
        dt6_bad["cited_by_ceff_or_cscale_pass"] = True
        r = check_receipt(dt6_bad, root)
        check("DT-6 interop: cited_by_ceff_or_cscale_pass=true without the DT-6 triple "
              "-> FAIL (structural, no dedicated [S] token per sec6b)",
              r["verdict"] == "FAIL")
        dt6_ok = dict(dt6_bad)
        dt6_ok.update({"signal_per_gpu_hour": 1.2, "equal_wallclock_band": 0.5,
                      "exceeds_band": True})
        r = check_receipt(dt6_ok, root)
        check("DT-6 interop: cited_by_ceff_or_cscale_pass=true WITH the full triple -> PASS",
              r["verdict"] == "PASS")

        # -- run_file / run_all plumbing, including UNEVALUABLE-on-missing-file --
        p_conforming = root / "receipts" / "conforming.json"
        p_conforming.parent.mkdir(parents=True, exist_ok=True)
        p_conforming.write_text(json.dumps(rate_ok), encoding="utf-8")
        exit_code = run_file(str(p_conforming), repo_root=root)
        check("run_file: conforming receipt on disk -> exit 0", exit_code == 0)

        exit_code_missing = run_file(str(root / "does-not-exist.json"), repo_root=root)
        check("run_file: missing file -> UNEVALUABLE, exit nonzero", exit_code_missing != 0)

        # a receipt that CITES the doc (spec_ref) but is not claim-shaped -- run_all
        # must report it as UNEVALUABLE, never crash, never fake a PASS
        p_citing_only = root / "receipts" / "citing-only.json"
        p_citing_only.write_text(json.dumps(
            {"ticket": "X", "ts": "y", "spec_ref": "docs/spec/energy-law-theory-v1.md sec1"}),
            encoding="utf-8")
        exit_code_all = run_all(receipts_dir=root / "receipts", repo_root=root)
        check("run_all: report-only mode always exits 0 even with FAIL/UNEVALUABLE findings",
              exit_code_all == 0)

        # -- recursive scan: --all must reach SUBDIRECTORY receipts (the exact gap the
        #    old top-level-only glob had -- receipts/ember-c-scale/ and every other
        #    subdirectory in the real tree was invisible to it) --
        found_top = _iter_receipt_files(root / "receipts")
        check("_iter_receipt_files: finds the existing top-level receipt",
              p_conforming in found_top)

        nested_dir = root / "receipts" / "ember-c-scale-fixture"
        nested_dir.mkdir(parents=True, exist_ok=True)
        nested_conforming = nested_dir / "nested-conforming.json"
        nested_payload = dict(rate_ok)
        nested_payload["spec_ref"] = "docs/spec/energy-law-theory-v1.md sec6b"
        nested_conforming.write_text(json.dumps(nested_payload), encoding="utf-8")

        found_nested = _iter_receipt_files(root / "receipts")
        check("_iter_receipt_files: recursive glob reaches a SUBDIRECTORY receipt "
              "(this is the precise bug class the fix closes)",
              nested_conforming in found_nested)

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            exit_code_all2 = run_all(receipts_dir=root / "receipts", repo_root=root)
        out = buf.getvalue()
        check("run_all: exits 0 with a subdirectory receipt present", exit_code_all2 == 0)
        check("run_all: subdirectory receipt is scanned+evaluated, not silently skipped "
              "(a conforming receipt one level down comes back PASS, matching a top-level one)",
              f"{'PASS':12s} nested-conforming.json" in out)

    print(f"\nselftest: {'ALL PASS' if not failures else f'{len(failures)} FAILED'}")
    for f in failures:
        print(f"  FAILED: {f}")
    return 0 if not failures else 1


def main():
    ap = argparse.ArgumentParser(
        description="check_energy_law_theory.py — energy-law-theory-v1.md sec6b receipt-shape checker")
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--file", metavar="PATH", help="fail-closed check on a single receipt")
    group.add_argument("--all", action="store_true",
                       help="report-only scan of receipts/ for any receipt citing "
                            "'energy-law-theory'")
    group.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        sys.exit(_selftest())
    if args.file:
        sys.exit(run_file(args.file))
    sys.exit(run_all())


if __name__ == "__main__":
    main()
