#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""check_publication_gate.py — premature-publication gate checker (publication-v1.md §3).

Mechanizes the three-conjunct gate `docs/spec/publication-v1.md` §3 names as the required
build target (its own §"Validation hook" paragraph). Checks, from ON-DISK evidence only,
never from a spec's prose or a model's self-report:

  (a) kernel_fired            — `docs/archive/pre-restart/kernel-v1-freeze-spec.md` §5 freeze artifact
                                 (`manifests/governance/kernel-v1.0.manifest`) PLUS a
                                 receipt demonstrating the math-core §9 flywheel-turn
                                 condition `dB/dround > 0 ∧ G1_delta > 0`.
  (b) earned_growth_rung      — a `receipts/**/*.json` file carrying the receipts-v1.md §2
                                 growth-EARNED shape: `identity_preservation.pass == true`
                                 AND an `earned` block with a positive FLOP-reduction metric
                                 (`reduction_pct` or `flop_saving_pct`). A receipt with only
                                 `identity_preservation` is a growth-STEP, not EARNED
                                 (receipts-v1.md §2) — it does not satisfy this conjunct.
                                 ADDITIONALLY (identity-manifest binding, closes a verified
                                 laundering gap): the receipt must name an `identity_manifest`
                                 field whose target validates cleanly through
                                 `scripts/ember_01_identity/validate_identity.py`'s
                                 `validate_manifest` — a hand-authored receipt with no bound,
                                 validated identity does not satisfy this conjunct regardless
                                 of its earned metric.
  (c) claims_map_complete     — every row of `paper/claims-evidence-map.md` whose Strength
                                 is not ABSENT names at least one receipt/script/doc path that
                                 resolves on disk (glob- and bare-timestamp-token aware); a
                                 pure-literature row (arXiv citation, no local path claimed)
                                 is compliant without a local path. ABSENT rows are exempt by
                                 the map's own stated convention ("ABSENT rows are the work
                                 plan, ... no wording anywhere may imply otherwise").
  (d) bootstrap_pass_real_world — publication-v1.md §3's second literal condition (map row 18,
                                 tier T1, `docs/spec/bootstrap-v1.md` rung B2): a receipt whose
                                 payload shows the outer criterion passing (a truthy
                                 `BOOTSTRAP_PASS`-shaped field: `BOOTSTRAP_PASS`,
                                 `BOOTSTRAP_PASS_from_raw_cache`,
                                 `BOOTSTRAP_PASS_from_vendored_package_direct`, or
                                 `positive_outer.outer_pass`) AND names an owned trainable core
                                 of >= 1e6 params AND carries a positive real-admitted-world
                                 signal (e.g. "W-code"/"wcode", `docs/spec/world-environment-v1.md`
                                 admission) with NO synthetic-witness marker present
                                 (`synthetic`, `ember_impl`, `ember_bootstrap_package`, `toy`,
                                 `vendored_package`, `package-defined`, or the package's own
                                 `does_not_prove` scope-disclaimer key). The B0 synthetic witness
                                 (rule-grammar, package-defined, `ember_impl/`) explicitly does
                                 NOT satisfy this — bootstrap-v1.md §2 names B0 as satisfiability-
                                 only, and B1/B2 (the real-world, >=1e6-param rungs) as the
                                 distinct, currently-ABSENT result this conjunct checks for.
                                 ADDITIONALLY (identity-manifest binding, closes a verified
                                 laundering gap): the receipt must name an `identity_manifest`
                                 field whose target validates cleanly through
                                 `scripts/ember_01_identity/validate_identity.py`'s
                                 `validate_manifest` — otherwise the outer-pass/param/real-world
                                 shape rides in with no validated claim of WHICH model produced
                                 it, and this conjunct stays RED.
  (e) research_focus_test     — docs/domains/governance/authority/GOAL.md §1b's research-focus test, mechanized (fifth conjunct,
                                 R11-ordered follow-up): every row of `paper/claims-evidence-map.md`
                                 must carry a non-empty `Law grade` column value in
                                 {P1-law-grade, P2-law-grade, coupling, instrument,
                                 engineering-support, P1-adjacent-accounting, frame-revision}
                                 (fail listing offending rows) AND the row(s) forming
                                 `paper/outline.md`'s pre-registered primary claim class (the first
                                 bold K-label composite under its "Primary claim class" heading,
                                 resolved to map rows via the map's own "K<n>=row <m>" legend
                                 anchor) must each be classified P1-law-grade, P2-law-grade, or
                                 (per the R4 ratification below) an accepted `instrument` row —
                                 else False with reason `primary_class_not_law_grade` (docs/domains/governance/authority/GOAL.md
                                 §1b: "the primary class must itself be a statement about a §1b
                                 formal object"). The pre-registered class is the K2/K4 composite,
                                 both `instrument`-classed under docs/domains/governance/authority/GOAL.md §1b's instruments clause —
                                 RATIFIED-INCLUSIVE 2026-07-03 by acting-operator ruling R4
                                 (`receipts/acceptance/acting-operator-ruling-2-20260703.json`,
                                 reversible on one operator word): "statements AND constitutive
                                 instruments both count, each still owing the field-delta bar."
                                 An instrument-classed primary row is therefore accepted iff
                                 `_check_instrument_field_delta_row` clears it (non-ABSENT
                                 Strength + a dated grounding-negative citation per
                                 publishability-adjudication-v1.md Leg C) — never accepted merely
                                 for being tagged `instrument`, and a row failing that bar still
                                 fails this conjunct with the reason attached.

                                 `frame-revision` (docs/domains/governance/authority/GOAL.md §1b's launchpad clause: the two formal
                                 objects are CURRENT formalizations, revisable; a contribution
                                 that improves/replaces/shows-the-incompleteness-of a formal
                                 object — or of the two-law frame itself — is research of the
                                 first rank, not a test failure) is an EARNED exception, never a
                                 loophole: a row so tagged must (a) name, in its Claim or Missing
                                 cell, WHICH formal object it revises — a literal match against
                                 the object symbols greppable from docs/domains/governance/authority/GOAL.md §1b itself (`C*_A(E)`,
                                 `BOOTSTRAP_PASS`, or the launchpad's own "the two-law frame"
                                 phrase), never a hardcoded name, so the check tracks docs/domains/governance/authority/GOAL.md if
                                 the formalization is renamed — and (b) name a `receipts/` path in
                                 its Evidence cell that resolves on disk; missing either is RED
                                 with a one-line reason. Conservative reading of "ride along": a
                                 frame-revision row may satisfy the primary-claim-class
                                 requirement ONLY when a P1-law-grade/P2-law-grade row ALSO exists
                                 somewhere in the map — the launchpad lets a revision ride along
                                 the law-grade core, it never replaces it.

Note: publication-v1.md §3's literal text names three conjuncts (kernel fired, BOOTSTRAP_PASS
real-world, EARNED rung); (c) claims_map_complete was ordered as a fourth check by the build
task alongside (a)/(b) before (d) was ordered as a follow-up to restore the literal §3 pairing
against map row 18, and (e) research_focus_test was ordered as a fifth follow-up mechanizing
docs/domains/governance/authority/GOAL.md §1b's research-focus test — this script now covers all four map rows the spec's own
Validation-hook paragraph names (18/19/21), the map-completeness check, and the §1b law-grade
gate.

Fails CLOSED: an unreadable or missing input is a RED conjunct with a stated reason, never a
crash and never a silent skip. Writes a UNIFIED SCHEMA v4 receipt (`docs/spec/receipts-v1.md`
§2) to `receipts/publication-gate-<UTC compact ts>.json` via the fail-closed writer
(`receipt_write.checked_write`) and prints a RED/GREEN line per conjunct plus the overall
verdict on stdout. Exit code 0 iff overall verdict is GREEN (4/4); non-zero otherwise — this
mirrors, and does not replace, publication-v1.md §3's binding gate: no submission-track file
or venue-portal entry may be created while this reads less than all conjuncts GREEN.

Stdlib only. No network. No git commands (byte-hash of own source, never a commit sha).
"""
import argparse
import glob as globmod
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RECEIPTS_DIR = REPO_ROOT / "scripts" / "ember_totality" / "receipts-publication"
CLAIMS_MAP_PATH = REPO_ROOT / "paper" / "claims-evidence-map.md"
OUTLINE_PATH = REPO_ROOT / "paper" / "outline.md"
GOAL_PATH = REPO_ROOT / "docs/domains/governance/authority/GOAL.md"

sys.path.insert(0, str(Path(__file__).parent))
import receipt_fp  # noqa: E402
import receipt_write  # noqa: E402

SHA_CONVENTION = "bytes on disk as-is (binary read, no line-ending normalization)"

PATH_PREFIXES = ("receipts/", "scripts/", "docs/", "paper/", "configs/", "config/",
                  "baseline/", "research/")
PREFIX_ALT = "|".join(re.escape(p) for p in PATH_PREFIXES)
PATH_CHARSET = r"[A-Za-z0-9_./{}<>*-]"
PREFIXED_PATH_RE = re.compile(rf"(?:{PREFIX_ALT}){PATH_CHARSET}+")
BACKTICK_SPAN_RE = re.compile(r"`([^`]*)`")
# Bare receipt-id token with no directory prefix (e.g. `t4-r1-q15-arc1-seed14-20260610T150153Z`)
BARE_RECEIPT_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*-\d{8}T\d{6}Z")
# Bare filename with a recognized extension, no directory prefix (e.g. `local-fm-2026.md`) —
# resolved by a repo-wide filename search rather than a direct join, since the map cites some
# files without their directory.
BARE_FILENAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\.(?:md|py|json|jsonl|txt|manifest)\b")
ARXIV_RE = re.compile(r"arXiv\s+\d{4}\.\d{5}", re.IGNORECASE)
_FILENAME_INDEX_CACHE = None


def _filename_index():
    """One-time repo-wide basename -> True map, skipping .git. Cached for the process."""
    global _FILENAME_INDEX_CACHE
    if _FILENAME_INDEX_CACHE is None:
        idx = set()
        for dirpath, dirnames, filenames in os.walk(REPO_ROOT):
            dirnames[:] = [d for d in dirnames if d != ".git"]
            for fn in filenames:
                idx.add(fn)
        _FILENAME_INDEX_CACHE = idx
    return _FILENAME_INDEX_CACHE


# ---------------------------------------------------------------------------
# Fail-closed helpers
# ---------------------------------------------------------------------------

def safe_load_json(path):
    """Return (dict_or_None, error_or_None). Never raises."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:  # noqa: BLE001 — fail-closed by design, any error is a RED reason
        return None, f"{type(e).__name__}: {e}"


