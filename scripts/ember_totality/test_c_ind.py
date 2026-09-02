#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""test_c_ind.py -- STATUS PROBE for Ember goal condition C-IND.

Condition (authoritative, docs/domains/governance/authority/GOAL.md §1 item 6 / §4.0 amendment 10;
docs/spec/operator-independence-v1.md is the full contract):

  C-IND -- operator-independence proof surface. R: the actual goal's completion
  generates receipts proving Ember stands as a whole comprehensive system and
  is stable and fully operable by any person WITHOUT the maintainer or any LLM
  assistant in the loop. Ten operator verbs (interact, talk; observe;
  activate, deactivate; customize, study, experiment; understand, comprehend)
  group into five receipt classes:
    IND-1 INTERACT   -- documented boot -> real rendered prompt turn -> clean exit.
    IND-2 OBSERVE     -- IMPORTS C-OBS's own tokens; green only if C-OBS is green.
    IND-3 OPERATE     -- documented launch + teardown + an interrupted-stop
                          resume case, teardown carrying its own post-stop
                          process-table capture.
    IND-4 CUSTOMIZE+EXPERIMENT -- documented config-surface change with
                          before/after, AND a documented re-run of a receipted
                          experiment matching the banked receipt within tolerance.
    IND-5 COMPREHEND  -- [ISSUE #88 RE-SPEC, 2026-07-04] four machine-checkable
                          legs, ALL required for GREEN (scripts/ember_totality/
                          ind5_comprehend_producer.py's comprehend_v2 receipt):
                          entry_point_integrity (README resolves, links real),
                          completeness (every live CLI command named in the
                          operator docs), freshness (every doc-cited command
                          exists in the live registry), executability (every
                          extracted runnable example exits 0). Operator
                          directive (verbatim class): no board condition may
                          require operator action -- the RETIRED [A]-audit-only
                          operator-attestation leg (schema modeled on docs/spec/
                          operator-acceptance-v1.md's acceptance/v1) was a fact
                          about a human mind, unfalsifiable by the system, and
                          parked a board RED on a person. Retained under
                          attestation_superseded_by for audit continuity; its
                          script-authored-invalid trap STAYS enforced below so
                          a legacy claim cannot be faked retroactively, but it
                          no longer counts toward GREEN on its own.

  Falsifiers (docs/spec/operator-independence-v1.md §3):
    invalid_doc_pointer_dead            [S] any command/path cited by an IND
                                         receipt that does not exist on disk.
    invalid_interactive_dead_cockpit    [S] an IND-1 receipt claiming
                                         interaction with no rendered-frame
                                         evidence (the D6 signature --
                                         docs/clicompare/ defines it).
    invalid_teardown_orphan             [S] an IND-3 teardown receipt missing
                                         its own post-stop process-table
                                         capture, or showing survivors.
    invalid_comprehension_by_script     [S] any RETIRED IND-5 [A] receipt
                                         (leg=="a_attested") asserting operator
                                         comprehension mechanically -- a fake
                                         evaluator is itself a violation, and
                                         this check is FAIL-CLOSED: it fires
                                         even if every other class (including a
                                         fully-passing comprehend_v2 receipt)
                                         is otherwise satisfying. Kept for
                                         audit continuity (issue #88) so a
                                         legacy claim cannot be faked
                                         retroactively; the [A] field itself no
                                         longer gates GREEN.
    invalid_assistant_in_loop           [A] audit-only (session-lineage
                                         provenance is not receipt-shaped);
                                         this probe cannot check it and does
                                         not claim to.

  This probe checks PRESENCE + SHAPE of receipts under receipts/ (or the
  EMBER_TOTALITY_ROOT fixture root) -- it does not itself re-derive the
  organism-component / doc-pointer enumeration (that is the IND-5 [S]
  receipt's own job, mirroring how C-MANIFEST validates a manifest rather
  than re-planning it). Command-STRING fields (e.g. documented_boot_command)
  are read, never executed -- only doc_pointer PATH fields are checked for
  on-disk existence, the same side-effect-free discipline every other status
  probe in this package already holds to.

TDD discipline: this is a STATUS PROBE. It ALWAYS exits 0; it prints exactly
one line "RED <reason>" or "GREEN <reason>" so the totality board can
aggregate. It determines RED/GREEN by REALLY inspecting state under the
resolved root -- it never hardcodes the verdict. Current honest state
(operator-independence-v1.md §6, 2026-07-02): ZERO receipts in any class --
"no IND-class receipts" is the correct live RED.

Run:  PYTHONIOENCODING=utf-8 python test_c_ind.py
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Locate the real state root -- identical resolution order to every other
# lane-14 probe (test_c_obs.py / test_c_manifest.py): EMBER_TOTALITY_ROOT env
# var first, then this repo's own root, then the legacy <external-state> nesting.
# ---------------------------------------------------------------------------

def _find_state_root() -> Path | None:
    _repo_root = Path(__file__).resolve().parent.parent.parent
    _env_root = os.environ.get("EMBER_TOTALITY_ROOT")
    candidates = [
        Path(_env_root) if _env_root else None,
        _repo_root,
        _repo_root / "<external-state>",
    ]
    for c in candidates:
        if c is None:
            continue
        try:
            if c.is_dir():
                return c
        except OSError:
            continue
    return None


_CLASS_RE = re.compile(r"^IND-([1-5])$")

# [ISSUE #97 cure 6, 2026-07-04] Discovery was receipt_class-field-keyed with
# NO directory/provenance binding: ANY *.json anywhere under receipts/ could
# self-declare "receipt_class": "IND-<n>" and be accepted as evidence, even
# sitting in a directory with no relation to operator-independence at all.
# Two real, observed constraints every genuine IND receipt in this repo's
# corpus already satisfies (verified against all 16 real IND receipts on
# disk 2026-07-04 -- ind1/ind3/ind4/ind5 loose files, receipts/
# ember-operator-independence/, receipts/ind1-context-carry-cure/,
# receipts/ind3-operate-cure/, receipts/acceptance/c-ind-comprehension-*.json
# -- every single one contains "ind" in its own relative path AND, for
# classes 1 and 3 specifically, always carries one of these real,
# pinned-from-the-corpus producer-identity field names):
_IND_PATH_TOKEN_RE = re.compile(r"ind", re.IGNORECASE)
_IND_PRODUCER_FIELDS = {
    "generator", "import_provenance", "cure_provenance",
    "checker", "verified_by", "assembled_by", "producer",
}
# Classes 4 and 5 are not required to carry one of these named fields in
# addition -- their existing per-class shape checks (_validate_ind4's
# banked_receipt_ref/fresh_receipt_ref citation pair, _validate_ind5's
# legs/exec_root/spec_amendment structure) are ALREADY a strict, structural
# provenance binding in their own right; every real IND-4/IND-5 receipt
# observed on disk satisfies those, but none carries a field from the set
# above, so requiring it here would regress genuine evidence, not harden
# against fabrication.
_PRODUCER_FIELD_REQUIRED_CLASSES = {1, 3}


def _classify_ind_receipts(root: Path) -> dict[int, list[tuple[Path, dict]]]:
    """Walk root/receipts/ (recursively), parse every *.json, and bucket any
    dict carrying a recognized "receipt_class": "IND-<n>" field -- PROVIDED
    it also passes the [ISSUE #97 cure 6] directory/provenance binding below.
    Non-JSON, unparseable, non-dict files, or files that self-declare an IND
    class from an unbound location are silently skipped (they are not
    ADMISSIBLE IND receipts, not a probe error)."""
    by_class: dict[int, list[tuple[Path, dict]]] = {1: [], 2: [], 3: [], 4: [], 5: []}
    receipts_dir = root / "receipts"
    if not receipts_dir.is_dir():
        return by_class
    for dirpath, dirnames, filenames in os.walk(receipts_dir):
        if ".git" in Path(dirpath).parts:
            continue
        for name in filenames:
            if not name.endswith(".json"):
                continue
            p = Path(dirpath) / name
            try:
                obj = json.loads(p.read_text(encoding="utf-8", errors="replace"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            if not isinstance(obj, dict):
                continue
            m = _CLASS_RE.match(str(obj.get("receipt_class", "")))
            if not m:
                continue
            cls = int(m.group(1))
            # [ISSUE #97 cure 6] directory binding: the path itself (not
            # merely the JSON content) must carry an "ind" token somewhere,
            # matching every real receipt's own on-disk location.
            rel = str(p.relative_to(receipts_dir))
            if not _IND_PATH_TOKEN_RE.search(rel):
                continue
            # [ISSUE #97 cure 6] producer-provenance binding, classes 1/3.
            if cls in _PRODUCER_FIELD_REQUIRED_CLASSES and not (_IND_PRODUCER_FIELDS & set(obj.keys())):
                continue
            by_class[cls].append((p, obj))
    return by_class


def _rel(p: Path, root: Path) -> str:
    try:
        return str(p.relative_to(root))
    except ValueError:
        return str(p)


# --- IND-1 INTERACT ----------------------------------------------------------

def _validate_ind1(entries, root: Path):
    """Return (satisfied, invalid_tokens, reason)."""
    if not entries:
        return False, set(), "IND-1 absent"
    dead_cockpit_hits = []
    ok = None
    for p, obj in entries:
        claims_interaction = bool(obj.get("documented_boot_command") or obj.get("clean_exit"))
        rendered = obj.get("rendered_frame_evidence")
        has_rendered = bool(rendered) if not isinstance(rendered, (dict, list)) else bool(rendered)
        if claims_interaction and not has_rendered:
            dead_cockpit_hits.append(_rel(p, root))
            continue
        # [HARDENED 2026-07-03] shape fields alone allowed a 3-of-4 matrix to
        # satisfy IND-1 (the spec's four-element session matrix was never
        # mechanically checked). The receipt must now ATTEST the full matrix:
        # matrix_complete must be exactly True and matrix_missing empty/absent.
        # An honest partial receipt (matrix_complete false) keeps IND-1 open.
        matrix_ok = (obj.get("matrix_complete") is True
                     and not obj.get("matrix_missing"))
        if (obj.get("clean_exit") is True and obj.get("documented_boot_command")
                and obj.get("doc_pointer") and has_rendered and matrix_ok):
            ok = (p, obj)
    if dead_cockpit_hits:
        return (False, {"invalid_interactive_dead_cockpit"},
                "IND-1 receipt(s) claim interaction with no rendered-frame evidence "
                "(D6-class dead cockpit): " + ", ".join(dead_cockpit_hits))
    if ok:
        return True, set(), f"IND-1 satisfied via {_rel(ok[0], root)}"
    return False, set(), "IND-1 receipt(s) present but incomplete shape"


# --- IND-2 OBSERVE (imported from C-OBS, never duplicated) -------------------

def _check_ind2(root: Path):
    probe_path = Path(__file__).resolve().parents[2] / "src" / "ember" / "governance" / "scripts" / "ember_totality" / "test_c_obs.py"
    env = dict(os.environ)
    env["EMBER_TOTALITY_ROOT"] = str(root)
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        proc = subprocess.run(
            [sys.executable, str(probe_path)],
            cwd=str(probe_path.parent),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace",
            env=env, timeout=60,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return False, f"C-OBS import check failed to execute: {exc}"
    lines = (proc.stdout or "").strip().splitlines()
    line = lines[0].strip() if lines else ""
    if line.startswith("GREEN"):
        return True, f"C-OBS GREEN ({line})"
    return False, f"C-OBS not GREEN ({line or f'no output, exit={proc.returncode}'})"


# --- IND-3 OPERATE -------------------------------------------------------------

def _validate_ind3(entries, root: Path):
    legs: dict[str, tuple[Path, dict]] = {}
    failures: list[str] = []
    for p, obj in entries:
        leg = obj.get("leg")
        rel = _rel(p, root)
        if leg == "launch":
            if obj.get("verified_alive") is not True:
                failures.append(f"{rel}: verified_alive is not true")
                continue
            heartbeat = obj.get("heartbeat_ready")
            if not isinstance(heartbeat, dict) or heartbeat.get("status") != "ready":
                failures.append(f"{rel}: heartbeat_ready is not ready")
                continue
            legs.setdefault("launch", (p, obj))
        elif leg == "teardown":
            pst = obj.get("post_stop_process_table")
            if not isinstance(pst, dict):
                failures.append(f"{rel}: post_stop_process_table absent or malformed")
                continue
            survivors = pst.get("survivors")
            if survivors is None or survivors or pst.get("orphaned_gpu_state", False):
                failures.append(f"{rel}: post_stop_process_table shows unknown/surviving process or orphaned GPU state")
                continue
            heartbeat = obj.get("final_heartbeat")
            if obj.get("exit_code") != 0 or not isinstance(heartbeat, dict) or heartbeat.get("status") != "stopped":
                failures.append(f"{rel}: teardown exit_code/final_heartbeat is not clean")
                continue
            legs.setdefault("teardown", (p, obj))
        elif leg == "interrupted_resume":
            cleanup = obj.get("final_cleanup")
            heartbeat = obj.get("resumed_ready_heartbeat")
            checks = {
                "interrupt_command_exit_code": obj.get("interrupt_command_exit_code") == 0,
                "interrupted_pid_verified_dead": obj.get("interrupted_pid_verified_dead") is True,
                "interrupted_launcher_pid_verified_dead": obj.get("interrupted_launcher_pid_verified_dead") is True,
                "resumed_verified_alive": obj.get("resumed_verified_alive") is True,
                "resumed_ready_heartbeat": isinstance(heartbeat, dict) and heartbeat.get("status") == "ready",
                "final_cleanup": isinstance(cleanup, dict) and cleanup.get("exit_code") == 0,
                "post_stop_survivors": isinstance(cleanup, dict) and cleanup.get("post_stop_survivors") == [],
            }
            failed = [name for name, passed in checks.items() if not passed]
            if failed:
                failures.append(f"{rel}: invalid {', '.join(failed)}")
                continue
            legs.setdefault("interrupted_resume", (p, obj))
    if failures:
        return False, {"invalid_operate_evidence"}, "; ".join(failures)
    missing = [leg for leg in ("launch", "teardown", "interrupted_resume") if leg not in legs]
    if missing:
        return False, set(), f"IND-3 missing leg(s): {', '.join(missing)}"
    return True, set(), "IND-3 launch + clean teardown + interrupted-resume all executed and independently verified"

# --- IND-4 CUSTOMIZE + EXPERIMENT ---------------------------------------------

def _validate_ind4(entries, root: Path):
    legs: dict[str, tuple[Path, dict]] = {}
    for p, obj in entries:
        leg = obj.get("leg")
        if leg == "customize" and obj.get("config_file_edited") and "before" in obj and "after" in obj:
            legs.setdefault("customize", (p, obj))
        elif leg == "experiment_reproduction" and obj.get("banked_receipt_ref") and \
                obj.get("fresh_receipt_ref") and obj.get("within_tolerance") is True:
            legs.setdefault("experiment_reproduction", (p, obj))
    missing = [l for l in ("customize", "experiment_reproduction") if l not in legs]
    if missing:
        return False, set(), f"IND-4 missing/incomplete leg(s): {', '.join(missing)}"
    return True, set(), "IND-4 customize + experiment-reproduction both present with required fields"


# --- IND-5 COMPREHEND (issue #88 re-spec: four machine-checkable legs) ------
#
# Operator directive (2026-07-04, verbatim class): no board condition may
# require operator action -- conditions must be properties of the SYSTEM,
# not the operator. The OLD [A] leg below (a dated operator-attestation
# object) was a fact about a human mind, unfalsifiable by the system, and
# parked a board RED on a person. GREEN now requires a `comprehend_v2`
# receipt (src/ember/governance/scripts/ember_totality/ind5_comprehend_producer.py) whose four
# legs -- entry_point_integrity, completeness, freshness, executability --
# ALL pass. The OLD [A] field's script-authored-invalid trap
# (invalid_comprehension_by_script) STAYS enforced, fail-closed, checked
# FIRST, exactly as before -- audit continuity means a legacy claim cannot
# be faked retroactively, even though the OLD field no longer counts
# toward GREEN on its own.

def _validate_ind5(entries, root: Path):
    a_entries = [(p, o) for p, o in entries if o.get("leg") == "a_attested"]
    v2_entries = [(p, o) for p, o in entries if o.get("leg") == "comprehend_v2"]

    # OLD [A] shape validation is FAIL-CLOSED and checked first, unchanged
    # from the pre-#88 probe: any claimed attestation that is not operator-
    # attestation-shaped is itself the violation, regardless of what else
    # (including a fully-passing comprehend_v2 receipt) is satisfied.
    script_hits = []
    for p, obj in a_entries:
        accepted_by = str(obj.get("accepted_by", "")).strip()
        verbatim = obj.get("verbatim")
        ts = obj.get("ts")
        if not (accepted_by == "operator" and isinstance(verbatim, str) and verbatim.strip() and ts):
            script_hits.append(
                f"{_rel(p, root)}: not operator-attestation-shaped "
                f"(accepted_by={accepted_by!r}, verbatim="
                f"{'present' if isinstance(verbatim, str) and verbatim.strip() else 'MISSING'}, "
                f"ts={'present' if ts else 'MISSING'})"
            )
    if script_hits:
        return False, {"invalid_comprehension_by_script"}, "; ".join(script_hits)

    # NEW shape (issue #88): comprehend_v2, four machine-checkable legs, ALL
    # must pass. The retired [S]/[A] fields (s_checkable / a_attested) are
    # audit history only from here down -- neither counts toward GREEN.
    if not v2_entries:
        return False, set(), "IND-5 comprehend_v2 receipt absent (issue #88 shape required for GREEN)"

    required_legs = ("entry_point_integrity", "completeness", "freshness", "executability")
    dead_pointers = []
    ok = None
    incomplete_hits = []
    for p, obj in v2_entries:
        legs = obj.get("legs")
        spec_amendment = obj.get("spec_amendment")
        superseded = obj.get("attestation_superseded_by")
        if not (isinstance(legs, dict) and all(isinstance(legs.get(n), dict) for n in required_legs)
                and isinstance(spec_amendment, dict) and isinstance(superseded, dict)):
            incomplete_hits.append(f"{_rel(p, root)}: missing required leg(s)/spec_amendment/attestation_superseded_by")
            continue
        epi_dead = legs["entry_point_integrity"].get("dead_links")
        if epi_dead:
            dead_pointers.extend(f"{_rel(p, root)}: {d}" for d in epi_dead)
            continue
        all_passed = all(bool(legs[n].get("passed")) for n in required_legs)
        if all_passed and obj.get("all_four_legs_passed") is True:
            ok = (p, obj)
    if dead_pointers:
        return False, {"invalid_doc_pointer_dead"}, "IND-5 entry_point_integrity cites dead path(s): " + "; ".join(dead_pointers)
    if ok:
        return True, set(), f"IND-5 satisfied via {_rel(ok[0], root)} (all four comprehend_v2 legs passed)"
    if incomplete_hits:
        return False, set(), "IND-5 comprehend_v2 receipt(s) malformed: " + "; ".join(incomplete_hits)
    return False, set(), "IND-5 comprehend_v2 receipt(s) present but one or more legs failed"


# --- cross-class doc_pointer existence (IND-1..4) -----------------------------

def _scan_dead_pointers(entries, root: Path):
    dead = []
    for p, obj in entries:
        val = obj.get("doc_pointer")
        if isinstance(val, str) and val and not (root / val).is_file():
            dead.append(f"{val!r} (cited by {_rel(p, root)}#doc_pointer)")
    return dead


def _inspect(root: Path):
    by_class = _classify_ind_receipts(root)

    invalid_hits: set[str] = set()
    detail: list[str] = []

    ind1_ok, ind1_inv, ind1_reason = _validate_ind1(by_class[1], root)
    invalid_hits |= ind1_inv
    if ind1_inv:
        detail.append(ind1_reason)

    ind3_ok, ind3_inv, ind3_reason = _validate_ind3(by_class[3], root)
    invalid_hits |= ind3_inv
    if ind3_inv:
        detail.append(ind3_reason)

    ind4_ok, ind4_inv, ind4_reason = _validate_ind4(by_class[4], root)
    invalid_hits |= ind4_inv
    if ind4_inv:
        detail.append(ind4_reason)

    ind5_ok, ind5_inv, ind5_reason = _validate_ind5(by_class[5], root)
    invalid_hits |= ind5_inv
    if ind5_inv:
        detail.append(ind5_reason)

    dead_ptrs = _scan_dead_pointers(by_class[1] + by_class[3] + by_class[4], root)
    if dead_ptrs:
        invalid_hits.add("invalid_doc_pointer_dead")
        detail.append("dead doc_pointer(s): " + "; ".join(dead_ptrs))

    # Fail-closed: any invalid token found is RED, regardless of what else
    # is satisfied (invalid_comprehension_by_script most of all -- a fake
    # evaluator is itself a violation, per operator-independence-v1.md §3).
    if invalid_hits:
        return ("RED",
                "invalid token(s) matched: " + ", ".join(sorted(invalid_hits))
                + " -- " + "; ".join(detail),
                sorted(invalid_hits))

    ind2_ok, ind2_reason = _check_ind2(root)

    missing = []
    if not ind1_ok:
        missing.append(f"IND-1 INTERACT ({ind1_reason})")
    if not ind2_ok:
        missing.append(f"IND-2 OBSERVE ({ind2_reason})")
    if not ind3_ok:
        missing.append(f"IND-3 OPERATE ({ind3_reason})")
    if not ind4_ok:
        missing.append(f"IND-4 CUSTOMIZE+EXPERIMENT ({ind4_reason})")
    if not ind5_ok:
        missing.append(f"IND-5 COMPREHEND ({ind5_reason})")

    if len(missing) == 5:
        return ("RED",
                "no IND-class receipts under receipts/ -- C-IND boots RED on all five "
                "classes (operator-independence-v1.md §6 honest baseline); root=" + str(root),
                [])

    if missing:
        return ("RED",
                f"{len(missing)}/5 IND classes unsatisfied: " + "; ".join(missing),
                [])

    return ("GREEN",
             "all five IND receipt classes present+shaped (IND-2 imports C-OBS=GREEN); "
             f"{ind2_reason}; no invalid token matched",
             [])


def main() -> int:
    root = _find_state_root()
    if root is None:
        print("RED state root not found on any resolution candidate -- cannot inspect real receipts")
        return 0
    verdict, reason, _invalid = _inspect(root)
    print(f"{verdict} {reason}")
    return 0


if __name__ == "__main__":
    # STATUS PROBE: always exit 0; verdict is in stdout.
    sys.exit(main())