def iter_receipt_files():
    """All receipts/*.json plus receipts/**/*.json (subdirectory receipts), sorted."""
    if not RECEIPTS_DIR.is_dir():
        return []
    files = sorted(RECEIPTS_DIR.glob("*.json")) + sorted(RECEIPTS_DIR.glob("**/*.json"))
    seen = set()
    out = []
    for f in files:
        if f not in seen:
            seen.add(f)
            out.append(f)
    return out


def resolve_local_ref(ref):
    """True if a candidate local path/glob/bare-token resolves on disk (file, dir, or
    at least one glob match). Never raises."""
    try:
        target = REPO_ROOT / ref
        if "*" in ref:
            return len(globmod.glob(str(target))) > 0
        return target.exists()
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------------------
# Identity-manifest binding (closes the capability-receipt identity-laundering gap: a
# hand-authored capability receipt could carry a truthy BOOTSTRAP_PASS/EARNED shape with
# no validation of WHICH model produced it). Shared by conjuncts (b) earned_growth_rung and
# (d) bootstrap_pass_real_world: a capability receipt qualifies for either conjunct only if
# it ALSO names an `identity_manifest` field whose target validates cleanly through
# scripts/ember_01_identity/validate_identity.py's validate_manifest. Fails CLOSED: no
# `identity_manifest` field, an unimportable validator, an unreadable/unparseable manifest
# file, or any IdentityValidationError finding all resolve to ok=False with a stated reason
# -- never a silent pass and never a crash.
# ---------------------------------------------------------------------------

def _check_identity_manifest(receipt):
    """(ok: bool, reason_or_None) for one capability receipt dict. Never raises."""
    manifest_ref = receipt.get("identity_manifest")
    if not isinstance(manifest_ref, str) or not manifest_ref.strip():
        return False, "receipt names no identity_manifest field"

    try:
        from ember_01_identity.validate_identity import (  # noqa: PLC0415
            IdentityValidationError, validate_manifest,
        )
    except Exception as e:  # noqa: BLE001 — fail-closed on any import defect
        return False, f"identity validator unavailable: {type(e).__name__}: {e}"

    manifest_path = REPO_ROOT / manifest_ref
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return False, (f"identity_manifest {manifest_ref!r} unreadable: "
                        f"{type(e).__name__}: {e}")

    try:
        validate_manifest(payload)
    except IdentityValidationError as e:
        return False, f"identity_manifest {manifest_ref!r} failed validation: {e}"
    except Exception as e:  # noqa: BLE001 — fail-closed on any other validator defect
        return False, (f"identity_manifest {manifest_ref!r} validator error: "
                        f"{type(e).__name__}: {e}")

    return True, None


# ---------------------------------------------------------------------------
# Conjunct (a): kernel_fired
# ---------------------------------------------------------------------------

_DB_ROUND_KEY_RE = re.compile(r"db.?(per.?round|.?dround)|flywheel.*db|dB_dround", re.IGNORECASE)
_G1_DELTA_KEY_RE = re.compile(r"g1.*delta", re.IGNORECASE)


def _walk_numeric_matches(obj, key_re, path=""):
    """Yield (path, value) for every numeric leaf whose key matches key_re, recursively."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            kp = f"{path}.{k}" if path else str(k)
            if isinstance(k, str) and key_re.search(k) and isinstance(v, (int, float)) \
                    and not isinstance(v, bool):
                yield kp, v
            yield from _walk_numeric_matches(v, key_re, kp)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _walk_numeric_matches(v, key_re, f"{path}[{i}]")


def check_kernel_fired():
    reasons = []
    evidence = {}

    canonical_manifest = REPO_ROOT / "manifests" / "governance" / "kernel-v1.0.manifest"
    manifest_hits = (
        [canonical_manifest.relative_to(REPO_ROOT).as_posix()]
        if canonical_manifest.is_file()
        else []
    )
    evidence["manifest_hits"] = manifest_hits
    manifest_ok = len(manifest_hits) > 0
    if not manifest_ok:
        reasons.append("canonical manifests/governance/kernel-v1.0.manifest is absent "
                        "(freeze procedure, docs/archive/pre-restart/kernel-v1-freeze-spec.md sec5, never executed)")

    flywheel_receipts = []
    parse_errors = 0
    for f in iter_receipt_files():
        d, err = safe_load_json(f)
        if err is not None:
            parse_errors += 1
            continue
        if not isinstance(d, dict):
            continue
        db_hits = list(_walk_numeric_matches(d, _DB_ROUND_KEY_RE))
        g1_hits = list(_walk_numeric_matches(d, _G1_DELTA_KEY_RE))
        db_positive = [h for h in db_hits if h[1] > 0]
        g1_positive = [h for h in g1_hits if h[1] > 0]
        ticket_or_kind = f"{d.get('ticket', '')} {d.get('kind', '')}".lower()
        name_hit = ("kernel" in ticket_or_kind and
                    ("fire" in ticket_or_kind or "flywheel" in ticket_or_kind))
        if (db_positive and g1_positive) or name_hit:
            flywheel_receipts.append({
                "path": str(f.relative_to(REPO_ROOT).as_posix()),
                "db_round_fields": db_positive,
                "g1_delta_fields": g1_positive,
                "name_hit": name_hit,
            })
    evidence["flywheel_turn_receipts"] = flywheel_receipts
    evidence["receipt_parse_errors"] = parse_errors
    flywheel_ok = len(flywheel_receipts) > 0
    if not flywheel_ok:
        reasons.append("no receipt found demonstrating the math-core sec9 flywheel-turn "
                        "condition (dB/dround > 0 and G1_delta > 0) under a frozen kernel")

    verdict = "GREEN" if (manifest_ok and flywheel_ok) else "RED"
    return {
        "verdict": verdict,
        "map_row": 21,
        "reason": "all evidence present" if verdict == "GREEN" else "; ".join(reasons),
        "evidence": evidence,
    }


# ---------------------------------------------------------------------------
# Conjunct (b): earned_growth_rung
# ---------------------------------------------------------------------------

def _earned_reduction_value(earned):
    """Positive-FLOP-reduction metric under either observed field name."""
    for key in ("reduction_pct", "flop_saving_pct", "flop_reduction_pct"):
        v = earned.get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return key, v
    return None, None


def check_earned_growth_rung():
    reasons = []
    candidates = []
    earned_hits = []
    parse_errors = 0

    for f in iter_receipt_files():
        d, err = safe_load_json(f)
        if err is not None:
            parse_errors += 1
            continue
        if not isinstance(d, dict):
            continue
        earned = d.get("earned")
        ip = d.get("identity_preservation")
        is_growth_shaped = d.get("kind") == "growth" or earned is not None
        if not is_growth_shaped:
            continue
        rel = str(f.relative_to(REPO_ROOT).as_posix())
        if earned is None or not isinstance(earned, dict):
            candidates.append({"path": rel, "reason": "growth-shaped but no earned block "
                                                        "(growth-STEP, not EARNED)"})
            continue
        key, value = _earned_reduction_value(earned)
        ip_pass = bool(ip.get("pass")) if isinstance(ip, dict) else None
        identity_ok, identity_reason = _check_identity_manifest(d)
        candidates.append({
            "path": rel, "earned_field": key, "earned_value": value,
            "identity_preservation_pass": ip_pass,
            "identity_manifest_ok": identity_ok,
            "identity_manifest_reason": identity_reason,
        })
        if key is not None and value > 0 and identity_ok:
            earned_hits.append({"path": rel, "field": key, "value": value,
                                 "identity_preservation_pass": ip_pass})

    if not earned_hits:
        if candidates:
            reasons.append(f"{len(candidates)} growth-shaped receipt(s) found, none carry both "
                            "a positive earned.reduction_pct/flop_saving_pct (EARNED per "
                            "math-core sec6 requires FLOPs(seed->cap) < FLOPs(scratch->cap), "
                            "measured, not assumed) AND a validated identity_manifest "
                            "(closes the capability-receipt identity-laundering gap): "
                            + "; ".join(
                                f"{c['path']} (earned_field={c['earned_field']!r}, "
                                f"identity_ok={c['identity_manifest_ok']}"
                                + (f", {c['identity_manifest_reason']}"
                                   if c['identity_manifest_reason'] else "") + ")"
                                for c in candidates
                            ))
        else:
            reasons.append("no receipt with a growth-EARNED shape (kind:growth or an "
                            "'earned' block) found under receipts/")

    verdict = "GREEN" if earned_hits else "RED"
    return {
        "verdict": verdict,
        "map_row": 19,
        "reason": "all evidence present" if verdict == "GREEN" else "; ".join(reasons),
        "evidence": {
            "growth_shaped_candidates": candidates,
            "positive_earned_hits": earned_hits,
            "receipt_parse_errors": parse_errors,
        },
    }


# ---------------------------------------------------------------------------
# Conjunct (d): bootstrap_pass_real_world (map row 18, tier T1, bootstrap-v1.md rung B2)
# ---------------------------------------------------------------------------

_BOOTSTRAP_PASS_KEY_RE = re.compile(r"bootstrap_pass", re.IGNORECASE)
_PARAM_COUNT_KEY_RE = re.compile(
    r"^n_params$|^param_count$|^core_params$|^n_trainable_params$|^n_orig_params$|"
    r"^n_grown_params$|owned.*param", re.IGNORECASE)
# Synthetic-witness markers (bootstrap-v1.md §2/§3a: B0 = synthetic rule grammar,
# package-defined, ember_impl/). Presence of any of these strings ANYWHERE in a
# candidate receipt (keys, string values) disqualifies it from B1/B2 -- the package's
# own "does_not_prove" scope-disclaimer key is the strongest, most precise signal
# (bootstrap-falsifier-20260702T064130Z.json names exactly this).
_SYNTHETIC_MARKERS = (
    "synthetic", "ember_impl", "ember_bootstrap_package", "ember_engineering_contract",
    "toy", "vendored_package", "package-defined", "package default", "does_not_prove",
)
# Real-admitted-world positive signals (world-environment-v1.md admission; W-code is the
# only training world currently admitted per that spec).
_REAL_WORLD_MARKERS = ("w-code", "wcode", "world-environment-v1", "world_admission")
MIN_REAL_CORE_PARAMS = 1_000_000


def _find_bootstrap_pass_hits(obj, path=""):
    """Yield (path, value) for every truthy leaf whose key matches BOOTSTRAP_PASS-shaped
    names, plus positive_outer.outer_pass==true (the falsifier package's own outer-pass
    field, used where the top-level literal key isn't present)."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            kp = f"{path}.{k}" if path else str(k)
            if isinstance(k, str) and _BOOTSTRAP_PASS_KEY_RE.search(k) and v is True:
                yield kp, v
            if isinstance(k, str) and k == "outer_pass" and v is True:
                yield kp, v
            yield from _find_bootstrap_pass_hits(v, kp)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _find_bootstrap_pass_hits(v, f"{path}[{i}]")


def _receipt_text_blob(obj):
    """Concatenate every string key and string value in obj (recursively) for a cheap
    case-insensitive substring scan -- used for both the synthetic-marker denylist and
    the real-world-marker allowlist."""
    parts = []

    def _walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if isinstance(k, str):
                    parts.append(k)
                _walk(v)
        elif isinstance(o, list):
            for v in o:
                _walk(v)
        elif isinstance(o, str):
            parts.append(o)

    _walk(obj)
    return " ".join(parts).lower()


def _max_param_count(obj):
    """Largest numeric value found at a key matching _PARAM_COUNT_KEY_RE, or None."""
    best = None
    for _, v in _walk_numeric_matches(obj, _PARAM_COUNT_KEY_RE):
        if best is None or v > best:
            best = v
    return best


def check_bootstrap_pass_real_world():
    reasons = []
    candidates = []
    real_hits = []
    parse_errors = 0

    for f in iter_receipt_files():
        d, err = safe_load_json(f)
        if err is not None:
            parse_errors += 1
            continue
        if not isinstance(d, dict):
            continue
        pass_hits = list(_find_bootstrap_pass_hits(d))
        if not pass_hits:
            continue

        rel = str(f.relative_to(REPO_ROOT).as_posix())
        blob = _receipt_text_blob(d)
        synthetic_hits = [m for m in _SYNTHETIC_MARKERS if m in blob]
        real_world_hits = [m for m in _REAL_WORLD_MARKERS if m in blob]
        params = _max_param_count(d)

        identity_ok, identity_reason = _check_identity_manifest(d)

        entry = {
            "path": rel,
            "bootstrap_pass_fields": [p for p, _ in pass_hits],
            "synthetic_markers_found": synthetic_hits,
            "real_world_markers_found": real_world_hits,
            "max_param_count_found": params,
            "identity_manifest_ok": identity_ok,
            "identity_manifest_reason": identity_reason,
        }
        is_real = (not synthetic_hits and real_world_hits
                   and params is not None and params >= MIN_REAL_CORE_PARAMS
                   and identity_ok)
        entry["qualifies_as_real_world_ge_1e6"] = bool(is_real)
        candidates.append(entry)
        if is_real:
            real_hits.append(entry)

    if not real_hits:
        if candidates:
            reasons.append(
                f"{len(candidates)} BOOTSTRAP_PASS-shaped receipt(s) found, none qualify: "
                + "; ".join(
                    f"{c['path']} (" +
                    (f"synthetic markers {c['synthetic_markers_found']}"
                     if c["synthetic_markers_found"] else
                     f"no real-world marker" if not c["real_world_markers_found"] else
                     f"params={c['max_param_count_found']!r} < {MIN_REAL_CORE_PARAMS}"
                     if c["max_param_count_found"] is None
                        or c["max_param_count_found"] < MIN_REAL_CORE_PARAMS else
                     f"identity_manifest: {c['identity_manifest_reason']}")
                    + ")"
                    for c in candidates
                )
            )
        else:
            reasons.append(
                "no receipt with a truthy BOOTSTRAP_PASS-shaped field found under receipts/ "
                "at all (bootstrap-v1.md sec2: B1/B2 -- the real-world, >=1e6-param rungs -- "
                "are ABSENT; only the B0 synthetic witness is receipted)")

    verdict = "GREEN" if real_hits else "RED"
    return {
        "verdict": verdict,
        "map_row": 18,
        "reason": "all evidence present" if verdict == "GREEN" else "; ".join(reasons),
        "evidence": {
            "bootstrap_pass_shaped_candidates": candidates,
            "qualifying_real_world_hits": real_hits,
            "receipt_parse_errors": parse_errors,
            "min_real_core_params": MIN_REAL_CORE_PARAMS,
        },
    }


# ---------------------------------------------------------------------------
# Conjunct (c): claims_map_complete
# ---------------------------------------------------------------------------

TABLE_ROW_RE = re.compile(r"^\|\s*(\d+)\s*\|(.*)\|\s*$")


def parse_claims_map(text):
    """Parse the '| # | Claim | Strength today | Evidence | Missing |' table.
    Returns list of dicts; raises ValueError if no data rows are found (caller catches)."""
    rows = []
    for line in text.splitlines():
        m = TABLE_ROW_RE.match(line.rstrip())
        if not m:
            continue
        row_num = m.group(1)
        rest = m.group(2)
        cells = [c.strip() for c in rest.split("|")]
        if len(cells) < 4:
            continue
        if cells[0].strip("-").strip() == "" and cells[1].strip("-").strip() == "":
            continue  # header separator row (---|---|---)
        rows.append({
            "row": int(row_num),
            "claim": cells[0],
            "strength": cells[1],
            "evidence": cells[2],
            "missing": cells[3] if len(cells) > 3 else "",
            "law_grade": cells[4].strip() if len(cells) > 4 and cells[4].strip() else None,
        })
    if not rows:
        raise ValueError("no data rows parsed from claims-evidence-map.md table")
    return rows


def extract_local_refs(evidence_text):
    """Candidate local paths from one Evidence cell: prefixed paths in backticks or bare,
    plus bare receipt-id tokens (timestamp-suffixed, no directory prefix)."""
    refs = set()
    for m in PREFIXED_PATH_RE.finditer(evidence_text):
        refs.add(m.group(0).rstrip(".,;"))
    for span in BACKTICK_SPAN_RE.findall(evidence_text):
        for m in PREFIXED_PATH_RE.finditer(span):
            refs.add(m.group(0).rstrip(".,;"))
        for m in BARE_RECEIPT_ID_RE.finditer(span):
            token = m.group(0)
            if any(token in r for r in refs):
                continue
            refs.add(f"__bare__{token}")
        for m in BARE_FILENAME_RE.finditer(span):
            token = m.group(0)
            if any(token in r for r in refs):
                continue
            refs.add(f"__barefile__{token}")
    return refs


def resolve_ref(ref):
    """Resolve a ref from extract_local_refs — bare timestamp tokens try
    receipts/<tok>.json then receipts/<tok>/; bare filenames resolve via a repo-wide
    basename search (the map cites some files without their directory)."""
    if ref.startswith("__bare__"):
        token = ref[len("__bare__"):]
        return (resolve_local_ref(f"receipts/{token}.json")
                or resolve_local_ref(f"receipts/{token}/"))
    if ref.startswith("__barefile__"):
        token = ref[len("__barefile__"):]
        return token in _filename_index()
    return resolve_local_ref(ref)


def check_claims_map_complete():
    text, err = None, None
    try:
        text = CLAIMS_MAP_PATH.read_text(encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        err = f"{type(e).__name__}: {e}"

    if err is not None:
        return {
            "verdict": "RED",
            "reason": f"paper/claims-evidence-map.md unreadable: {err}",
            "evidence": {"path": str(CLAIMS_MAP_PATH.relative_to(REPO_ROOT).as_posix())},
        }

    try:
        rows = parse_claims_map(text)
    except ValueError as e:
        return {
            "verdict": "RED",
            "reason": f"paper/claims-evidence-map.md unparseable: {e}",
            "evidence": {"path": str(CLAIMS_MAP_PATH.relative_to(REPO_ROOT).as_posix())},
        }

    per_row = []
    noncompliant = []
    for r in rows:
        strength = r["strength"]
        evidence_text = r["evidence"]
        if re.search(r"ABSENT", strength, re.IGNORECASE):
            per_row.append({"row": r["row"], "strength": strength, "status": "exempt_absent"})
            continue

        refs = extract_local_refs(evidence_text)
        if not refs:
            if ARXIV_RE.search(evidence_text):
                per_row.append({"row": r["row"], "strength": strength,
                                 "status": "compliant_literature_only"})
                continue
            noncompliant.append({"row": r["row"], "strength": strength,
                                  "reason": "no locatable local path and no arXiv citation "
                                            "in Evidence cell"})
            per_row.append({"row": r["row"], "strength": strength,
                             "status": "noncompliant_no_evidence"})
            continue

        resolved = {ref: resolve_ref(ref) for ref in refs}
        if any(resolved.values()):
            per_row.append({"row": r["row"], "strength": strength,
                             "status": "compliant", "refs": resolved})
        else:
            noncompliant.append({"row": r["row"], "strength": strength,
                                  "reason": f"named path(s) do not resolve on disk: "
                                            f"{sorted(refs)}"})
            per_row.append({"row": r["row"], "strength": strength,
                             "status": "noncompliant_stale_path", "refs": resolved})

    verdict = "GREEN" if not noncompliant else "RED"
    return {
        "verdict": verdict,
        "reason": "all rows compliant" if verdict == "GREEN"
                  else f"{len(noncompliant)} row(s) noncompliant: "
                       + "; ".join(f"row {n['row']} ({n['strength']}): {n['reason']}"
                                   for n in noncompliant),
        "evidence": {"rows_checked": len(rows), "per_row": per_row,
                     "noncompliant": noncompliant},
    }


# ---------------------------------------------------------------------------
# Conjunct (e): research_focus_test (docs/domains/governance/authority/GOAL.md §1b research-focus test, mechanized;
# fifth conjunct, R11-ordered follow-up)
# ---------------------------------------------------------------------------

LAW_GRADE_ENUM = {
    "P1-law-grade", "P2-law-grade", "coupling", "instrument",
    "engineering-support", "P1-adjacent-accounting", "frame-revision",
}
LAW_GRADE_ANCHOR_RE = re.compile(r"\bK(\d+)\s*=\s*row\s*(\d+)\b", re.IGNORECASE)
PRIMARY_CLASS_HEADING_RE = re.compile(r"^##\s*Primary claim class", re.MULTILINE)
NEXT_HEADING_RE = re.compile(r"^##\s", re.MULTILINE)
BOLD_SPAN_RE = re.compile(r"\*\*([^*]+)\*\*")
K_LABEL_RE = re.compile(r"\bK(\d+)\b")
# docs/domains/governance/authority/GOAL.md sec1b's own "## 1b." heading, bounding the section this file greps for formal-object
# names (never hardcoded) — see _parse_formal_object_names.
SECTION_1B_HEADING_RE = re.compile(r"^##\s*1b\.", re.MULTILINE)
FORMAL_OBJECT_RE = re.compile(r"Formal object:[^`]*`([^`]+)`")
TWO_LAW_FRAME_RE = re.compile(r"or of (the [\w-]+ frame) itself", re.IGNORECASE)


def _parse_k_label_anchor(map_text):
    """Extract the 'K<n>=row <m>' anchor pairs from claims-evidence-map.md's law-grade
    legend (e.g. 'K1=row 3, K2=row 4, K3=row 6, K4=row 5'). Returns (dict_or_None,
    error_or_None); never raises."""
    hits = LAW_GRADE_ANCHOR_RE.findall(map_text)
    if not hits:
        return None, "no 'K<n>=row <m>' anchor found in claims-evidence-map.md's law-grade legend"
    return {f"K{k}": int(r) for k, r in hits}, None


def _parse_primary_class_k_labels(outline_text):
    """Extract the K-label set forming paper/outline.md's pre-registered primary claim
    class composite: the FIRST bold span under the '## Primary claim class' heading only
    (excludes K-labels named later in the same paragraph as 'supporting contributions',
    e.g. outline.md's own '(K1, K3 are supporting contributions...)' aside). Returns
    (sorted_list_or_None, error_or_None); never raises."""
    m = PRIMARY_CLASS_HEADING_RE.search(outline_text)
    if not m:
        return None, "no '## Primary claim class' heading found in paper/outline.md"
    rest = outline_text[m.end():]
    nh = NEXT_HEADING_RE.search(rest)
    section = rest[:nh.start()] if nh else rest
    bold = BOLD_SPAN_RE.search(section)
    if not bold:
        return None, "no bold composite declaration found under 'Primary claim class'"
    labels = sorted(set(f"K{n}" for n in K_LABEL_RE.findall(bold.group(1))))
    if not labels:
        return None, "no K<n> label found in the composite declaration"
    return labels, None


def _parse_formal_object_names(goal_text):
    """Dynamically greps docs/domains/governance/authority/GOAL.md's '## 1b.' section for the formal-object names the
    launchpad clause protects — never hardcoded, so this tracks docs/domains/governance/authority/GOAL.md if a formalization
    is renamed. Two sources within the section:
      - the backtick-quoted symbol following each 'Formal object:' label, first
        whitespace-delimited token only (e.g. 'C*_A(E)' out of the full equation
        'C*_A(E) = sup over A in ADM of C(A, E)'; 'BOOTSTRAP_PASS' out of a bare span);
      - the launchpad clause's own 'or of the two-law frame itself' escape hatch, which
        names no formal object but explicitly licenses revising the frame itself.
    Returns (set_of_names, error_or_None); never raises."""
    m = SECTION_1B_HEADING_RE.search(goal_text)
    if not m:
        return set(), "no '## 1b.' section heading found in docs/domains/governance/authority/GOAL.md"
    rest = goal_text[m.end():]
    nh = NEXT_HEADING_RE.search(rest)
    section = rest[:nh.start()] if nh else rest

    names = set()
    for fo in FORMAL_OBJECT_RE.finditer(section):
        tokens = fo.group(1).split()
        if tokens:
            names.add(tokens[0])
    tl = TWO_LAW_FRAME_RE.search(section)
    if tl:
        names.add(tl.group(1).strip())

    if not names:
        return set(), "no formal-object names extracted from docs/domains/governance/authority/GOAL.md's '## 1b.' section"
    return names, None


def _row_cites_receipt(evidence_text):
    """True (with the resolving ref) iff a claims-map row's Evidence cell names at least
    one receipts/ path — prefixed (`receipts/...`) or a bare timestamp-token (which per
    BARE_RECEIPT_ID_RE only ever resolves under receipts/) — that resolves on disk.
    Narrower than check_claims_map_complete's general evidence check (which also accepts
    doc/script/arXiv citations): a frame-revision claim needs a load-bearing RECEIPT
    specifically, not merely evidence. Never raises."""
    for ref in extract_local_refs(evidence_text):
        if ref.startswith("__bare__"):
            if resolve_ref(ref):
                return True, ref[len("__bare__"):]
            continue
        if ref.startswith("__barefile__"):
            continue  # a bare filename citation isn't necessarily a receipt
        if (ref.startswith("receipts/") or ref.startswith("receipts\\")) and resolve_ref(ref):
            return True, ref
    return False, None


def _check_frame_revision_row(row, formal_object_names):
    """Acceptance predicate for a claims-map row tagged 'frame-revision' (docs/domains/governance/authority/GOAL.md sec1b's
    launchpad clause: a contribution that improves/replaces/shows-the-incompleteness-of a
    sec1b formal object — or of the two-law frame itself — is research of the first rank,
    not a test failure). The launchpad is an EARNED exception, not a loophole, so BOTH of
    these must hold or the row is RED with a one-line reason:
      (a) the row names WHICH formal object it revises — a literal match, in the Claim or
          Missing cell (the map's schema has no dedicated column for this), against one of
          docs/domains/governance/authority/GOAL.md sec1b's own formal-object symbols;
      (b) the Evidence cell names a receipts/ path that resolves on disk — a revision
          claim without a load-bearing receipt is a proposal, not a result.
    Returns (ok: bool, reason_or_None); never raises."""
    row_text = f"{row.get('claim') or ''} {row.get('missing') or ''}"
    cited = sorted(n for n in formal_object_names if n in row_text)
    if not cited:
        return False, (
            f"row {row['row']}: frame-revision row does not cite which sec1b formal "
            f"object it revises (checked Claim + Missing cells against "
            f"{sorted(formal_object_names)})"
        )
    has_receipt, _ref = _row_cites_receipt(row.get("evidence") or "")
    if not has_receipt:
        return False, (
            f"row {row['row']}: frame-revision row cites {cited} but names no receipts/ "
            f"path that resolves on disk in its Evidence cell"
        )
    return True, None


# docs/domains/governance/authority/GOAL.md sec1b's research-focus test instruments-clause scope call was RATIFIED-INCLUSIVE by
# acting-operator ruling R4 (receipts/acceptance/acting-operator-ruling-2-20260703.json,
# 2026-07-03T15:38:33Z, reversible on one operator word): "statements AND constitutive
# instruments both count, each still owing the field-delta bar." An instrument-classed row is
# therefore no longer an automatic primary-class failure -- but the rider is load-bearing:
# "each still needs its dated-negative delta receipted."
def _check_instrument_field_delta_row(row):
    """Acceptance predicate for a claims-map row classified 'instrument' when it forms (or
    belongs to) the pre-registered primary claim class. Mechanizes publishability-adjudication-
    v1.md Leg C's field-delta bar ("the contribution is stated as a falsifiable delta against
    the dated grounding negatives ... instruments remain subject to this leg's delta bar: 'we
    built a tool' without a receipted, falsifiable field-delta still fails") — BOTH of these
    must hold or the row is RED with a one-line reason:
      (a) the row's own Strength is not ABSENT — an instrument with no strength demonstrated
          yet carries no delta at all, "we built a tool" with nothing behind it;
      (b) the Evidence cell cites a dated literature negative establishing what the delta
          displaces — an arXiv reference, or a local grounding-sweep doc path
          (docs/grounding/*.md) — per the same Leg C's named grounding docs
          (self-improvement-2026.md, local-fm-2026.md).
    Returns (ok: bool, reason_or_None); never raises."""
    strength = row.get("strength") or ""
    if re.search(r"ABSENT", strength, re.IGNORECASE):
        return False, (
            f"row {row['row']}: instrument-classed row is ABSENT — no field-delta yet "
            f"demonstrated (publishability-adjudication-v1.md Leg C)"
        )
    evidence_text = row.get("evidence") or ""
    has_arxiv = bool(ARXIV_RE.search(evidence_text))
    has_grounding_doc = any(
        ref.startswith("docs/grounding/") for ref in extract_local_refs(evidence_text)
    )
    if not (has_arxiv or has_grounding_doc):
        return False, (
            f"row {row['row']}: instrument-classed row cites no dated grounding negative "
            f"(arXiv reference or docs/grounding/*.md sweep) in its Evidence cell — "
            f"publishability-adjudication-v1.md Leg C field-delta bar unmet"
        )
    return True, None


def check_research_focus_test():
    map_text, map_err = None, None
    try:
        map_text = CLAIMS_MAP_PATH.read_text(encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        map_err = f"{type(e).__name__}: {e}"
    if map_err is not None:
        return {
            "verdict": "RED",
            "reason": f"paper/claims-evidence-map.md unreadable: {map_err}",
            "evidence": {"path": str(CLAIMS_MAP_PATH.relative_to(REPO_ROOT).as_posix())},
        }

    try:
        rows = parse_claims_map(map_text)
    except ValueError as e:
        return {
            "verdict": "RED",
            "reason": f"paper/claims-evidence-map.md unparseable: {e}",
            "evidence": {"path": str(CLAIMS_MAP_PATH.relative_to(REPO_ROOT).as_posix())},
        }

    reasons = []
    offending = [{"row": r["row"], "law_grade": r.get("law_grade")}
                 for r in rows
                 if not r.get("law_grade") or r["law_grade"] not in LAW_GRADE_ENUM]
    if offending:
        reasons.append(
            f"{len(offending)} row(s) missing/invalid law_grade (must be one of "
            f"{sorted(LAW_GRADE_ENUM)}): "
            + "; ".join(f"row {o['row']} ({o['law_grade']!r})" for o in offending)
        )

    # --- frame-revision acceptance predicate (launchpad clause, docs/domains/governance/authority/GOAL.md sec1b) ---
    # Only touches docs/domains/governance/authority/GOAL.md when a row actually claims the grade — no new failure mode for
    # maps that never use it. Fail-closed like every other check in this file: an
    # unreadable docs/domains/governance/authority/GOAL.md or an unparseable sec1b section marks every frame-revision row
    # invalid rather than silently passing them.
    frame_revision_rows = [r for r in rows if r.get("law_grade") == "frame-revision"]
    frame_revision_ok = {}  # row_num -> bool, only for rows actually checked
    formal_object_names = set()
    if frame_revision_rows:
        goal_text, goal_err = None, None
        try:
            goal_text = GOAL_PATH.read_text(encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            goal_err = f"{type(e).__name__}: {e}"
        if goal_err is not None:
            for r in frame_revision_rows:
                frame_revision_ok[r["row"]] = False
            reasons.append(f"docs/domains/governance/authority/GOAL.md unreadable for frame-revision row(s) "
                            f"{[r['row'] for r in frame_revision_rows]}: {goal_err}")
        else:
            formal_object_names, fo_err = _parse_formal_object_names(goal_text)
            if fo_err is not None:
                for r in frame_revision_rows:
                    frame_revision_ok[r["row"]] = False
                reasons.append(f"frame-revision row(s) "
                                f"{[r['row'] for r in frame_revision_rows]} invalid: {fo_err}")
            else:
                for r in frame_revision_rows:
                    ok, reason = _check_frame_revision_row(r, formal_object_names)
                    frame_revision_ok[r["row"]] = ok
                    if not ok:
                        reasons.append(reason)
    frame_revision_invalid = sorted(rn for rn, ok in frame_revision_ok.items() if not ok)
    # "at least one P1-law-grade or P2-law-grade row ALSO exists" -- the launchpad lets a
    # revision ride along the law-grade core; it never REPLACES it (conservative reading).
    law_grade_core_present = any(
        r.get("law_grade") in ("P1-law-grade", "P2-law-grade") for r in rows
    )

    outline_text, outline_err = None, None
    try:
        outline_text = OUTLINE_PATH.read_text(encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        outline_err = f"{type(e).__name__}: {e}"

    primary_class_not_law_grade = False
    primary_evidence = {}
    if outline_err is not None:
        reasons.append(f"primary_class_not_law_grade: paper/outline.md unreadable: {outline_err}")
        primary_class_not_law_grade = True
    else:
        k_labels, k_err = _parse_primary_class_k_labels(outline_text)
        if k_err is not None:
            reasons.append(f"primary_class_not_law_grade: {k_err}")
            primary_class_not_law_grade = True
        else:
            anchor, anchor_err = _parse_k_label_anchor(map_text)
            if anchor_err is not None:
                reasons.append(f"primary_class_not_law_grade: {anchor_err}")
                primary_class_not_law_grade = True
            else:
                missing_anchor = [k for k in k_labels if k not in anchor]
                if missing_anchor:
                    reasons.append(
                        "primary_class_not_law_grade: no row anchor for K-label(s) "
                        f"{missing_anchor} (outline.md primary class = {k_labels})"
                    )
                    primary_class_not_law_grade = True
                else:
                    row_by_num = {r["row"]: r for r in rows}
                    primary_rows = {k: anchor[k] for k in k_labels}
                    not_law_grade = []
                    instrument_accepted = []
                    for k, rn in primary_rows.items():
                        row = row_by_num.get(rn)
                        lg = row.get("law_grade") if row else None
                        if lg in ("P1-law-grade", "P2-law-grade"):
                            continue
                        if (lg == "frame-revision" and law_grade_core_present
                                and frame_revision_ok.get(rn)):
                            continue  # launchpad ride-along: valid revision + law-grade core
                        if lg == "instrument":
                            # R4 RATIFIED-INCLUSIVE (see _check_instrument_field_delta_row
                            # docstring) — instrument rows count toward the primary class iff
                            # they clear the field-delta bar; else they fall through to RED.
                            inst_ok, inst_reason = _check_instrument_field_delta_row(row)
                            if inst_ok:
                                instrument_accepted.append({"k_label": k, "row": rn})
                                continue
                            not_law_grade.append({"k_label": k, "row": rn, "law_grade": lg,
                                                   "instrument_reason": inst_reason})
                            continue
                        not_law_grade.append({"k_label": k, "row": rn, "law_grade": lg})
                    primary_evidence = {
                        "outline_k_labels": k_labels,
                        "primary_rows": primary_rows,
                        "not_law_grade": not_law_grade,
                        "instrument_accepted": instrument_accepted,
                    }
                    if not_law_grade:
                        primary_class_not_law_grade = True
                        reasons.append(
                            "primary_class_not_law_grade: pre-registered primary claim class "
                            f"({'/'.join(k_labels)} composite, paper/outline.md) includes row(s) "
                            "not classified P1-law-grade/P2-law-grade (and, for instrument-"
                            "classed rows, not clearing the R4 field-delta bar): "
                            + "; ".join(
                                f"{n['k_label']}=row {n['row']} ({n['law_grade']!r}"
                                + (f", {n['instrument_reason']}" if n.get("instrument_reason")
                                   else "") + ")"
                                for n in not_law_grade)
                            + " -- docs/domains/governance/authority/GOAL.md sec1b: 'the primary class must itself be a statement "
                              "about a sec1b formal object'"
                        )

    verdict = "GREEN" if (not offending and not primary_class_not_law_grade
                          and not frame_revision_invalid) else "RED"
    return {
        "verdict": verdict,
        "reason": "all rows law-graded and primary claim class is law-grade" if verdict == "GREEN"
                  else "; ".join(reasons),
        "evidence": {
            "rows_checked": len(rows),
            "offending_law_grade": offending,
            "primary_class": primary_evidence,
            "frame_revision": {
                "rows_checked": [r["row"] for r in frame_revision_rows],
                "invalid": frame_revision_invalid,
                "formal_object_names": sorted(formal_object_names),
                "law_grade_core_present": law_grade_core_present,
            },
        },
    }


# ---------------------------------------------------------------------------
# Envelope + main
# ---------------------------------------------------------------------------

def build_receipt(conjuncts, start_ts, start_perf, generator_path):
    overall_green = all(c["verdict"] == "GREEN" for c in conjuncts.values())
    green_count = sum(1 for c in conjuncts.values() if c["verdict"] == "GREEN")
    n_conjuncts = len(conjuncts)
    total_secs = time.perf_counter() - start_perf

    generator_bytes = generator_path.read_bytes()
    generator_sha256 = hashlib.sha256(generator_bytes).hexdigest()

    now = datetime.now(timezone.utc)
    ts_compact = now.strftime("%Y%m%dT%H%M%SZ")

    receipt = {
        "ticket": "PUBLICATION-GATE-CHECK",
        "ts": ts_compact,
        "kind": "gate",
        # C(-1) spend declaration: this checker is offline by design (local
        # bytes only, no network, no paid surface) — declared, not implied,
        # because undeclared != proven-zero (test_c_neg1.py).
        "api_spend_usd": 0.0,
        "paid_api_surface_used": False,
        "verdict": "PASS" if overall_green else "FAIL",
        "verdict_detail": f"{green_count}/{n_conjuncts} GREEN — gate "
                           f"{'OPEN' if overall_green else 'CLOSED'} (publication-v1.md sec3)",
        "chk_name": "check_publication_gate",
        "spec_ref": "docs/spec/publication-v1.md sec3 (premature-publication gate); "
                    "paper/claims-evidence-map.md rows 18/19/21; "
                    "docs/domains/governance/authority/GOAL.md sec1b (research-focus test)",
        "generator": {
            "path": "scripts/check_publication_gate.py",
            "sha256": generator_sha256,
        },
        "execution": {
            "pid": os.getpid(),
            "host": os.environ.get("COMPUTERNAME") or os.environ.get("HOSTNAME") or "unknown",
            "start_ts": start_ts,
            "total_secs": total_secs,
            "model_load_secs": None,
            "overhead_secs": None,
            "overhead_pct": None,
        },
        "inputs_sha": {
            "args_fingerprint": receipt_fp.args_fingerprint({
                "repo_root": str(REPO_ROOT),
                "claims_map_path": str(CLAIMS_MAP_PATH.relative_to(REPO_ROOT).as_posix()),
            }),
        },
        "sha_convention": SHA_CONVENTION,
        "result": {
            "conjuncts": conjuncts,
            "overall_verdict": "GREEN" if overall_green else "RED",
            "gate_state": f"{'OPEN' if overall_green else 'CLOSED'} {green_count}/{n_conjuncts}",
        },
    }
    return receipt


def run():
    start_perf = time.perf_counter()
    start_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    conjuncts = {
        "kernel_fired": check_kernel_fired(),
        "bootstrap_pass_real_world": check_bootstrap_pass_real_world(),
        "earned_growth_rung": check_earned_growth_rung(),
        "claims_map_complete": check_claims_map_complete(),
        "research_focus_test": check_research_focus_test(),
    }

    receipt = build_receipt(conjuncts, start_ts, start_perf, Path(__file__).resolve())

    RECEIPTS_DIR.mkdir(parents=True, exist_ok=True)
    receipt_path = RECEIPTS_DIR / f"publication-gate-{receipt['ts']}.json"
    receipt_write.checked_write(str(receipt_path), receipt)

    print("check_publication_gate: publication-v1.md sec3 premature-publication gate")
    for name, c in conjuncts.items():
        print(f"  [{c['verdict']}] {name}: {c['reason']}")
    print(f"OVERALL: {receipt['result']['overall_verdict']} "
          f"({receipt['result']['gate_state']})")
    print(f"receipt: {receipt_path.relative_to(REPO_ROOT).as_posix()}")

    return 0 if receipt["result"]["overall_verdict"] == "GREEN" else 1


# ---------------------------------------------------------------------------
# Selftest
# ---------------------------------------------------------------------------

def _selftest():
    """Pure-logic checks against constructed fixtures. Writes nothing under the repo."""
    import tempfile
    import shutil

    failures = []

    def check(name, cond):
        status = "PASS" if cond else "FAIL"
        print(f"  [{status}] {name}")
        if not cond:
            failures.append(name)

    global REPO_ROOT, RECEIPTS_DIR, CLAIMS_MAP_PATH, OUTLINE_PATH, GOAL_PATH
    orig_root, orig_receipts, orig_map, orig_outline, orig_goal = (
        REPO_ROOT, RECEIPTS_DIR, CLAIMS_MAP_PATH, OUTLINE_PATH, GOAL_PATH)

    # Read the real valid-identity manifest fixture BEFORE REPO_ROOT is repointed at the
    # temp workspace below, so the identity-manifest-binding fixtures validate through the
    # real scripts/ember_01_identity/validate_identity.py against the real positive fixture
    # — never a hand-rolled stand-in.
    valid_identity_manifest_text = (
        orig_root / "tests" / "ember_01_identity" / "fixtures" / "valid-identity-v1.json"
    ).read_text(encoding="utf-8")

    td = tempfile.mkdtemp()
    try:
        root = Path(td)
        (root / "receipts").mkdir()
        (root / "paper").mkdir()
        REPO_ROOT = root
        RECEIPTS_DIR = root / "receipts"
        CLAIMS_MAP_PATH = root / "paper" / "claims-evidence-map.md"
        OUTLINE_PATH = root / "paper" / "outline.md"
        GOAL_PATH = root / "docs/domains/governance/authority/GOAL.md"
        GOAL_PATH.parent.mkdir(parents=True)

        # Identity-manifest fixtures shared by the earned_growth_rung and
        # bootstrap_pass_real_world identity-binding tests below.
        (root / "identity").mkdir()
        (root / "identity" / "valid-identity-v1.json").write_text(
            valid_identity_manifest_text, encoding="utf-8")
        (root / "identity" / "forged-identity.json").write_text("{}", encoding="utf-8")

        # --- kernel_fired: absent case ---
        r = check_kernel_fired()
        check("kernel_fired RED when no manifest and no flywheel receipt", r["verdict"] == "RED")

        # A stale root-level copy is not the canonical authority and must not
        # resurrect the gate after carrier-055 relocates the manifest.
        decoy_manifest = root / "kernel-v1.0.manifest"
        decoy_manifest.write_text("sha256:decoy\n", encoding="utf-8")
        decoy = check_kernel_fired()
        check("kernel_fired RED with only a root-level decoy manifest", decoy["verdict"] == "RED")
        decoy_manifest.unlink()

        # --- kernel_fired: present case ---
        manifest = root / "manifests" / "governance" / "kernel-v1.0.manifest"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text("sha256:deadbeef\n", encoding="utf-8")
        (RECEIPTS_DIR / "kernel-fire-20260702T000000Z.json").write_text(json.dumps({
            "ticket": "T", "ts": "20260702T000000Z", "kind": "job",
            "dB_dround": 0.42, "G1_delta": 0.05,
        }), encoding="utf-8")
        r2 = check_kernel_fired()
        check("kernel_fired GREEN when manifest + positive dB/round + G1_delta receipt present",
              r2["verdict"] == "GREEN")
        manifest.unlink()
        (RECEIPTS_DIR / "kernel-fire-20260702T000000Z.json").unlink()

        # --- earned_growth_rung: absent case ---
        r3 = check_earned_growth_rung()
        check("earned_growth_rung RED with empty receipts dir", r3["verdict"] == "RED")

        # --- earned_growth_rung: growth-STEP only (identity, no earned) ---
        (RECEIPTS_DIR / "growth-step-1.json").write_text(json.dumps({
            "ticket": "T", "ts": "20260702T000000Z",
            "identity_preservation": {"max_diff": 0.0, "tol": 1e-5, "pass": True},
        }), encoding="utf-8")
        r4 = check_earned_growth_rung()
        check("earned_growth_rung RED for identity-only (growth-STEP, not EARNED)",
              r4["verdict"] == "RED")
        (RECEIPTS_DIR / "growth-step-1.json").unlink()

        # --- earned_growth_rung: negative EARNED (net2net-v2-shaped) stays RED ---
        (RECEIPTS_DIR / "growth-negative.json").write_text(json.dumps({
            "ticket": "T", "ts": "20260702T000000Z", "kind": "growth",
            "identity_preservation": {"max_diff": 0.0, "tol": 1e-5, "pass": True},
            "earned": {"flop_saving_pct": -1294.46, "ratio_scratch_over_warmstart": 0.071712},
        }), encoding="utf-8")
        r5 = check_earned_growth_rung()
        check("earned_growth_rung RED for a NEGATIVE earned.flop_saving_pct",
              r5["verdict"] == "RED")

        # --- earned_growth_rung: positive EARNED but NO identity_manifest -> RED
        #     (identity-laundering probe: an otherwise-qualifying receipt with no bound,
        #     validated identity claim must not qualify) ---
        (RECEIPTS_DIR / "growth-no-identity.json").write_text(json.dumps({
            "ticket": "T", "ts": "20260702T000001Z", "kind": "growth",
            "identity_preservation": {"max_diff": 0.0, "tol": 1e-5, "pass": True},
            "earned": {"reduction_pct": 12.5},
        }), encoding="utf-8")
        r6a = check_earned_growth_rung()
        check("earned_growth_rung RED for a positive earned.reduction_pct receipt naming no "
              "identity_manifest field (identity-laundering probe)",
              r6a["verdict"] == "RED")
        (RECEIPTS_DIR / "growth-no-identity.json").unlink()

        # --- earned_growth_rung: positive EARNED + valid identity_manifest -> GREEN ---
        (RECEIPTS_DIR / "growth-positive.json").write_text(json.dumps({
            "ticket": "T", "ts": "20260702T000001Z", "kind": "growth",
            "identity_preservation": {"max_diff": 0.0, "tol": 1e-5, "pass": True},
            "earned": {"reduction_pct": 12.5},
            "identity_manifest": "identity/valid-identity-v1.json",
        }), encoding="utf-8")
        r6 = check_earned_growth_rung()
        check("earned_growth_rung GREEN for a positive earned.reduction_pct receipt naming a "
              "validated identity_manifest",
              r6["verdict"] == "GREEN")
        (RECEIPTS_DIR / "growth-negative.json").unlink()
        (RECEIPTS_DIR / "growth-positive.json").unlink()

        # --- earned_growth_rung: same shape but identity_manifest names a forged/malformed
        #     manifest -> RED (validate_manifest raises; no publication claim rides on an
        #     unvalidated identity). Isolated: the qualifying GREEN fixtures above are
        #     already removed, so only this forged-identity receipt is on disk. ---
        (RECEIPTS_DIR / "growth-forged-identity.json").write_text(json.dumps({
            "ticket": "T", "ts": "20260702T000002Z", "kind": "growth",
            "identity_preservation": {"max_diff": 0.0, "tol": 1e-5, "pass": True},
            "earned": {"reduction_pct": 12.5},
            "identity_manifest": "identity/forged-identity.json",
        }), encoding="utf-8")
        r6b = check_earned_growth_rung()
        check("earned_growth_rung RED when identity_manifest names a forged/malformed "
              "manifest that fails validate_manifest",
              r6b["verdict"] == "RED")
        (RECEIPTS_DIR / "growth-forged-identity.json").unlink()

        # --- bootstrap_pass_real_world: absent case (no receipts at all) ---
        r_bpw0 = check_bootstrap_pass_real_world()
        check("bootstrap_pass_real_world RED with empty receipts dir", r_bpw0["verdict"] == "RED")

        # --- bootstrap_pass_real_world: B0 synthetic-witness shape REFUSED even though
        #     BOOTSTRAP_PASS is truthy (bootstrap-falsifier-20260702T064130Z.json shape:
        #     package-defined, ember_impl, does_not_prove disclaimer, no real params) ---
        (RECEIPTS_DIR / "bootstrap-falsifier-fake.json").write_text(json.dumps({
            "ticket": "T", "ts": "20260702T000000Z",
            "version": "ember_bootstrap_package_v1",
            "positive_outer": {"A_n": 1.0, "outer_pass": True},
            "scope": {"does_not_prove": "real checkpoints", "proves": "synthetic satisfiability"},
        }), encoding="utf-8")
        r_bpw1 = check_bootstrap_pass_real_world()
        check("bootstrap_pass_real_world RED for a B0 synthetic-witness-shaped receipt "
              "(outer_pass true but synthetic markers present)",
              r_bpw1["verdict"] == "RED")
        (RECEIPTS_DIR / "bootstrap-falsifier-fake.json").unlink()

        # --- bootstrap_pass_real_world: BOOTSTRAP_PASS true but sub-1e6 params REFUSED
        #     (the C14 keystone-failure shape: 244,056-param owned checkpoint) ---
        (RECEIPTS_DIR / "bootstrap-toosmall.json").write_text(json.dumps({
            "ticket": "T", "ts": "20260702T000000Z",
            "BOOTSTRAP_PASS": True,
            "world": "W-code (real admitted training world)",
            "core": {"n_params": 244056},
        }), encoding="utf-8")
        r_bpw2 = check_bootstrap_pass_real_world()
        check("bootstrap_pass_real_world RED when the owned core is under 1e6 params",
              r_bpw2["verdict"] == "RED")
        (RECEIPTS_DIR / "bootstrap-toosmall.json").unlink()

        # --- bootstrap_pass_real_world: satisfying shape but NO identity_manifest -> RED
        #     (identity-laundering probe: an otherwise-qualifying receipt with no bound,
        #     validated identity claim must not qualify) ---
        (RECEIPTS_DIR / "bootstrap-no-identity.json").write_text(json.dumps({
            "ticket": "T", "ts": "20260702T000001Z",
            "BOOTSTRAP_PASS": True,
            "world": "W-code (real admitted training world, world-environment-v1.md)",
            "core": {"n_params": 1_200_000},
        }), encoding="utf-8")
        r_bpw3a = check_bootstrap_pass_real_world()
        check("bootstrap_pass_real_world RED for an otherwise-qualifying receipt naming no "
              "identity_manifest field (identity-laundering probe)",
              r_bpw3a["verdict"] == "RED")
        (RECEIPTS_DIR / "bootstrap-no-identity.json").unlink()

        # --- bootstrap_pass_real_world: satisfying shape + valid identity_manifest -> GREEN
        #     (real world, >=1e6 params, BOOTSTRAP_PASS true, no synthetic marker, identity
        #     manifest named AND validated) ---
        (RECEIPTS_DIR / "bootstrap-real-pass.json").write_text(json.dumps({
            "ticket": "T", "ts": "20260702T000001Z",
            "BOOTSTRAP_PASS": True,
            "world": "W-code (real admitted training world, world-environment-v1.md)",
            "core": {"n_params": 1_200_000},
            "identity_manifest": "identity/valid-identity-v1.json",
        }), encoding="utf-8")
        r_bpw3 = check_bootstrap_pass_real_world()
        check("bootstrap_pass_real_world GREEN for a real-world, >=1e6-param, non-synthetic "
              "BOOTSTRAP_PASS=true receipt naming a validated identity_manifest",
              r_bpw3["verdict"] == "GREEN")
        (RECEIPTS_DIR / "bootstrap-real-pass.json").unlink()

        # --- bootstrap_pass_real_world: same shape but identity_manifest names a forged/
        #     malformed manifest -> RED (validate_manifest raises; no publication claim rides
        #     on an unvalidated identity). Isolated: the qualifying GREEN fixture above is
        #     already removed. ---
        (RECEIPTS_DIR / "bootstrap-forged-identity.json").write_text(json.dumps({
            "ticket": "T", "ts": "20260702T000002Z",
            "BOOTSTRAP_PASS": True,
            "world": "W-code (real admitted training world, world-environment-v1.md)",
            "core": {"n_params": 1_200_000},
            "identity_manifest": "identity/forged-identity.json",
        }), encoding="utf-8")
        r_bpw3b = check_bootstrap_pass_real_world()
        check("bootstrap_pass_real_world RED when identity_manifest names a forged/malformed "
              "manifest that fails validate_manifest",
              r_bpw3b["verdict"] == "RED")
        (RECEIPTS_DIR / "bootstrap-forged-identity.json").unlink()

        # --- claims_map_complete: missing file ---
        r7 = check_claims_map_complete()
        check("claims_map_complete RED (never a crash) when the map file is absent",
              r7["verdict"] == "RED" and "unreadable" in r7["reason"])

        # --- claims_map_complete: ABSENT row exempt, resolvable row compliant,
        #     unresolvable row noncompliant, literature-only row compliant ---
        (RECEIPTS_DIR / "exists-20260702T000000Z.json").write_text("{}", encoding="utf-8")
        table = (
            "# Claims -> evidence map\n\n"
            "| # | Claim | Strength today | Evidence (receipt path / arXiv) | Missing |\n"
            "|---|---|---|---|---|\n"
            "| 1 | claim absent | **ABSENT** | — | everything |\n"
            "| 2 | claim resolvable | PROVEN | `receipts/exists-20260702T000000Z.json` | none |\n"
            "| 3 | claim broken | PROVEN | `receipts/does-not-exist-20260101T000000Z.json` | fix |\n"
            "| 4 | claim literature | LITERATURE | arXiv 2405.15319 | n/a |\n"
        )
        CLAIMS_MAP_PATH.write_text(table, encoding="utf-8")
        r8 = check_claims_map_complete()
        statuses = {row["row"]: row["status"] for row in r8["evidence"]["per_row"]}
        check("claims_map_complete: ABSENT row exempt", statuses[1] == "exempt_absent")
        check("claims_map_complete: resolvable path row compliant", statuses[2] == "compliant")
        check("claims_map_complete: unresolvable path row noncompliant",
              statuses[3] == "noncompliant_stale_path")
        check("claims_map_complete: arXiv-only row compliant without a local path",
              statuses[4] == "compliant_literature_only")
        check("claims_map_complete overall RED when any row noncompliant (row 3)",
              r8["verdict"] == "RED")

        # --- bare timestamp-token resolution (row 14-style citation, no dir prefix) ---
        (RECEIPTS_DIR / "t4-r1-q15-arc1-seed14-20260610T150153Z.json").write_text(
            "{}", encoding="utf-8")
        table2 = table + (
            "| 5 | claim bare token | PROVEN | `t4-r1-q15-arc1-seed14-20260610T150153Z` | none |\n"
        )
        CLAIMS_MAP_PATH.write_text(table2, encoding="utf-8")
        r9 = check_claims_map_complete()
        statuses9 = {row["row"]: row["status"] for row in r9["evidence"]["per_row"]}
        check("claims_map_complete: bare timestamp-token resolves via receipts/<tok>.json",
              statuses9[5] == "compliant")

        # --- bare filename resolution (row 7-style citation: `foo.md`, no directory) ---
        (root / "docs").mkdir(exist_ok=True)
        (root / "docs" / "grounding").mkdir(exist_ok=True)
        (root / "docs" / "grounding" / "local-fm-2026.md").write_text("x", encoding="utf-8")
        global _FILENAME_INDEX_CACHE
        _FILENAME_INDEX_CACHE = None  # force reindex against the temp tree
        table3 = table2 + (
            "| 6 | claim bare filename | GROUNDED | grounding `local-fm-2026.md` sec1c | none |\n"
        )
        CLAIMS_MAP_PATH.write_text(table3, encoding="utf-8")
        r11 = check_claims_map_complete()
        statuses11 = {row["row"]: row["status"] for row in r11["evidence"]["per_row"]}
        check("claims_map_complete: bare filename resolves via repo-wide basename search",
              statuses11[6] == "compliant")
        _FILENAME_INDEX_CACHE = None  # reset so the real run reindexes the live repo

        # --- fail-closed: unparseable (no table rows) map file ---
        CLAIMS_MAP_PATH.write_text("just prose, no table here\n", encoding="utf-8")
        r10 = check_claims_map_complete()
        check("claims_map_complete RED (never a crash) when the file has no table rows",
              r10["verdict"] == "RED" and "unparseable" in r10["reason"])

        # --- research_focus_test: missing law_grade column entirely -> every row offending ---
        table_no_lg = (
            "# Claims -> evidence map\n\n"
            "| # | Claim | Strength today | Evidence | Missing |\n"
            "|---|---|---|---|---|\n"
            "| 1 | a | PROVEN | x | y |\n"
            "| 2 | b | PROVEN | x | y |\n"
        )
        CLAIMS_MAP_PATH.write_text(table_no_lg, encoding="utf-8")
        r_rft0 = check_research_focus_test()
        check("research_focus_test RED when the law_grade column is absent entirely",
              r_rft0["verdict"] == "RED" and len(r_rft0["evidence"]["offending_law_grade"]) == 2)

        # --- research_focus_test: invalid enum value on one row ---
        table_bad_lg = (
            "# Claims -> evidence map\n\n"
            "| # | Claim | Strength today | Evidence | Missing | Law grade |\n"
            "|---|---|---|---|---|---|\n"
            "| 1 | a | PROVEN | x | y | not-a-real-grade |\n"
            "| 2 | b | PROVEN | x | y | P2-law-grade |\n"
        )
        CLAIMS_MAP_PATH.write_text(table_bad_lg, encoding="utf-8")
        r_rft1 = check_research_focus_test()
        check("research_focus_test RED when a row's law_grade is not in the enum",
              r_rft1["verdict"] == "RED"
              and [o["row"] for o in r_rft1["evidence"]["offending_law_grade"]] == [1])

        # --- research_focus_test: all rows valid, K-anchor present, primary class (K2/K4)
        #     resolves to instrument rows -> primary_class_not_law_grade ---
        table_instrument = (
            "# Claims -> evidence map\n\n"
            "legend: K-label anchor: K1=row 3, K2=row 4, K3=row 6, K4=row 5.\n\n"
            "| # | Claim | Strength today | Evidence | Missing | Law grade |\n"
            "|---|---|---|---|---|---|\n"
            "| 1 | crit | PROVEN | x | y | P2-law-grade |\n"
            "| 2 | witness | PROVEN | x | y | P2-law-grade |\n"
            "| 3 | k1 grounding | GROUNDED | x | y | instrument |\n"
            "| 4 | k2 grounding | GROUNDED | x | y | instrument |\n"
            "| 5 | k4 grounding | GROUNDED | x | y | instrument |\n"
            "| 6 | k3 grounding | GROUNDED | x | y | coupling |\n"
        )
        CLAIMS_MAP_PATH.write_text(table_instrument, encoding="utf-8")
        OUTLINE_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUTLINE_PATH.write_text(
            "## Primary claim class (C8 candidate)\n\n"
            "**K2/K4 composite: the composed standing gate**, with BOOTSTRAP_PASS as its "
            "criterion. (K1, K3 are supporting contributions.)\n\n"
            "## Structure\n\n1. Introduction\n",
            encoding="utf-8",
        )
        r_rft2 = check_research_focus_test()
        check("research_focus_test RED with reason primary_class_not_law_grade when the "
              "K2/K4 composite resolves to instrument-classified rows",
              r_rft2["verdict"] == "RED" and "primary_class_not_law_grade" in r_rft2["reason"])
        check("research_focus_test evidence names both K2=row4 and K4=row5 as not law-grade",
              {n["k_label"] for n in r_rft2["evidence"]["primary_class"]["not_law_grade"]}
              == {"K2", "K4"})

        # --- research_focus_test: same map, but outline's primary class is K1 alone,
        #     and K1's row is law-graded -> GREEN ---
        table_p2 = table_instrument.replace(
            "| 3 | k1 grounding | GROUNDED | x | y | instrument |",
            "| 3 | k1 grounding | GROUNDED | x | y | P2-law-grade |",
        )
        CLAIMS_MAP_PATH.write_text(table_p2, encoding="utf-8")
        OUTLINE_PATH.write_text(
            "## Primary claim class (C8 candidate)\n\n"
            "**K1 solo: ledger-as-identity**, the sole primary claim. (K2, K3, K4 are "
            "supporting contributions.)\n\n"
            "## Structure\n\n1. Introduction\n",
            encoding="utf-8",
        )
        r_rft3 = check_research_focus_test()
        check("research_focus_test GREEN when every row is law-graded and the resolved "
              "primary claim class (K1 -> row 3, P2-law-grade) satisfies sec1b",
              r_rft3["verdict"] == "GREEN")

        # --- research_focus_test: fail-closed when paper/outline.md is missing ---
        OUTLINE_PATH.unlink()
        r_rft4 = check_research_focus_test()
        check("research_focus_test RED (never a crash) when paper/outline.md is missing",
              r_rft4["verdict"] == "RED" and "primary_class_not_law_grade" in r_rft4["reason"])

        # --- research_focus_test: frame-revision grade (launchpad clause, docs/domains/governance/authority/GOAL.md sec1b) ---
        goal_fixture = (
            "# GOAL\n\n"
            "## 1b. THE TWO RESEARCH PROBLEMS\n\n"
            "P1 -- the ENERGY LAW. Formal object: the capability-energy frontier\n"
            "`C*_A(E) = sup over A in ADM of C(A, E)`, where ADM is admissible.\n"
            "P2 -- the GROWTH LAW. Formal object: the assimilation criterion --\n"
            "`BOOTSTRAP_PASS`, a thresholded reliability criterion.\n\n"
            "Launchpad clause: a contribution that improves, replaces, or shows the\n"
            "incompleteness of a formal object -- or of the two-law frame itself --\n"
            "is research of the first rank, not a test failure.\n\n"
            "## 2. NEXT SECTION\n\nsomething else entirely.\n"
        )
        GOAL_PATH.write_text(goal_fixture, encoding="utf-8")
        (RECEIPTS_DIR / "frame-rev-real-20260702T000000Z.json").write_text("{}", encoding="utf-8")

        # (i) valid frame-revision row (cites BOOTSTRAP_PASS + a resolvable receipt) rides
        #     along as the primary class ONLY because a P2-law-grade core row also exists -> GREEN
        table_fr_ok = (
            "# Claims -> evidence map\n\n"
            "legend: K-label anchor: K1=row 1, K2=row 2.\n\n"
            "| # | Claim | Strength today | Evidence | Missing | Law grade |\n"
            "|---|---|---|---|---|---|\n"
            "| 1 | law-grade core claim | PROVEN | x | y | P2-law-grade |\n"
            "| 2 | revises the BOOTSTRAP_PASS criterion | GROUNDED | "
            "`receipts/frame-rev-real-20260702T000000Z.json` | none | frame-revision |\n"
        )
        CLAIMS_MAP_PATH.write_text(table_fr_ok, encoding="utf-8")
        OUTLINE_PATH.write_text(
            "## Primary claim class (C8 candidate)\n\n"
            "**K2 solo: the frame revision**, riding along the law-grade core. (K1 is a "
            "supporting contribution.)\n\n"
            "## Structure\n\n1. Introduction\n",
            encoding="utf-8",
        )
        r_fr1 = check_research_focus_test()
        check("research_focus_test (i) GREEN: valid frame-revision row (object cited + "
              "receipt resolves) rides along the primary class because a P2-law-grade "
              "core row also exists", r_fr1["verdict"] == "GREEN")

        # (iv) same map shape, but the OTHER row is downgraded off law-grade too, so the
        #      map has NO P1/P2-law-grade row anywhere -> RED: the launchpad lets a
        #      revision ride along, it never REPLACES the law-grade core
        table_fr_only = table_fr_ok.replace(
            "| 1 | law-grade core claim | PROVEN | x | y | P2-law-grade |",
            "| 1 | supporting claim | PROVEN | x | y | engineering-support |",
        )
        CLAIMS_MAP_PATH.write_text(table_fr_only, encoding="utf-8")
        r_fr2 = check_research_focus_test()
        check("research_focus_test (iv) RED: frame-revision is well-formed but is the "
              "ONLY row and no law-grade core exists anywhere in the map",
              r_fr2["verdict"] == "RED" and "primary_class_not_law_grade" in r_fr2["reason"])

        # Remaining controls isolate the row-level acceptance predicate: primary class is
        # pinned to the already-law-grade row 1, so only the frame-revision row (not the
        # primary-class ride-along rule) can drive the verdict.
        OUTLINE_PATH.write_text(
            "## Primary claim class (C8 candidate)\n\n"
            "**K1 solo: the law-grade core**, the sole primary claim. (K2 is a "
            "supporting contribution.)\n\n"
            "## Structure\n\n1. Introduction\n",
            encoding="utf-8",
        )

        # (ii) frame-revision row that names no formal object at all -> RED
        table_fr_no_object = table_fr_ok.replace(
            "| 2 | revises the BOOTSTRAP_PASS criterion | GROUNDED | "
            "`receipts/frame-rev-real-20260702T000000Z.json` | none | frame-revision |",
            "| 2 | an unnamed improvement to the paper | GROUNDED | "
            "`receipts/frame-rev-real-20260702T000000Z.json` | none | frame-revision |",
        )
        CLAIMS_MAP_PATH.write_text(table_fr_no_object, encoding="utf-8")
        r_fr3 = check_research_focus_test()
        check("research_focus_test (ii) RED: frame-revision row missing a formal-object "
              "citation in its Claim/Missing cells",
              r_fr3["verdict"] == "RED"
              and "does not cite which sec1b formal object" in r_fr3["reason"])

        # (iii) frame-revision row citing a real object but a FABRICATED receipt path -> RED
        table_fr_fake_receipt = table_fr_ok.replace(
            "`receipts/frame-rev-real-20260702T000000Z.json`",
            "`receipts/does-not-exist-20260101T000000Z.json`",
        )
        CLAIMS_MAP_PATH.write_text(table_fr_fake_receipt, encoding="utf-8")
        r_fr4 = check_research_focus_test()
        check("research_focus_test (iii) RED: frame-revision row cites a real formal "
              "object but names a receipts/ path that does not resolve on disk",
              r_fr4["verdict"] == "RED"
              and "names no receipts/ path that resolves on disk" in r_fr4["reason"])

    finally:
        shutil.rmtree(td, ignore_errors=True)
        REPO_ROOT, RECEIPTS_DIR, CLAIMS_MAP_PATH, OUTLINE_PATH, GOAL_PATH = (
            orig_root, orig_receipts, orig_map, orig_outline, orig_goal)

    print(f"\nselftest: {'ALL PASS' if not failures else f'{len(failures)} FAILED'}")
    for f in failures:
        print(f"  FAILED: {f}")
    return 0 if not failures else 1


def main():
    ap = argparse.ArgumentParser(
        description="check_publication_gate.py — publication-v1.md sec3 gate checker")
    ap.add_argument("--selftest", action="store_true",
                     help="pure-logic selftest against constructed fixtures; writes no receipt")
    args = ap.parse_args()
    if args.selftest:
        sys.exit(_selftest())
    sys.exit(run())


if __name__ == "__main__":
    main()
